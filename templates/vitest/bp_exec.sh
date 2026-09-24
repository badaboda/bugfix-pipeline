#!/bin/sh
# bp_exec.sh <트리> -- <명령…> — 그 트리에서 명령 하나. cwd 는 호출 루트(계약).
# 명령을 «돌리지 못하면» 125 — 계약에서 125 는 「probe 가 돌지 못했다」(ENV)다.
#
# 사본에는 git 이 추적하지 않는 node_modules 가 없다 — 호출 루트의 것을 사본에 링크한다(사본은 폐기된다).
# 🔴 워크스페이스 레포(npm/yarn workspaces · pnpm)에서는 루트 node_modules 안의 워크스페이스 링크가 «루트»
#    패키지를 가리켜, 사본이 루트 코드를 잰다(최종 리뷰 실측: 거짓 초록). 이 템플릿은 그 경우를 거부한다 —
#    사본에 직접 설치하는 exec 를 쓴다.
tree=$1; shift
[ "$1" = "--" ] || { echo "사용법: bp_exec.sh <트리> -- <명령…>" >&2; exit 125; }
shift
[ -d "$tree" ] || { echo "bp_exec: 트리가 없다 — $tree" >&2; exit 125; }
root=$(pwd)
if [ ! -e "$tree/node_modules" ] && [ -d "$root/node_modules" ]; then
  if [ -f "$tree/pnpm-workspace.yaml" ] || grep -q '"workspaces"' "$tree/package.json" 2>/dev/null; then
    echo "bp_exec: 워크스페이스 레포 — 루트 node_modules 를 빌리면 사본이 루트 패키지를 잰다. 사본에 설치하는 exec 를 쓴다" >&2
    exit 125
  fi
  ln -s "$root/node_modules" "$tree/node_modules" || exit 125
fi
cd "$tree" || exit 125
command -v "$1" >/dev/null 2>&1 || { echo "bp_exec: 명령이 없다 — $1" >&2; exit 125; }
exec "$@"
