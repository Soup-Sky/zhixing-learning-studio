#!/usr/bin/env bash
# macOS / Linux source launcher. Windows users can use 启动学习工作室.cmd or scripts/serve.py.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "需要 Python 3.11 或更高版本。" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -m venv .venv
fi

if ! .venv/bin/python -c 'import fastapi,uvicorn,httpx,sympy,pypdf,docx,multipart' 2>/dev/null; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
fi

if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "缺少前端构建产物，且未找到 Node.js 20+。请安装 Node.js 后重试，或使用 Release 中的 Windows 包。" >&2
    exit 1
  fi
  (cd frontend && npm ci && npm run build)
fi

exec .venv/bin/python scripts/serve.py "$@"
