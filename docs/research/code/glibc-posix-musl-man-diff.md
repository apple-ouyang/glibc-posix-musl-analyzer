# glibc / POSIX / musl 手册差异分析代码调研

> 状态: active
> 创建: 2026-03-10
> 更新: 2026-03-10
> 适用范围: `glibc_API_analyse.csv`、`musl_file_modify_analyse.csv`、基于 Linux man / POSIX 规范的接口差异分析流水线

**调研目标：** 为“从 glibc 切换到 musl”的快速报告建立一条可追溯的分析链：先定位手册，再判定功能差异与行为差异，最后结合代码修改评估风险。
**一句话结论：** 当前仓库已经具备本地 `glibc/manual/`、本地 `musl` 源码和可缓存的 Open Group 官方 POSIX 归档；后续主流程可收窄为“glibc 官方 manual + 官方 POSIX”两套主语料，只有在 POSIX 留白或 glibc manual 缺项时再回看 musl 源码。
**建议下一步：** `/writing-plans`

## TL;DR

- 当前机器是 `Darwin arm64`，`manpath` 指向的是 macOS 手册树，不能直接拿本机 `man` 结果当 Linux 侧证据。
- 目前没有找到可直接复用的 `myclaw` man 树；本地能定位到的 `myclaw` 目录是 Caddy 配置目录，不是手册目录。
- `glibc_API_analyse.csv` 的表头把“手册定位、结论、分析产物路径”混在了一张表里，缺少“接口分类、标准覆盖状态、行为差异类型、证据级别”等关键字段。
- `musl_file_modify_analyse.csv` 只有文件路径，无法回答“改了什么内容”；至少还需要目标仓库路径、`base/head` revision、diff hunk、符号映射，才有资格判断行为变化。
- 为了做“快速报告”，应该拆成三段流水线：`man locator` → `manual comparator` → `repo diff impact analyzer`，所有中间结果先输出 JSON，再汇总 Markdown 报告。

## 证据源策略（收窄后）

- `glibc` 侧主语料使用与你本地源码版本匹配的 `glibc-2.34/manual/`；这是 glibc 官方维护的说明面，适合作为 glibc 侧主证据。
- `POSIX` 侧主语料使用 The Open Group 官方 `Issue 8 / POSIX.1-2024` 下载归档；我已将官方 HTML 归档下载到本地 `out/posix/issue8/extracted/susv5-html/`。
- `musl` 不应被等同于 `POSIX` 手册。musl 官网 manual 明确说明它是草稿/WIP，接口目标是遵循 ISO C 和 POSIX；因此本轮可以把 POSIX 作为 musl 的“标准基线”，但不能把 POSIX 直接当成 musl 的实现文档。
- 当 POSIX 对某行为标为 `undefined`、`unspecified`、`implementation-defined`，或 glibc manual 根本没有对应条目时，再回落到 `musl-1.2.4` 源码做补证。
- 对于 GNU 扩展、glibc 内部符号和 Linux 特定接口，若 POSIX 无页面，应标记为 `non-standard` 或 `not-in-posix`，而不是标记为 musl “缺失”。

## 系统如何工作

这次任务本质上不是“做一个大而全的 diff”，而是做一条带证据的筛选流水线。

第一段输入是接口清单。`glibc_API_analyse.csv` 现在只提供了符号名，其中已经混入内部符号和 GNU/Linux 扩展符号。这意味着在进入对比前，必须先给每个符号打上分类：`POSIX 标准接口 / GNU 扩展 / Linux 特定 / glibc 内部符号 / 暂无法归类`。如果不先做这一步，后面很容易把“POSIX 没有定义”误报成“musl 缺失实现”。

第二段输入是手册语料。现在这部分可以收窄：glibc 侧直接使用本地 `glibc-2.34/manual/`，POSIX 侧使用 Open Group 官方下载归档。这样可以避免宿主机 `manpath`、Ubuntu 打包页和节号映射带来的噪音。但它的代价是：不是每个导出符号都会在 glibc manual 中有一条一对一条目，所以定位器必须允许输出 `no_glibc_manual_entry`，并在必要时回源码补证。

第三段输入是代码修改集合。`musl_file_modify_analyse.csv` 当前只有文件名，适合做“需要进一步查看哪些区域”的索引，但不够支撑行为分析。行为分析真正需要的是：这些文件相对哪个基线改了什么、涉及哪些导出符号或内部实现、这些改动能否映射到 man 的 `RETURN VALUE` / `ERRORS` / `NOTES` / `STANDARDS` 等段落。如果只有文件路径，我们最多能做“潜在高风险区域预警”，不能下“行为已变更”的结论。

## 关键设计决策

### 1. 手册来源不能依赖当前宿主机 `manpath`

当前 `manpath` 指向的是 macOS 路径，`man -w pthread_detach` 命中的是 Xcode Command Line Tools SDK 内的手册，`man -w accept4` 则直接返回无手册页。这个环境足以说明“本机能查手册”，但不足以说明“本机查到的是 Linux 手册”。

因此，后续脚本必须显式接受 Linux 语料位置，例如 `--linux-man-root`，并在启动时验证它不是当前 Darwin 的 man 树。对于 POSIX 侧，字段名称也不应该继续叫“POSIX man 所在位置”，因为 POSIX 更准确的是“规范位置 / 章节 URL / 本地缓存路径”。

### 2. 要把“功能差异”和“行为差异”分开存储

你当前要识别的是两类差异：

- 功能差异：接口是否存在、是否属于 POSIX、musl 是否实现、是否需要 feature test macro。
- 行为差异：返回值、`errno`、线程语义、取消点、边界输入、历史兼容行为。

这两类差异的证据来源不同，不能塞到一个模糊的“man 对比结论”里。更稳的做法是结构化字段：`functional_status`、`behavior_delta_type`、`behavior_delta_summary`、`confidence`、`evidence_path`。这样像 `pthread_detach` 这类“接口存在，但返回值行为可能不同”的情况，才不会被淹没在一个笼统结论里。

### 3. “快速报告”不等于“全量穷举”

如果目标是尽快产出第一版报告，最合适的策略不是一次性穷举所有 glibc 符号，而是优先聚焦“与迁移改动最相关的接口集合”。

理想路径是：先从目标仓库 diff 提取被改动的函数、宏或调用点，再回溯到接口级差异；若目标仓库暂时没给到，只能退一步对 `glibc_API_analyse.csv` 里的符号做批量定位，并把结论标成“手册差异视角，不代表代码路径已触发”。

## 必须守住的约束

- 不要把 `musl` 官网 manual 或 Ubuntu 的 `manpages-posix` 误当成 POSIX 规范原文；POSIX 基线应来自 The Open Group 官方发布物。
- 不要假设 `glibc/manual/` 能覆盖所有导出接口；缺页时必须显式标记，而不是偷偷回落到其他语料。
- 不要把 “POSIX 未定义” 混同于 “musl 缺失实现”。很多符号本来就不是 POSIX 公共接口。
- 不要把当前 macOS `man` 的定位结果写回 Linux 对比表，否则证据面从一开始就是错的。
- 没有 `base/head` revision 的前提下，`musl_file_modify_analyse.csv` 只能做区域索引，不能做真实 diff 结论。
- 行为差异结论必须带证据段落，至少要能追到 `RETURN VALUE`、`ERRORS`、`STANDARDS`、`NOTES` 中的某一类说明。
- 头文件、`arch/*`、`bits/*` 变更往往只说明 ABI、宏定义或平台细节可能变化，只有映射到具体接口或调用点时，才能提升到行为结论。

## 风险与未决问题

- 若后续发现 `glibc/manual/` 对某批接口覆盖率过低，再考虑把上游 `Linux man-pages` 作为第三语料补进来；当前不默认引入。
- `myclaw` 手册路径目前未找到；如果你有特定的 Linux man 镜像目录，需要在执行前明确给出。
- 当前仓库里没有 `musl` 源码 checkout，也没有你的业务仓库路径；后续“看一下它们都修改了什么内容”这一步必须依赖真实仓库和 revision。
- `glibc_API_analyse.csv` 内含内部符号（如 `_dl_allocate_tls`、`__assert_fail`、`__clock_gettime64`），这些符号的分析策略应与 POSIX 公共接口分开。
- 某些行为差异不会出现在 man 文本里，而是体现在源码约束、历史补丁或实现细节中；这类接口需要降级为“手册未覆盖，需源码复核”。

## 建议的下一步

建议进入 `/writing-plans`，把实现拆成 4 个最小可交付阶段：

1. 规范化 CSV 表头与中间 JSON 结构。
2. 实现 Linux man / POSIX 规范定位脚本。
3. 实现基于手册段落的功能差异 / 行为差异比较器。
4. 在拿到目标仓库路径与 revision 后，追加代码 diff 影响分析并生成 quick report。

如果你希望第一版报告更快落地，建议先只做“手册定位 + 手册差异”两步，把 repo diff 分析放到第二批。

---

## 附录 A：证据索引

- `/Users/admin/code/rtos/glibc_API_analyse.csv:1` — 当前表头只有“位置 / 结论 / 路径”，缺少结构化差异字段。
- `/Users/admin/code/rtos/glibc_API_analyse.csv:2` — `_dl_allocate_tls` 属于内部符号示例，不能直接按 POSIX 公共接口处理。
- `/Users/admin/code/rtos/glibc_API_analyse.csv:15` — `__asprintf_chk` 属于内部/检查变体示例。
- `/Users/admin/code/rtos/glibc_API_analyse.csv:18` — `__assert_fail` 属于内部符号示例。
- `/Users/admin/code/rtos/glibc_API_analyse.csv:51` — `__clock_gettime64` 说明当前清单还包含 time64 相关内部/兼容符号。
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv:1` — 当前 CSV 只有 `文件名` 一列。
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv:2` — `arch/*` 变更示例，通常不能直接推出接口行为差异。
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv:18` — `arch/generic/bits/*` 变更示例，更偏 ABI / 宏定义层。
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv:26` — `crt/*` 变更示例，可能影响启动流程，不一定对应单个 POSIX 接口。
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv:31` — `include/*` 变更示例，更容易映射到公开接口。
- `Command: uname -a` — 当前系统为 `Darwin ... arm64`。
- `Command: manpath` — 当前 `manpath` 指向 macOS 手册树，而非 Linux man 树。
- `Command: man -w pthread_detach` — 命中 `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/share/man/man3/pthread_detach.3`。
- `Command: man -w accept4` — 当前宿主机返回 `No manual entry for accept4`。
- `Command: man -w basename` — 当前宿主机优先命中 `/usr/share/man/man1/basename.1`，不是 C API 手册页。

## 附录 B：补充观察

- `glibc_API_analyse.csv` 当前样本共 50 个符号，其中至少 6 个是明显的内部符号或双下划线符号。
- `musl_file_modify_analyse.csv` 当前样本共 50 个文件，主要分布在 `arch/`、`include/`、`crt/`，说明后续需要区分“接口层改动”和“平台/ABI 层改动”。
- 本地找到的 `myclaw` 相关路径是 `/Users/admin/code/ads_public/openclaw-configs/caddy/myclaw`，其中只有 `Caddyfile`，没有 man 语料。

## 附录 C：调研范围

- `/Users/admin/code/rtos/glibc_API_analyse.csv`
- `/Users/admin/code/rtos/musl_file_modify_analyse.csv`
- `/Users/admin/.claude/skills/plan-dev/SKILL.md`
- `/Users/admin/.claude/skills/code-research/SKILL.md`
- `/Users/admin/.agents/skills/writing-plans/SKILL.md`
- `/Users/admin/.agents/skills/using-superpowers/SKILL.md`
