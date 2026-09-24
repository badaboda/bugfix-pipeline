#!/bin/sh
# bp_exec.sh <트리> -- <명령…> — 그 트리에서 명령 하나. cwd 는 호출 루트(계약).
# 트리에 .venv 가 있으면 그것을, 없으면(사본 — git 이 추적하지 않는 .venv 가 없다) 호출 루트의 것을
# PATH 앞에 둔다. 🔴 «트리에 없을 때만» 넣으면 루트 자신은 시스템 python 으로 돈다(실측 2026-09-25).
tree=$1; shift
[ "$1" = "--" ] || { echo "사용법: bp_exec.sh <트리> -- <명령…>" >&2; exit 125; }
shift
[ -d "$tree" ] || { echo "bp_exec: 트리가 없다 — $tree" >&2; exit 125; }
root=$(pwd)
if [ -d "$tree/.venv" ]; then
  PATH="$tree/.venv/bin:$PATH"; export PATH
elif [ -d "$root/.venv" ]; then
  PATH="$root/.venv/bin:$PATH"; export PATH
fi
cd "$tree" || exit 125
exec "$@"
