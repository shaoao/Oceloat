#!/bin/zsh
cd "$(dirname "$0")" || exit 1

# 优先用本机统一安装的 Python 3.13.12（不放在 WorkBuddy 目录里）
PY="$HOME/.local/share/python/3.13.12/bin/python3"
if [ -x "$PY" ]; then
  exec "$PY" main.py
fi

# 兜底：PATH 里任何带 PyQt6 的 Python 3.10+
for py in "$(command -v python3.13 2>/dev/null)" "$(command -v python3 2>/dev/null)"; do
  [ -n "$py" ] || continue
  [ -x "$py" ] || continue
  if "$py" -c 'import sys, PyQt6; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    exec "$py" main.py
  fi
done

print -u2 "[Ocelot] 没找到带 PyQt6 的 Python 3.10+。请先安装：python3 -m pip install PyQt6"
exit 1
