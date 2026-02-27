# Claude Code 内部架构 — PPT 素材

## 一、架构分层总览

参照鸿蒙架构图风格，分为 **4 层**，从上到下：

```
┌──────────────────────────────────────────────────────────────────────────┐
│  应用场景层  │ 代码移植 │ 告警修复 │ Bug修复 │ 需求开发 │ CI运营 │ 版本发布 │  ← 橙色
├──────────────────────────────────────────────────────────────────────────┤
│  增强能力层  │       Skill (44个)        │         MCP (60+工具)         │  ← 绿色
├──────────────────────────────────────────────────────────────────────────┤
│  平台工具层  │              Claude Code (CLI / IDE 插件)                 │  ← 蓝色
├──────────────────────────────────────────────────────────────────────────┤
│  基础模型层  │      GM 4.5-Air (现有)      │      GM 4.7 (规划中)        │  ← 紫色
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 二、各层详细内容

### 第 1 层：基础模型层（紫色底）

| 模型 | 状态 | 说明 |
|------|------|------|
| GM 4.5-Air | ✅ 已部署 | 当前唯一可用模型 |
| GM 4.7 | 🔄 规划中 | 中软正在部署 |

### 第 2 层：平台工具层（蓝色底）

- **Claude Code**：Anthropic 官方 CLI / IDE 插件
- 作为 Skill 和 MCP 的运行载体

### 第 3 层：增强能力层（绿色底）— 分左右两大块

#### 左侧：Skill（共 44 个）

**开源/官方 Skill（23 个）** — 来源：bys_skills/skills

| 子类 | Skill 名称 | 下载量 |
|------|-----------|--------|
| 开源 | Superpower (find-skills) | 68 |
| 官方 | skill-creator | 67 |
| 官方 | brainstorming | 66 |
| 官方 | frontend-design | 65 |
| 官方 | writing-skills | 65 |
| 官方 | doc-coauthoring, systematic-debugging, xlsx, requesting-code-review, writing-plans, verification-before-completion, test-driven-development, using-superpowers, docx, pdf, pptx, receiving-code-review, mcp-builder, executing-plans, subagent-driven-development, dispatching-parallel-agents, finishing-a-development-branch, using-git-worktrees | 64 |

**自研开发 Skill（8 个）** — 来源：bys_skills/develop_skills

| Skill | 下载量 | 说明 |
|-------|--------|------|
| All-commit | 18 | 全版本代码提交 |
| swarm | 9 | 多 Agent 协作 |
| All-alert-fix | 8 | 全版本告警修复 |
| All-indent-c-formatter | 7 | C 代码格式化 |
| ALL-review-mr | 7 | MR 代码检视 |
| Lite-instruct-one-bit-flip | 7 | Lite 版本位翻转指令 |
| code-research | 6 | 代码调研 |
| pb-download-code | 2 | 代码下载 |

**自研测试 Skill（11 个）** — 来源：bys_skills/test_skills

| Skill | 下载量 | 说明 |
|-------|--------|------|
| RTOS-testcode-commit | 16 | RTOS 测试代码提交 |
| hm-test-manual | 15 | 鸿蒙测试手册 |
| testcode-api-utils | 13 | 测试 API 工具集 |
| testcode-template | 8 | 测试代码模板 |
| Lite-libck-test | 4 | Lite 版本 libck 测试 |
| Lite-embed-comments | 4 | Lite 嵌入式注释 |
| Lite-testcode-template | 4 | Lite 测试模板 |
| Lite-testcode-analysis | 4 | Lite 测试分析 |
| Lite-c-testcase-design | 4 | Lite C 用例设计 |
| Lite-ck-analyze-ci-logs | 4 | Lite CI 日志分析 |
| Lite-test-template | 0 | Lite 测试模板 |

**自研工程 Skill（2 个）** — 来源：bys_skills/engineering_skills

| Skill | 下载量 | 说明 |
|-------|--------|------|
| ci-pipeline-generator | 5 | CI 流水线生成 |
| all-build | 2 | 全版本构建 |

#### 右侧：MCP（共 60+ 工具，按业务域分 10 组）

**① DTS 缺陷管理**（对接 DTS 缺陷跟踪系统）

| 工具 | 能力 |
|------|------|
| dts_query | 批量查询 DTS 单信息 |
| dts_has_mr | 检查 DTS 是否有关联代码合入 |
| dts_query_vulninfo | 获取 DTS 对应的 CVE 漏洞信息 |
| dts_query_by_time | 按时间段查询版本 DTS 单 |
| dts_dev_to_plan | DTS 单从开发分析走到修补计划阶段 |

**② CVE 漏洞管理**（对接 Hulk 漏洞平台）

| 工具 | 能力 |
|------|------|
| is_cve_affected_version | 判断版本是否受 CVE 影响 |
| is_cve_need_fix | 检查 CVE 是否需要修复 |
| is_hulk_provide_patch | 检查 Hulk 是否已提供补丁 |
| is_patch_merged | 检查补丁是否已合入代码分支 |
| get_hulk_owner_by | 通过 CVE ID 获取 Hulk 责任人 |
| version_dts_query | 查询版本所有 DTS 单号 |
| version_dts_query_hulk_no_patch | 查询未提供补丁的清单 |
| version_dts_check_patch_merge | 检查补丁未合入的清单 |
| update_cve_info_by_file | 文件批量更新 CVE 数据 |

**③ CI/CD 运营**（对接 CI 运营看板）

| 工具 | 能力 |
|------|------|
| get_ci_details_api | 获取 CI 执行结果（编译/裁剪/部署/测试） |
| get_testcase_result | 获取测试套用例执行结果 |
| repair_failed_job | 批量触发失败测试套修复 |
| repair_failed_job_in_version | 按版本触发失败修复 |
| get_rtos_version_id_by | 获取 RTOS 版本 ID |
| get_rtos_test_revision | 获取版本 testRevision |
| ci_cd_status_check | CI/CD 评估状态检查 |

**④ 代码切片数据库**（对接 Config 宏控系统）

| 工具 | 能力 |
|------|------|
| query_config_codebase | 输入 Config 名 → 返回代码文件路径 + 行号 + 代码内容 |

**⑤ 项目管理**（对接项目管理平台）

| 工具 | 能力 |
|------|------|
| query_project_pbi_id | 查询项目 PBI ID |
| query_project_metrics_data | 查询项目指标数据 |
| query_requirement_details | 读取项目需求列表 |
| query_dts_details | 查询 DTS 详情（分页） |
| query_iteration_by_version_date | 查询迭代版本信息 |
| summary_code_merge_status | 汇总代码合入记录统计 |
| list_quality_tasks_status | 列出版本质量任务状态 |
| query_all_build_metrics | 查询流水线健康度指标 |

**⑥ 版本管理**（对接版本发布系统）

| 工具 | 能力 |
|------|------|
| get_bversion_config | 获取版本构建环境、源码信息 |
| get_bversion_info | 获取版本信息（含验签状态） |
| query_product_list | 获取版本发布产品列表 |
| get_version_stage | 获取版本阶段信息 |
| query_release_task_status | 查询归档任务状态 |

**⑦ 转测评估**（对接转测电子流）

| 工具 | 能力 |
|------|------|
| transfer_evaluation | 提交转测 |
| get_evaluation_status | 获取转测评估详情 |
| create_test_ticket | 创建转测电子流 |

**⑧ Jenkins 流水线**（对接 Jenkins CI）

| 工具 | 能力 |
|------|------|
| jenkins_trigger_job | 触发构建任务 |
| jenkins_get_job_status | 查询任务状态 |
| jenkins_get_build_log | 获取构建日志（分页） |
| jenkins_cancel_build | 取消运行中的构建 |
| jenkins_list_build_artifacts | 列出/下载构建产物 |

**⑨ 数据库查询**（对接内部 PgSQL/MySQL）

| 工具 | 能力 |
|------|------|
| list_tables / query_table_info | 列出表和 DDL |
| run_sql | 执行 SQL 查询 |

**⑩ 知识库 & 通用工具**

| 工具 | 能力 |
|------|------|
| record_solution / search_solution | Yocto 问题解决方案知识库（Dify） |
| send_message_to_user | 发送消息通知用户 |
| set_wakeup | 设置定时唤醒 |
| beplist / bep_task | BEP 任务管理 |

### 第 4 层：应用场景层（橙色底）

| 场景 | 依赖的 Skill / MCP | 说明 |
|------|-------------------|------|
| 代码移植 | 代码切片数据库 MCP | V2 Linux → V3 鸿蒙，精准定位 Config 对应代码段 |
| 告警修复 | All-alert-fix Skill + DTS MCP | 批量屏蔽 + 代码修复，~80% 告警可自动屏蔽 |
| Bug 修复 | DTS MCP + code-research Skill | 查询问题单 → 定位代码 → 修复 |
| 需求开发 | iDesigner MCP + 测试套 Skill | 读取特性文档 → 编码 → 检视 → 测试 |
| CI 运营 | CI/CD MCP + Jenkins MCP | CI 结果查看 → 失败修复 → 重新触发 |
| 版本发布 | 版本管理 MCP + 转测评估 MCP | 版本构建 → 转测评估 → 归档发布 |
| CVE 修复 | CVE 漏洞 MCP + DTS MCP | 漏洞影响分析 → 补丁合入检查 → 修复跟踪 |
| 代码检视 | ALL-review-mr Skill | MR 代码检视 + commit 规范检查 |

---

## 三、PPT 制作建议

### 页面 1：整体架构图（核心页，必做）

仿照鸿蒙架构图风格：

1. **布局**：4 条水平色带，从下到上依次为紫→蓝→绿→橙
2. **每层内部**：用白色/浅色圆角矩形小方框表示各组件
3. **配色方案**（参考鸿蒙风格）：
   - 基础模型层：`#7B68EE`（紫色）
   - 平台工具层：`#4A90D9`（蓝色）
   - 增强能力层：`#5CB85C`（绿色）
   - 应用场景层：`#F0AD4E`（橙色）
4. **增强能力层**用竖线分为左右两块：
   - 左侧 Skill：3 个小方框（开源/官方 23个 | 自研开发 8个 | 自研测试 11个 + 工程 2个）
   - 右侧 MCP：10 个小方框（每个业务域一个）
5. 每个小方框标注名称 + 工具数量，如 "DTS 缺陷管理 (5)"
6. 圆角矩形，每层左侧标注层名

### 页面 2：增强能力层展开（推荐）

将第 1 页的绿色层放大展开，分两列详细展示：

```
┌─── Skill (44个) ──────────────┬─── MCP (60+工具) ─────────────────┐
│                               │                                    │
│  ┌─ 开源/官方 (23) ─────┐    │  ┌─ DTS缺陷管理 ──┐ ┌─ CVE漏洞 ─┐│
│  │ Superpower            │    │  │ 查询/走单/关联  │ │ 影响分析   ││
│  │ brainstorming         │    │  └────────────────┘ │ 补丁跟踪   ││
│  │ TDD / code-review ... │    │                      └───────────┘│
│  └───────────────────────┘    │  ┌─ CI/CD运营 ───┐ ┌─ Jenkins ──┐│
│                               │  │ 结果查看       │ │ 触发/取消  ││
│  ┌─ 自研开发 (8) ───────┐    │  │ 失败修复       │ │ 日志/产物  ││
│  │ All-commit            │    │  └────────────────┘ └───────────┘│
│  │ All-alert-fix         │    │                                    │
│  │ ALL-review-mr         │    │  ┌─ 代码切片DB ──┐ ┌─ 项目管理 ─┐│
│  │ swarm (多Agent)       │    │  │ Config→代码    │ │ PBI/需求   ││
│  └───────────────────────┘    │  │ 精确到行号     │ │ 指标/追溯  ││
│                               │  └────────────────┘ └───────────┘│
│  ┌─ 自研测试 (11+2) ────┐    │                                    │
│  │ RTOS / V3 / Lite      │    │  ┌─ 版本管理 ───┐ ┌─ 转测评估 ─┐│
│  │ 测试模板/分析/CI日志  │    │  │ 构建/归档     │ │ 提交/评估  ││
│  └───────────────────────┘    │  └────────────────┘ └───────────┘│
└───────────────────────────────┴────────────────────────────────────┘
```

### 页面 3（可选）：代码切片数据库 MCP 详解

技术亮点页，展示 Config 宏控 → 代码映射 → 跨系统移植的流程：

```
需求 ──→ Config 宏 ──→ 代码文件:行号
  │         │              │
  │    一个需求对应      精确到文件
  │    多个 Config       和代码行
  │
  └── V2 Linux 代码 ──移植──→ V3 鸿蒙代码
         (源)                  (目标)
```

### 视觉要点

- 圆角矩形，不要直角（更现代）
- 小方框内文字精简到 2-4 个字 + 数量
- 层与层之间用细线或箭头表示调用关系
- 右上角可加 "现有 ✅ / 规划中 🔄" 图例
- 数据亮点用大字突出：**44 个 Skill**、**60+ MCP 工具**、**10 大业务域**
