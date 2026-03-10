#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_PYTHON=1
INSTALL_CLI=1

usage() {
  cat <<'EOF'
用法:
  scripts/install_claude_code_sdk.sh [--python-bin <python>] [--skip-python] [--skip-cli]

说明:
  - 安装或升级 Python 版 Claude Code SDK
  - 安装或升级 Claude Code CLI
  - 默认使用当前 python3；若已在 virtualenv 中，则安装到该环境，否则安装到 user site
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --skip-python)
      INSTALL_PYTHON=0
      shift
      ;;
    --skip-cli)
      INSTALL_CLI=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 Python: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "未找到 node，请先安装 Node.js 18+。" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm，请先安装 npm。" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10+ 才能安装 Claude Code SDK")
PY

node - <<'NODE'
const major = Number(process.versions.node.split('.')[0]);
if (major < 18) {
  console.error('需要 Node.js 18+ 才能安装 Claude Code CLI');
  process.exit(1);
}
NODE

cd "$ROOT_DIR"

echo "项目目录: $ROOT_DIR"
echo "Python: $PYTHON_BIN"

after_python_check() {
  "$PYTHON_BIN" - <<'PY'
import importlib
module = importlib.import_module('claude_code_sdk')
print(f'Python SDK 已可导入: {module.__name__}')
PY
}

if [[ "$INSTALL_PYTHON" -eq 1 ]]; then
  echo "安装/升级 Python SDK..."
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install --upgrade claude-code-sdk
  else
    "$PYTHON_BIN" -m pip install --user --upgrade pip
    "$PYTHON_BIN" -m pip install --user --upgrade claude-code-sdk
  fi
  after_python_check
else
  echo "跳过 Python SDK 安装"
fi

if [[ "$INSTALL_CLI" -eq 1 ]]; then
  echo "安装/升级 Claude Code CLI..."
  npm install -g @anthropic-ai/claude-code
  claude --version
else
  echo "跳过 Claude Code CLI 安装"
fi

cat <<'EOF'

安装完成。常用下一步：
1. 确认 `claude --version` 正常输出
2. 如需账号登录，执行 `claude login`
3. 运行分析脚本：
   python3 scripts/analyze_musl_changes_with_claude.py --repo-root <源码仓路径>

说明：
- 当前分析脚本默认打印进度；如需关闭可加 `--quiet`
- 如需更详细日志可加 `--verbose`
EOF
