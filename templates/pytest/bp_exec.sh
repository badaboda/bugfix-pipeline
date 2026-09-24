#!/bin/sh
# bp_exec.sh <트리> -- <명령…> — 그 트리에서 명령 하나. cwd 는 호출 루트(계약).
# 명령을 «돌리지 못하면» 125 — 계약에서 125 는 「probe 가 돌지 못했다」(ENV)다. 1 이면 «재현됨»으로 읽힌다.
#
# 트리에 .venv 가 있으면 그것을 쓴다. 없으면(사본 — git 이 추적하지 않는 .venv 가 없다) 호출 루트의 것을
# 빌린다. 🔴 «트리에 없을 때만» 넣으면 루트 자신은 시스템 python 으로 돈다(실측 2026-09-25).
# 🔴 빌린 venv 의 editable 설치(uv sync 기본)는 «루트» 소스를 가리킨다 — 그대로면 사본이 루트 코드를 import
#    해서 기준선이 수정 후 코드를 잰다(최종 리뷰 실측: src 레이아웃, 거짓 초록). 사본 소스를 PYTHONPATH 앞에
#    둔다. PYTHONPATH 는 .pth 보다 앞선다. 비-editable 로 프로젝트를 설치한 venv 는 이것으로도 못 막는다.
tree=$1; shift
[ "$1" = "--" ] || { echo "사용법: bp_exec.sh <트리> -- <명령…>" >&2; exit 125; }
shift
[ -d "$tree" ] || { echo "bp_exec: 트리가 없다 — $tree" >&2; exit 125; }
root=$(pwd)
if [ -d "$tree/.venv" ]; then
  PATH="$tree/.venv/bin:$PATH"
elif [ -d "$root/.venv" ]; then
  PATH="$root/.venv/bin:$PATH"
  PYTHONPATH="$tree/src:$tree${PYTHONPATH:+:$PYTHONPATH}"; export PYTHONPATH
else
  echo "bp_exec: .venv 가 없다 — 트리에도 호출 루트에도 ($tree · $root)" >&2
  exit 125
fi
export PATH
cd "$tree" || exit 125
command -v "$1" >/dev/null 2>&1 || { echo "bp_exec: 명령이 없다 — $1" >&2; exit 125; }
exec "$@"
