# glibc / POSIX / musl 手册差异分析 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立一条可复现的分析流水线：先定位 `glibc/manual/` 与官方 POSIX 规范，再抽取功能差异与行为差异，最后在需要时结合 musl 源码与仓库 diff 生成快速报告。

**Architecture:** 采用“glibc manual 定位 + POSIX 官方规范定位 + 手册语义比较 + 源码补证 + 报告生成”的最小方案。主语料只保留本地 `glibc-2.34/manual/` 和 Open Group 官方 `Issue 8 / POSIX.1-2024` HTML 归档；`musl` 源码只在 POSIX 留白、实现相关行为或 glibc manual 缺项时介入。当前宿主机是 macOS，因此禁止默认回落到本机 `manpath`。

**Tech Stack:** Python 3、`csv` / `json` / `argparse` / `subprocess`、`unittest`、可选 `docker`、只读 `git diff`

**Source Policy:**
- `glibc`：优先使用本地 `glibc-2.34/manual/`；找不到条目时再回 glibc 源码。
- `POSIX`：优先使用 The Open Group `Issue 8 / POSIX.1-2024` 官方下载归档。
- `musl`：默认不作为主语料；仅在 POSIX 留白或行为属实现定义时，回本地 `musl-1.2.4` 源码补证。

---

### Task 1: 固化输入/输出数据模型

**Files:**
- Create: `scripts/lib/models.py`
- Create: `tests/test_models.py`
- Create: `tests/fixtures/glibc_api_sample.csv`
- Create: `tests/fixtures/musl_files_sample.csv`

**Step 1: Write the failing test**

```python
import unittest

from scripts.lib.models import load_glibc_symbols, load_musl_files


class ModelTests(unittest.TestCase):
    def test_load_glibc_symbols_marks_internal_symbols(self):
        rows = load_glibc_symbols("tests/fixtures/glibc_api_sample.csv")
        self.assertEqual(rows[0].symbol, "_dl_allocate_tls")
        self.assertEqual(rows[0].symbol_kind, "internal")

    def test_load_musl_files_requires_only_filename_column(self):
        rows = load_musl_files("tests/fixtures/musl_files_sample.csv")
        self.assertEqual(rows[0].path, "include/pthread.h")
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing function errors

**Step 3: Write minimal implementation**

```python
from dataclasses import dataclass


@dataclass
class GlibcSymbolRow:
    symbol: str
    symbol_kind: str
```

实现 `load_glibc_symbols()`、`load_musl_files()`，并统一输出后续脚本可复用的数据结构。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_models.py tests/fixtures/glibc_api_sample.csv tests/fixtures/musl_files_sample.csv scripts/lib/models.py
git commit -m "test(models): 固化 glibc 与 musl 输入模型"
```

### Task 2: 实现 glibc manual / POSIX 官方规范定位器

**Files:**
- Create: `scripts/find_linux_man_pages.py`
- Create: `tests/test_find_linux_man_pages.py`
- Create: `tests/fixtures/glibc_manual_index.json`
- Create: `tests/fixtures/posix_index.json`

**Step 1: Write the failing test**

```python
import json
import unittest

from scripts.find_linux_man_pages import locate_symbol


class FindLinuxManPagesTests(unittest.TestCase):
    def test_locate_symbol_returns_linux_and_posix_refs(self):
        result = locate_symbol(
            symbol="pthread_detach",
            glibc_index_path="tests/fixtures/glibc_manual_index.json",
            posix_index_path="tests/fixtures/posix_index.json",
        )
        self.assertEqual(result["glibc_manual_status"], "found")
        self.assertIn("threads", result["glibc_manual_ref"])
        self.assertIn("pthread_detach", result["posix_ref"])

    def test_locate_symbol_marks_missing_linux_page(self):
        result = locate_symbol(
            symbol="__assert_fail",
            glibc_index_path="tests/fixtures/glibc_manual_index.json",
            posix_index_path="tests/fixtures/posix_index.json",
        )
        self.assertEqual(result["glibc_manual_status"], "missing")
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_find_linux_man_pages.py -v`
Expected: FAIL with missing module/function errors

**Step 3: Write minimal implementation**

```python
def locate_symbol(symbol: str, glibc_index_path: str, posix_index_path: str | None = None) -> dict:
    return {
        "symbol": symbol,
        "glibc_manual_status": "found",
        "glibc_manual_ref": f"/glibc/manual/threads.html#{symbol}",
        "posix_ref": f"https://pubs.opengroup.org/.../{symbol}.html",
    }
```

补齐 CLI：
- 输入 `glibc_API_analyse.csv`
- 输出 `out/manual_locator.json`
- `--glibc-manual-root` 指向本地 `glibc-2.34/manual/` 或其生成后的 HTML 索引
- `--posix-root` 或 `--posix-index` 指向 The Open Group 官方下载归档
- 若未提供 `glibc` / `POSIX` 官方语料位置，明确报错，而不是回落到当前 Darwin `manpath`

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_find_linux_man_pages.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_find_linux_man_pages.py tests/fixtures/linux_man_index.json scripts/find_linux_man_pages.py
git commit -m "feat(locator): 增加 Linux man 与 POSIX 规范定位器"
```

### Task 3: 实现手册语义比较器（glibc / POSIX）

**Files:**
- Create: `scripts/compare_api_manuals.py`
- Create: `tests/test_compare_api_manuals.py`
- Create: `tests/fixtures/manual_text/`

**Step 1: Write the failing test**

```python
import unittest

from scripts.compare_api_manuals import compare_manuals


class CompareApiManualsTests(unittest.TestCase):
    def test_compare_manuals_separates_functional_and_behavior_diffs(self):
        result = compare_manuals(
            linux_text="RETURN VALUE\nOn success, returns 0.\nERRORS\nEINVAL ...",
            posix_text="RETURN VALUE\nUpon successful completion, 0 shall be returned.",
            symbol="pthread_detach",
        )
        self.assertIn("behavior", result)
        self.assertIn("functional", result)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_compare_api_manuals.py -v`
Expected: FAIL with missing module/function errors

**Step 3: Write minimal implementation**

```python
def compare_manuals(symbol: str, glibc_text: str, posix_text: str, musl_text: str | None = None) -> dict:
    return {
        "symbol": symbol,
        "functional": {"posix_status": "standard"},
        "behavior": [{"type": "return_or_errno", "summary": "待比较"}],
    }
```

实现最小可用规则：
- 从 `RETURN VALUE`、`ERRORS`、`STANDARDS`、`NOTES` 提取段落
- 明确区分 `missing / extension-only / standard / unspecified`
- 对 `undefined / unspecified / implementation-defined` 的条目打标，交给下一阶段 musl 源码补证
- 产出 `out/manual_diff.json`

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_compare_api_manuals.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_compare_api_manuals.py tests/fixtures/manual_text scripts/compare_api_manuals.py
git commit -m "feat(compare): 增加手册功能差异与行为差异比较器"
```

### Task 4: 实现 musl 源码 / repo diff 与行为风险映射器

**Files:**
- Create: `scripts/analyze_repo_behavior_risk.py`
- Create: `tests/test_analyze_repo_behavior_risk.py`
- Create: `tests/fixtures/git_diff_sample.patch`

**Step 1: Write the failing test**

```python
import unittest

from scripts.analyze_repo_behavior_risk import classify_patch_risk


class AnalyzeRepoBehaviorRiskTests(unittest.TestCase):
    def test_classify_patch_risk_flags_return_value_change(self):
        result = classify_patch_risk(
            symbol="pthread_detach",
            patch_text="- return 0;\n+ return EINVAL;",
        )
        self.assertEqual(result["risk_level"], "high")
        self.assertIn("return value", result["reason"])
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_analyze_repo_behavior_risk.py -v`
Expected: FAIL with missing module/function errors

**Step 3: Write minimal implementation**

```python
def classify_patch_risk(symbol: str, patch_text: str) -> dict:
    return {
        "symbol": symbol,
        "risk_level": "high",
        "reason": "return value changed",
    }
```

补齐 CLI：
- 输入 `musl_file_modify_analyse.csv` + `--repo-path` + `--base-ref` + `--head-ref`
- 支持 `--musl-src`，把变更文件映射到真实接口实现与头文件
- 调用只读 `git diff --unified=0`
- 输出 `out/repo_behavior_risk.json`
- 若未提供 repo/ref，则只输出 `needs_repo_context=true`，不伪造结论
- 对于手册无结论但源码可确认的接口，允许输出 `source-confirmed` 级别证据

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_analyze_repo_behavior_risk.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_analyze_repo_behavior_risk.py tests/fixtures/git_diff_sample.patch scripts/analyze_repo_behavior_risk.py
git commit -m "feat(diff): 增加仓库变更到行为风险的映射器"
```

### Task 5: 生成 quick report

**Files:**
- Create: `scripts/generate_quick_report.py`
- Create: `tests/test_generate_quick_report.py`
- Create: `out/.gitkeep`

**Step 1: Write the failing test**

```python
import unittest

from scripts.generate_quick_report import render_report


class GenerateQuickReportTests(unittest.TestCase):
    def test_render_report_contains_functional_and_behavior_sections(self):
        report = render_report(
            manual_diff=[{"symbol": "pthread_detach", "behavior": [{"summary": "EINVAL risk"}]}],
            repo_risk=[{"symbol": "pthread_detach", "risk_level": "high"}],
        )
        self.assertIn("功能差异", report)
        self.assertIn("行为差异", report)
        self.assertIn("pthread_detach", report)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_generate_quick_report.py -v`
Expected: FAIL with missing module/function errors

**Step 3: Write minimal implementation**

```python
def render_report(manual_diff: list, repo_risk: list) -> str:
    return "# Quick Report\n\n## 功能差异\n\n## 行为差异\n"
```

CLI 输出：
- `out/quick_report.md`
- `out/manual_locator.json`
- `out/manual_diff.json`
- `out/repo_behavior_risk.json`

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_generate_quick_report.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_generate_quick_report.py scripts/generate_quick_report.py out/.gitkeep
git commit -m "feat(report): 生成 glibc 到 musl 迁移快速报告"
```

### Task 6: 端到端验证

**Files:**
- Modify: `tests/fixtures/glibc_api_sample.csv`
- Modify: `tests/fixtures/musl_files_sample.csv`
- Create: `tests/test_end_to_end_pipeline.py`

**Step 1: Write the failing test**

```python
import pathlib
import subprocess
import unittest


class EndToEndPipelineTests(unittest.TestCase):
    def test_pipeline_generates_quick_report(self):
        result = subprocess.run(
            [
                "python3",
                "scripts/generate_quick_report.py",
                "--manual-diff",
                "out/manual_diff.json",
                "--repo-risk",
                "out/repo_behavior_risk.json",
                "--output",
                "out/quick_report.md",
            ],
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(pathlib.Path("out/quick_report.md").exists())
```

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_end_to_end_pipeline.py -v`
Expected: FAIL because pipeline is incomplete

**Step 3: Write minimal implementation**

补齐脚本参数校验、输出目录创建、错误消息和 JSON 互操作，保证在缺少 repo/ref 时也能输出“仅手册视角”的 quick report。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_end_to_end_pipeline.py tests/fixtures/glibc_api_sample.csv tests/fixtures/musl_files_sample.csv
git commit -m "test(pipeline): 验证手册定位到快速报告的端到端流程"
```

