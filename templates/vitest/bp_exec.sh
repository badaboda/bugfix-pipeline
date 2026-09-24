#!/bin/sh
# bp_exec.sh <트리> -- <명령…> — 그 트리에서 명령 하나. cwd 는 호출 루트(계약).
# 사본에는 git 이 추적하지 않는 node_modules 가 없다 — 호출 루트의 것을 사본에 링크한다(사본은 폐기된다).
tree=$1; shift
[ "$1" = "--" ] || { echo "사용법: bp_exec.sh <트리> -- <명령…>" >&2; exit 125; }
shift
[ -d "$tree" ] || { echo "bp_exec: 트리가 없다 — $tree" >&2; exit 125; }
root=$(pwd)
if [ ! -e "$tree/node_modules" ] && [ -d "$root/node_modules" ]; then
  ln -s "$root/node_modules" "$tree/node_modules" || exit 125
fi
cd "$tree" || exit 125
exec "$@"
