import csv
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.analyze_musl_changes_with_claude import (
    MUSL_ANALYSIS_HEADERS,
    analyze_rows,
    classify_commit_subject,
    infer_file_class,
    infer_scope,
    list_file_commits,
    load_musl_rows,
    normalize_analysis_result,
    parse_analysis_json,
    summarize_change_source,
)


class FakeBackend:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def analyze(self, *, prompt: str, cwd: Path, model: str, max_turns: int) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class AnalyzeMuslChangesWithClaudeTests(unittest.IsolatedAsyncioTestCase):
    def test_infer_file_class_and_scope(self) -> None:
        self.assertEqual(infer_file_class("include/pthread.h"), "公共头文件")
        self.assertEqual(infer_file_class("src/thread/pthread_detach.c"), "源码文件")
        self.assertEqual(infer_scope("arch/aarch64/atomic_arch.h"), "aarch64")
        self.assertEqual(infer_scope("include/pthread.h"), "全局")

    def test_classify_and_summarize_commit_subjects(self) -> None:
        self.assertEqual(classify_commit_subject("[Backport] fix thread"), "Backport")
        self.assertEqual(classify_commit_subject("[Huawei] adjust detach"), "Huawei")
        self.assertEqual(classify_commit_subject("misc tweak"), "未归类")

    def test_parse_and_normalize_analysis_json(self) -> None:
        parsed = parse_analysis_json(
            '{"修改类型":["线程语义","错误码处理"],"修改内容摘要":"调整 detach 行为","关联接口":["pthread_detach"],"变更影响结论":"可能改变错误码表现","风险等级":"高","备注":"需要复核"}'
        )
        normalized = normalize_analysis_result(parsed)
        self.assertEqual(normalized["修改类型"], "线程语义；错误码处理")
        self.assertEqual(normalized["关联接口"], "pthread_detach")
        self.assertEqual(normalized["风险等级"], "高")

    async def test_analyze_rows_uses_git_history_and_excludes_oldest_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            self._init_git_repo(repo)
            file_path = repo / "include/pthread.h"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("int pthread_detach(void);\n", encoding="utf-8")
            self._commit_all(repo, "import musl baseline")
            file_path.write_text("int pthread_detach(void);\n#define MUSL_BP 1\n", encoding="utf-8")
            self._commit_all(repo, "[Backport] sync detach handling")
            file_path.write_text("int pthread_detach(void);\n#define MUSL_BP 1\n#define MUSL_HW 1\n", encoding="utf-8")
            self._commit_all(repo, "[Huawei] adjust detach semantics")

            rows = [{header: "" for header in MUSL_ANALYSIS_HEADERS}]
            rows[0]["文件路径"] = "include/pthread.h"
            backend = FakeBackend(
                {
                    "修改类型": ["线程语义", "错误码处理"],
                    "修改内容摘要": "在自研提交里补充 pthread 相关宏定义与行为约束",
                    "关联接口": ["pthread_detach"],
                    "变更影响结论": "可能改变调用方观察到的线程相关行为，需结合调用点复核",
                    "风险等级": "中",
                    "备注": "优先检查线程销毁路径",
                }
            )

            result = await analyze_rows(
                rows,
                backend=backend,
                repo_root=repo,
                timeout_seconds=5,
                retries=0,
                concurrency=1,
                max_turns=2,
                max_commits_per_file=5,
                max_diff_lines_per_commit=80,
                cwd=repo,
                model="sonnet",
                exclude_oldest_commit=True,
                show_progress=False,
                verbose=False,
            )

            self.assertEqual(result[0]["变更来源"], "Backport+Huawei")
            self.assertEqual(result[0]["Backport提交数"], "1")
            self.assertEqual(result[0]["Huawei提交数"], "1")
            self.assertEqual(result[0]["未归类提交数"], "0")
            self.assertEqual(result[0]["分析状态"], "已分析")
            self.assertEqual(result[0]["关联接口"], "pthread_detach")
            self.assertEqual(backend.calls, 1)

    async def test_analyze_rows_marks_no_self_changes_when_only_baseline_commit_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            self._init_git_repo(repo)
            file_path = repo / "src/thread/pthread_detach.c"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("return 0;\n", encoding="utf-8")
            self._commit_all(repo, "import musl baseline")

            rows = [{header: "" for header in MUSL_ANALYSIS_HEADERS}]
            rows[0]["文件路径"] = "src/thread/pthread_detach.c"
            backend = FakeBackend({})
            result = await analyze_rows(
                rows,
                backend=backend,
                repo_root=repo,
                timeout_seconds=5,
                retries=0,
                concurrency=1,
                max_turns=2,
                max_commits_per_file=5,
                max_diff_lines_per_commit=80,
                cwd=repo,
                model="sonnet",
                exclude_oldest_commit=True,
                show_progress=False,
                verbose=False,
            )

            self.assertEqual(result[0]["变更来源"], "无自研修改")
            self.assertEqual(result[0]["分析状态"], "无自研修改")
            self.assertEqual(result[0]["风险等级"], "低")
            self.assertEqual(backend.calls, 0)

    async def test_analyze_rows_prints_progress_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            self._init_git_repo(repo)
            file_path = repo / "include/elf.h"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("#define EM_NUM 1\n", encoding="utf-8")
            self._commit_all(repo, "import musl baseline")
            file_path.write_text("#define EM_NUM 2\n", encoding="utf-8")
            self._commit_all(repo, "[Backport] add loongarch ids")

            rows = [{header: "" for header in MUSL_ANALYSIS_HEADERS}]
            rows[0]["文件路径"] = "include/elf.h"
            backend = FakeBackend(
                {
                    "修改类型": ["架构适配"],
                    "修改内容摘要": "补充 LoongArch 相关常量定义",
                    "关联接口": [],
                    "变更影响结论": "主要是架构常量补充，未直接看到公开接口行为变化",
                    "风险等级": "低",
                    "备注": "",
                }
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                await analyze_rows(
                    rows,
                    backend=backend,
                    repo_root=repo,
                    timeout_seconds=5,
                    retries=0,
                    concurrency=1,
                    max_turns=2,
                    max_commits_per_file=5,
                    max_diff_lines_per_commit=80,
                    cwd=repo,
                    model="sonnet",
                    exclude_oldest_commit=True,
                )

            output = buffer.getvalue()
            self.assertIn("开始分析 1 个文件", output)
            self.assertIn("[1/1] include/elf.h -> 已分析", output)

    def test_load_musl_rows_accepts_legacy_single_column_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "musl.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["文件名"])
                writer.writerow(["src/thread/pthread_detach.c"])
            rows = load_musl_rows(csv_path)
            self.assertEqual(rows[0]["文件路径"], "src/thread/pthread_detach.c")
            self.assertEqual(rows[0]["文件分类"], "源码文件")

    def test_list_file_commits_reads_subjects_from_git_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            self._init_git_repo(repo)
            file_path = repo / "include/elf.h"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("#define EM_NUM 1\n", encoding="utf-8")
            self._commit_all(repo, "import musl baseline")
            file_path.write_text("#define EM_NUM 2\n", encoding="utf-8")
            self._commit_all(repo, "[Backport] add loongarch ids")

            commits = list_file_commits(repo, "include/elf.h")
            self.assertEqual(len(commits), 2)
            self.assertEqual(commits[0].subject, "[Backport] add loongarch ids")
            self.assertEqual(commits[-1].subject, "import musl baseline")
            source, counts = summarize_change_source(commits[:-1])
            self.assertEqual(source, "仅Backport")
            self.assertEqual(counts["Backport"], 1)

    def _init_git_repo(self, repo: Path) -> None:
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)

    def _commit_all(self, repo: Path, subject: str) -> None:
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", subject], cwd=repo, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
