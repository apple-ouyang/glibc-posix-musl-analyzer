# rtos 项目约定

## 语料与主流程

- `glibc` 接口分析以 `glibc/manual` 为主证据，路径示例：`glibc/glibc-2.34/manual/`
- `POSIX` 规范分析以 Open Group 官方 Issue 8 本地归档为主证据，路径示例：`out/posix/issue8/extracted/susv5-html/`
- `musl` 文件分析不再默认依赖 RPM 解压目录对比，而是假设在**直接源码仓**里运行，文件路径相对于源码仓根目录

## CSV 约定

### `glibc_API_analyse.csv`

- 继续使用当前中文表头
- `glibc手册覆盖情况` 建议使用：`有详细说明` / `有专门位置` / `只在正文提到` / `手册未找到`

### `musl_file_modify_analyse.csv`

- 当前主键是 `文件路径`
- 默认表头：
  - `文件路径`
  - `文件分类`
  - `作用范围`
  - `当前是否存在`
  - `变更来源`
  - `Backport提交数`
  - `Huawei提交数`
  - `未归类提交数`
  - `修改类型`
  - `修改内容摘要`
  - `关联接口`
  - `变更影响结论`
  - `风险等级`
  - `分析状态`
  - `备注`

## musl 分析脚本约定

- 脚本：`scripts/analyze_musl_changes_with_claude.py`
- 运行方式：在目标源码仓上执行，或显式传入 `--repo-root`
- 提交归因规则：
  - 标题前缀 `[Backport]` 归为社区回合提交
  - 标题前缀 `[Huawei]` 归为自研提交
  - 其它标题归为未归类提交
- 默认启用 `--exclude-oldest-commit`：按当前规则，将文件历史中的最早提交视为导入/基线提交并排除
- 如果后续发现某些文件是中途新增、不能把最早提交当作基线，需要显式关闭该参数或单独复核

## 输出与验证

- 默认输出目录：`out/musl/`
- 先跑小样本，再扩大并发
- 当前默认参数：
  - `timeout=120s`
  - `retries=2`
  - `concurrency=3`
  - `max_commits_per_file=5`
  - `max_diff_lines_per_commit=200`
