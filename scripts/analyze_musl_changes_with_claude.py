from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

GLIBC_ANALYSIS_HEADERS = [
    "接口名",
    "接口分类",
    "glibc手册覆盖情况",
    "glibc手册位置",
    "POSIX规范覆盖情况",
    "POSIX规范位置",
    "功能差异类型",
    "功能差异结论",
    "行为差异类型",
    "行为差异结论",
    "行为差异摘要",
    "关联musl文件",
    "证据位置",
    "分析状态",
    "优先级",
    "备注",
]

MUSL_ANALYSIS_HEADERS = [
    "文件路径",
    "文件分类",
    "作用范围",
    "当前是否存在",
    "变更来源",
    "Backport提交数",
    "Huawei提交数",
    "未归类提交数",
    "修改类型",
    "修改内容摘要",
    "关联接口",
    "变更影响结论",
    "风险等级",
    "分析状态",
    "备注",
]

DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_RETRIES = 2
DEFAULT_CONCURRENCY = 3
DEFAULT_MAX_TURNS = 6
DEFAULT_MAX_COMMITS_PER_FILE = 5
DEFAULT_MAX_DIFF_LINES_PER_COMMIT = 200

SYSTEM_PROMPT = textwrap.dedent(
    """
    你是资深 libc / POSIX 兼容性分析工程师。
    目标是基于文件 git 历史中的自研提交，分析 musl 文件改动是否可能影响公开接口行为。

    规则：
    1. 只基于输入里的提交标题、差异内容和文件路径下结论，不要编造未出现的实现细节。
    2. 将标题前缀 [Backport] 视为社区回合，将 [Huawei] 视为自研改动；其它前缀视为未归类提交。
    3. 优先关注返回值、错误码、线程语义、取消点、结构体布局、宏定义、ABI、系统调用封装。
    4. 如果无法直接映射到公开接口，请明确写“未直接看到公开接口行为变化，需结合调用点复核”。
    5. 输出必须是 JSON 对象，不要 Markdown，不要代码块。
    6. 风险等级只能填写：高 / 中 / 低。
    7. 修改类型请输出字符串数组，元素尽量使用：返回值处理、错误码处理、线程语义、取消点、ABI、宏定义、结构体布局、系统调用封装、架构适配、启动流程、其他。
    """
).strip()


@dataclass(slots=True)
class GitCommitInfo:
    commit_id: str
    subject: str
    category: str


@dataclass(slots=True)
class GitFileContext:
    relative_path: str
    file_class: str
    scope: str
    current_exists: bool
    change_source: str
    backport_count: int
    huawei_count: int
    unclassified_count: int
    commit_excerpt: str


class AnalysisBackend(Protocol):
    async def analyze(self, *, prompt: str, cwd: Path, model: str, max_turns: int) -> str:
        ...


class ClaudeSdkBackend:
    def __init__(self) -> None:
        try:
            from claude_code_sdk import ClaudeCodeOptions, query  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "未安装 Python 版 Claude Code SDK，请先运行 scripts/install_claude_code_sdk.sh，或改用 --backend cli。"
            ) from exc
        self._options_cls = ClaudeCodeOptions
        self._query = query

    async def analyze(self, *, prompt: str, cwd: Path, model: str, max_turns: int) -> str:
        options = self._options_cls(
            cwd=str(cwd),
            model=model,
            max_turns=max_turns,
            system_prompt=SYSTEM_PROMPT,
        )
        final_result: str | None = None
        async for message in self._query(prompt=prompt, options=options):
            payload = _message_to_dict(message)
            if payload.get("type") == "result":
                result = payload.get("result")
                if result is not None:
                    final_result = str(result)
        if not final_result:
            raise RuntimeError("Claude Code SDK 未返回最终结果。")
        return final_result


class ClaudeCliBackend:
    def __init__(self, executable: str = "claude") -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise RuntimeError("当前环境未找到 claude 命令，无法使用 CLI fallback。")
        self._executable = resolved

    async def analyze(self, *, prompt: str, cwd: Path, model: str, max_turns: int) -> str:
        process = await asyncio.create_subprocess_exec(
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--max-turns",
            str(max_turns),
            "--system-prompt",
            SYSTEM_PROMPT,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(prompt.encode("utf-8"))
        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace").strip() or stdout.decode(
                "utf-8", errors="replace"
            ).strip()
            raise RuntimeError(f"claude CLI 调用失败: {error_text}")
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
        result = payload.get("result")
        if result is None:
            raise RuntimeError("claude CLI JSON 输出中缺少 result 字段。")
        return str(result)


def _message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    for method_name in ("model_dump", "dict"):
        method = getattr(message, method_name, None)
        if callable(method):
            payload = method()
            if isinstance(payload, dict):
                return payload
    if hasattr(message, "__dict__"):
        return {key: value for key, value in vars(message).items() if not key.startswith("_")}
    raise TypeError(f"无法解析 SDK 消息类型: {type(message)!r}")


def infer_file_class(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("include/"):
        return "公共头文件"
    if normalized.startswith("src/"):
        return "源码文件"
    if normalized.startswith("arch/"):
        return "架构相关文件"
    if normalized.startswith("crt/"):
        return "启动文件"
    if normalized.startswith("tools/"):
        return "工具文件"
    return "其他文件"


def infer_scope(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    if not parts:
        return "全局"
    if parts[0] == "arch" and len(parts) > 1:
        return parts[1]
    return "全局"


def load_musl_rows(csv_path: Path | str) -> list[dict[str, str]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 缺少表头: {path}")
        fieldnames = [name.strip() for name in reader.fieldnames]
        path_key = "文件路径" if "文件路径" in fieldnames else fieldnames[0]
        rows: list[dict[str, str]] = []
        for source_row in reader:
            relative_path = (source_row.get(path_key) or "").strip()
            if not relative_path:
                continue
            row = {header: (source_row.get(header) or "").strip() for header in MUSL_ANALYSIS_HEADERS}
            row["文件路径"] = relative_path
            if not row["文件分类"]:
                row["文件分类"] = infer_file_class(relative_path)
            if not row["作用范围"]:
                row["作用范围"] = infer_scope(relative_path)
            rows.append(row)
    return rows


def load_existing_enriched_rows(csv_path: Path | str) -> dict[str, dict[str, str]]:
    path = Path(csv_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "文件路径" not in [name.strip() for name in reader.fieldnames]:
            return {}
        rows_by_path: dict[str, dict[str, str]] = {}
        for source_row in reader:
            relative_path = (source_row.get("文件路径") or "").strip()
            if not relative_path:
                continue
            rows_by_path[relative_path] = {
                header: (source_row.get(header) or "").strip() for header in MUSL_ANALYSIS_HEADERS
            }
        return rows_by_path


def is_processed_row(row: dict[str, str]) -> bool:
    status = (row.get("分析状态") or "").strip()
    return status not in {"", "未开始"}


def merge_base_and_existing_row(base_row: dict[str, str], existing_row: dict[str, str] | None) -> dict[str, str]:
    merged = {header: base_row.get(header, "") for header in MUSL_ANALYSIS_HEADERS}
    if existing_row:
        for header in MUSL_ANALYSIS_HEADERS:
            value = existing_row.get(header, "")
            if value:
                merged[header] = value
    if not merged["文件分类"]:
        merged["文件分类"] = infer_file_class(merged["文件路径"])
    if not merged["作用范围"]:
        merged["作用范围"] = infer_scope(merged["文件路径"])
    return merged


def ensure_git_repo(repo_root: Path | str) -> Path:
    root = Path(repo_root)
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"不是有效的 git 仓库: {root}")
    return Path(completed.stdout.strip())


def run_git(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        error_text = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(error_text or f"git 命令失败: {' '.join(args)}")
    return completed.stdout


def list_file_commits(repo_root: Path, relative_path: str) -> list[GitCommitInfo]:
    try:
        output = run_git(
            repo_root,
            [
                "log",
                "--follow",
                "--format=%H%x1f%s",
                "--",
                relative_path,
            ],
        )
    except RuntimeError:
        return []
    commits: list[GitCommitInfo] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        commit_id, subject = line.split("\x1f", 1)
        commits.append(
            GitCommitInfo(
                commit_id=commit_id.strip(),
                subject=subject.strip(),
                category=classify_commit_subject(subject.strip()),
            )
        )
    return commits


def classify_commit_subject(subject: str) -> str:
    if subject.startswith("[Backport]"):
        return "Backport"
    if subject.startswith("[Huawei]"):
        return "Huawei"
    return "未归类"


def select_self_developed_commits(
    commits: list[GitCommitInfo],
    *,
    exclude_oldest_commit: bool,
) -> list[GitCommitInfo]:
    if not exclude_oldest_commit:
        return commits
    if len(commits) <= 1:
        return []
    return commits[:-1]


def summarize_change_source(commits: list[GitCommitInfo]) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter(commit.category for commit in commits)
    if not commits:
        return "无自研修改", counts
    if counts["未归类"] > 0:
        parts: list[str] = []
        if counts["Backport"] > 0:
            parts.append("Backport")
        if counts["Huawei"] > 0:
            parts.append("Huawei")
        parts.append("未归类")
        return "+".join(parts), counts
    if counts["Backport"] > 0 and counts["Huawei"] > 0:
        return "Backport+Huawei", counts
    if counts["Backport"] > 0:
        return "仅Backport", counts
    if counts["Huawei"] > 0:
        return "仅Huawei", counts
    return "存在未归类修改", counts


def truncate_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    kept = lines[:max_lines]
    kept.append(f"... 已截断，原始总行数 {len(lines)}，当前仅保留前 {max_lines} 行")
    return "\n".join(kept)


def build_commit_excerpt(
    repo_root: Path,
    relative_path: str,
    commits: list[GitCommitInfo],
    *,
    max_commits_per_file: int,
    max_diff_lines_per_commit: int,
) -> str:
    if not commits:
        return ""
    excerpts: list[str] = []
    selected = commits[:max_commits_per_file]
    for commit in selected:
        try:
            patch = run_git(
                repo_root,
                [
                    "show",
                    "--stat=120,80",
                    "--unified=3",
                    commit.commit_id,
                    "--",
                    relative_path,
                ],
            )
        except RuntimeError as exc:
            patch = f"git show 失败: {exc}"
        patch = truncate_lines(patch.strip(), max_diff_lines_per_commit)
        excerpts.append(
            textwrap.dedent(
                f"""
                提交分类: {commit.category}
                提交ID: {commit.commit_id}
                提交标题: {commit.subject}
                差异内容:
                {patch}
                """
            ).strip()
        )
    omitted = len(commits) - len(selected)
    if omitted > 0:
        excerpts.append(f"另有 {omitted} 个提交未展开，以控制上下文大小。")
    return "\n\n".join(excerpts)


def build_file_context(
    repo_root: Path,
    relative_path: str,
    *,
    max_commits_per_file: int,
    max_diff_lines_per_commit: int,
    exclude_oldest_commit: bool,
) -> GitFileContext:
    commits = list_file_commits(repo_root, relative_path)
    self_commits = select_self_developed_commits(commits, exclude_oldest_commit=exclude_oldest_commit)
    change_source, counts = summarize_change_source(self_commits)
    return GitFileContext(
        relative_path=relative_path,
        file_class=infer_file_class(relative_path),
        scope=infer_scope(relative_path),
        current_exists=(repo_root / relative_path).exists(),
        change_source=change_source,
        backport_count=counts["Backport"],
        huawei_count=counts["Huawei"],
        unclassified_count=counts["未归类"],
        commit_excerpt=build_commit_excerpt(
            repo_root,
            relative_path,
            self_commits,
            max_commits_per_file=max_commits_per_file,
            max_diff_lines_per_commit=max_diff_lines_per_commit,
        ),
    )


def build_analysis_prompt(context: GitFileContext) -> str:
    commit_excerpt = context.commit_excerpt or "排除基线提交后，没有需要分析的自研提交。"
    return textwrap.dedent(
        f"""
        请分析以下 musl 文件的自研变更，并评估这些变更对公开接口行为的潜在影响。

        文件路径: {context.relative_path}
        文件分类: {context.file_class}
        作用范围: {context.scope}
        当前是否存在: {'是' if context.current_exists else '否'}
        变更来源: {context.change_source}
        Backport提交数: {context.backport_count}
        Huawei提交数: {context.huawei_count}
        未归类提交数: {context.unclassified_count}

        请输出一个 JSON 对象，字段必须如下：
        {{
          "修改类型": ["返回值处理"],
          "修改内容摘要": "一句话总结这组提交改了什么",
          "关联接口": ["pthread_detach"],
          "变更影响结论": "说明是否可能带来行为变化，若不能直接确认请写需结合调用点复核",
          "风险等级": "高",
          "备注": "可选补充说明"
        }}

        提交与差异内容如下：
        {commit_excerpt}
        """
    ).strip()


def parse_analysis_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                raise ValueError("返回结果不是 JSON object")
            return parsed
        except Exception as exc:
            last_error = exc
    raise ValueError(f"无法解析模型输出为 JSON: {last_error}")


def normalize_analysis_result(parsed: dict[str, Any]) -> dict[str, str]:
    modification_types = parsed.get("修改类型") or []
    related_symbols = parsed.get("关联接口") or []
    if isinstance(modification_types, str):
        modification_types = [modification_types]
    if isinstance(related_symbols, str):
        related_symbols = [related_symbols]
    risk_level = str(parsed.get("风险等级") or "低").strip() or "低"
    if risk_level not in {"高", "中", "低"}:
        risk_level = "中"
    return {
        "修改类型": "；".join(str(item).strip() for item in modification_types if str(item).strip()),
        "修改内容摘要": str(parsed.get("修改内容摘要") or "").strip(),
        "关联接口": "；".join(str(item).strip() for item in related_symbols if str(item).strip()),
        "变更影响结论": str(parsed.get("变更影响结论") or "").strip(),
        "风险等级": risk_level,
        "备注": str(parsed.get("备注") or "").strip(),
    }


def select_backend(name: str) -> AnalysisBackend:
    if name == "sdk":
        return ClaudeSdkBackend()
    if name == "cli":
        return ClaudeCliBackend()
    if name != "auto":
        raise ValueError(f"不支持的 backend: {name}")
    try:
        return ClaudeSdkBackend()
    except RuntimeError:
        return ClaudeCliBackend()


def describe_backend(backend: AnalysisBackend) -> str:
    if isinstance(backend, ClaudeSdkBackend):
        return "sdk"
    if isinstance(backend, ClaudeCliBackend):
        return "cli"
    return backend.__class__.__name__


def emit_line(message: str, *, enabled: bool = True, stream: Any = None) -> None:
    if not enabled:
        return
    target = sys.stdout if stream is None else stream
    print(message, file=target, flush=True)


def format_progress_line(done: int, total: int, row: dict[str, str]) -> str:
    risk = row.get("风险等级") or "-"
    source = row.get("变更来源") or "-"
    status = row.get("分析状态") or "-"
    return f"[{done}/{total}] {row['文件路径']} -> {status} | 来源={source} | 风险={risk}"


def materialize_rows_snapshot(
    base_rows: list[dict[str, str]],
    current_results: list[dict[str, str] | None],
) -> list[dict[str, str]]:
    snapshot: list[dict[str, str]] = []
    for index, base_row in enumerate(base_rows):
        row = current_results[index] if current_results[index] is not None else base_row
        snapshot.append({header: row.get(header, "") for header in MUSL_ANALYSIS_HEADERS})
    return snapshot


def write_snapshot(
    base_rows: list[dict[str, str]],
    current_results: list[dict[str, str] | None],
    output_csv: Path | str | None,
    output_json: Path | str | None,
) -> None:
    snapshot_rows = materialize_rows_snapshot(base_rows, current_results)
    if output_csv is not None:
        write_csv(snapshot_rows, output_csv)
    if output_json is not None:
        write_json(snapshot_rows, output_json)


async def analyze_rows(
    rows: list[dict[str, str]],
    *,
    backend: AnalysisBackend,
    repo_root: Path,
    timeout_seconds: int,
    retries: int,
    concurrency: int,
    max_turns: int,
    max_commits_per_file: int,
    max_diff_lines_per_commit: int,
    cwd: Path,
    model: str,
    exclude_oldest_commit: bool,
    show_progress: bool = True,
    verbose: bool = False,
    existing_rows_by_path: dict[str, dict[str, str]] | None = None,
    output_csv: Path | str | None = None,
    output_json: Path | str | None = None,
    autosave: bool = True,
    pending_limit: int | None = None,
) -> list[dict[str, str]]:
    total = len(rows)
    if total == 0:
        emit_line("没有待分析的文件。", enabled=show_progress)
        return []

    existing_rows_by_path = existing_rows_by_path or {}
    base_rows = [merge_base_and_existing_row(row, existing_rows_by_path.get(row["文件路径"])) for row in rows]
    current_results: list[dict[str, str] | None] = [None] * total
    pending_indices: list[int] = []

    for index, row in enumerate(base_rows):
        if is_processed_row(row):
            current_results[index] = row
        else:
            pending_indices.append(index)

    skipped_existing = total - len(pending_indices)
    if pending_limit is not None:
        pending_indices = pending_indices[:pending_limit]
    pending_set = set(pending_indices)

    emit_line(
        f"开始分析 {total} 个文件 | 已处理 {skipped_existing} | 待处理 {len(pending_indices)} | backend={describe_backend(backend)} | model={model} | concurrency={concurrency} | timeout={timeout_seconds}s | retries={retries}",
        enabled=show_progress,
    )

    if autosave and (output_csv is not None or output_json is not None):
        write_snapshot(base_rows, current_results, output_csv, output_json)

    if not pending_indices:
        emit_line("没有待处理文件，已直接复用现有结果。", enabled=show_progress)
        return materialize_rows_snapshot(base_rows, current_results)

    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    completed = skipped_existing
    contexts: dict[int, GitFileContext] = {
        index: build_file_context(
            repo_root,
            base_rows[index]["文件路径"],
            max_commits_per_file=max_commits_per_file,
            max_diff_lines_per_commit=max_diff_lines_per_commit,
            exclude_oldest_commit=exclude_oldest_commit,
        )
        for index in pending_indices
    }

    async def worker(index: int) -> None:
        nonlocal completed
        row = base_rows[index]
        context = contexts[index]
        if verbose:
            async with progress_lock:
                emit_line(f"开始处理: {row['文件路径']}")
        async with semaphore:
            result = await analyze_single_row(
                row=row,
                context=context,
                backend=backend,
                timeout_seconds=timeout_seconds,
                retries=retries,
                max_turns=max_turns,
                cwd=cwd,
                model=model,
                verbose=verbose,
            )
        async with progress_lock:
            current_results[index] = result
            completed += 1
            if autosave and (output_csv is not None or output_json is not None):
                write_snapshot(base_rows, current_results, output_csv, output_json)
            emit_line(format_progress_line(completed, total, result), enabled=show_progress)

    tasks = [asyncio.create_task(worker(index)) for index in pending_indices if index in pending_set]
    await asyncio.gather(*tasks)
    return materialize_rows_snapshot(base_rows, current_results)


async def analyze_single_row(
    *,
    row: dict[str, str],
    context: GitFileContext,
    backend: AnalysisBackend,
    timeout_seconds: int,
    retries: int,
    max_turns: int,
    cwd: Path,
    model: str,
    verbose: bool,
) -> dict[str, str]:
    enriched = {header: row.get(header, "") for header in MUSL_ANALYSIS_HEADERS}
    enriched["文件分类"] = context.file_class
    enriched["作用范围"] = context.scope
    enriched["当前是否存在"] = "是" if context.current_exists else "否"
    enriched["变更来源"] = context.change_source
    enriched["Backport提交数"] = str(context.backport_count)
    enriched["Huawei提交数"] = str(context.huawei_count)
    enriched["未归类提交数"] = str(context.unclassified_count)

    if not context.current_exists:
        enriched["分析状态"] = "跳过（文件不存在）"
        enriched["备注"] = merge_notes(enriched["备注"], "当前源码仓中不存在该文件")
        return enriched
    if context.change_source == "无自研修改":
        enriched["分析状态"] = "无自研修改"
        enriched["变更影响结论"] = enriched["变更影响结论"] or "按当前规则排除最早提交后，未检测到自研修改"
        enriched["风险等级"] = enriched["风险等级"] or "低"
        return enriched
    if not context.commit_excerpt:
        enriched["分析状态"] = "需人工复核"
        enriched["备注"] = merge_notes(enriched["备注"], "存在自研提交，但未能抽取可分析差异")
        return enriched

    prompt = build_analysis_prompt(context)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if verbose:
                emit_line(f"调用模型: {row['文件路径']} | attempt={attempt + 1}/{retries + 1}")
            raw_text = await asyncio.wait_for(
                backend.analyze(
                    prompt=prompt,
                    cwd=cwd,
                    model=model,
                    max_turns=max_turns,
                ),
                timeout=timeout_seconds,
            )
            parsed = parse_analysis_json(raw_text)
            normalized = normalize_analysis_result(parsed)
            for key, value in normalized.items():
                if value:
                    enriched[key] = value
            enriched["分析状态"] = "已分析"
            return enriched
        except Exception as exc:
            last_error = exc
            if verbose:
                emit_line(f"模型失败: {row['文件路径']} | attempt={attempt + 1}/{retries + 1} | error={exc}", stream=sys.stderr)
            if attempt < retries:
                await asyncio.sleep(min(2**attempt, 8))
    enriched["分析状态"] = "分析失败"
    enriched["备注"] = merge_notes(enriched["备注"], f"分析失败: {last_error}")
    return enriched


def merge_notes(existing: str, incoming: str) -> str:
    existing = existing.strip()
    incoming = incoming.strip()
    if not existing:
        return incoming
    if not incoming:
        return existing
    return f"{existing}；{incoming}"


def write_csv(rows: list[dict[str, str]], output_path: Path | str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MUSL_ANALYSIS_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, str]], output_path: Path | str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    risk_counter = Counter(row.get("风险等级", "") for row in rows)
    status_counter = Counter(row.get("分析状态", "") for row in rows)
    source_counter = Counter(row.get("变更来源", "") for row in rows)
    pending_unprocessed = sum(1 for row in rows if not is_processed_row(row))
    payload = {
        "summary": {
            "total": len(rows),
            "analyzed": status_counter.get("已分析", 0),
            "no_self_changes": status_counter.get("无自研修改", 0),
            "missing_file": status_counter.get("跳过（文件不存在）", 0),
            "manual_review": status_counter.get("需人工复核", 0),
            "failed": status_counter.get("分析失败", 0),
            "pending_unprocessed": pending_unprocessed,
            "risk_high": risk_counter.get("高", 0),
            "risk_medium": risk_counter.get("中", 0),
            "risk_low": risk_counter.get("低", 0),
        },
        "change_source": dict(source_counter),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def async_main(args: argparse.Namespace) -> int:
    repo_root = ensure_git_repo(args.repo_root)
    rows = load_musl_rows(args.csv)
    existing_rows_by_path = load_existing_enriched_rows(args.output_csv) if args.resume_existing else {}
    backend = select_backend(args.backend)
    analyzed_rows = await analyze_rows(
        rows,
        backend=backend,
        repo_root=repo_root,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        concurrency=args.concurrency,
        max_turns=args.max_turns,
        max_commits_per_file=args.max_commits_per_file,
        max_diff_lines_per_commit=args.max_diff_lines_per_commit,
        cwd=Path(args.cwd),
        model=args.model,
        exclude_oldest_commit=args.exclude_oldest_commit,
        show_progress=not args.quiet,
        verbose=args.verbose,
        existing_rows_by_path=existing_rows_by_path,
        output_csv=args.output_csv,
        output_json=args.output_json,
        autosave=not args.no_autosave,
        pending_limit=args.limit,
    )
    summary = Counter(row.get("分析状态", "") for row in analyzed_rows)
    emit_line(
        "rows={total}, analyzed={analyzed}, no_self_changes={no_self_changes}, missing_file={missing_file}, manual_review={manual_review}, failed={failed}, pending={pending}".format(
            total=len(analyzed_rows),
            analyzed=summary.get("已分析", 0),
            no_self_changes=summary.get("无自研修改", 0),
            missing_file=summary.get("跳过（文件不存在）", 0),
            manual_review=summary.get("需人工复核", 0),
            failed=summary.get("分析失败", 0),
            pending=sum(1 for row in analyzed_rows if not is_processed_row(row)),
        ),
        enabled=True,
    )
    emit_line(f"csv: {args.output_csv}", enabled=True)
    emit_line(f"json: {args.output_json}", enabled=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 Claude Code SDK 分析 musl 文件 git 历史中的自研改动及其潜在行为影响。")
    parser.add_argument("--csv", default="musl_file_modify_analyse.csv")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-csv", default="out/musl/musl_file_modify_analyse.enriched.csv")
    parser.add_argument("--output-json", default="out/musl/musl_file_modify_analyse.enriched.json")
    parser.add_argument("--backend", choices=["auto", "sdk", "cli"], default="auto")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--max-commits-per-file", type=int, default=DEFAULT_MAX_COMMITS_PER_FILE)
    parser.add_argument("--max-diff-lines-per-commit", type=int, default=DEFAULT_MAX_DIFF_LINES_PER_COMMIT)
    parser.add_argument("--exclude-oldest-commit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resume-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-autosave", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
