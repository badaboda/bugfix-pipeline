#!/bin/sh
# bp_side.sh <트리> <이름 출력> — 그 트리에서 전체 스위트를 돌리고 실패·오류 id 를 쓴다.
# stdout 이 곧 로그다 — 프로파일의 ran_fully 가 여기서 요약 줄을 찾는다.
tree=$1; names=$2
here=$(cd "$(dirname "$0")" && pwd)
raw="$names.raw"
"$here/bp_exec.sh" "$tree" -- ${BP_PYTEST:-python3 -m pytest} -rfE -p no:cacheprovider --color=no > "$raw" 2>&1
status=$?
cat "$raw"
# FAILED 만 세면 fixture·setup 오류(ERROR)가 빠진다 — 그것도 «새 빨강»이다
grep -E '^(FAILED|ERROR) ' "$raw" | sed -E 's/^(FAILED|ERROR) //; s/ - .*//' > "$names"
rm -f "$raw"
exit $status
