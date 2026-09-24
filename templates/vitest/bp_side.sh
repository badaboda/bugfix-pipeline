#!/bin/sh
# bp_side.sh <트리> <이름 출력> — 그 트리에서 전체 스위트를 돌리고 실패 id 를 쓴다.
# 이름은 JSON 리포터에서 뽑는다(텍스트 출력은 버전마다 모양이 다르다). stdout 은 기본 리포터 — 로그다.
tree=$1; names=$2
here=$(cd "$(dirname "$0")" && pwd)
json="$names.json"
"$here/bp_exec.sh" "$tree" -- npx vitest run --reporter=default --reporter=json --outputFile.json="$json" 2>&1
status=$?
# 🔴 JSON 의 파일 이름은 절대경로다 — 그대로 쓰면 기준선 사본과 수정 후 트리의 경로가 달라
# 모든 실패가 «새 빨강»이 된다(실측 2026-09-25). 트리 기준 상대경로로 바꾼다.
python3 - "$json" "$names" "$tree" <<'PY'
import json, os, sys
src, dst, tree = sys.argv[1], sys.argv[2], os.path.realpath(sys.argv[3])
out = []
try:
    data = json.load(open(src))
except (OSError, ValueError):
    data = {"testResults": []}
for f in data.get("testResults", []):
    name = os.path.relpath(os.path.realpath(f.get("name", "")), tree)
    failed = [a for a in f.get("assertionResults", []) if a.get("status") == "failed"]
    for a in failed:
        out.append(f"{name} > {a.get('fullName')}")
    if f.get("status") == "failed" and not failed:
        out.append(name)  # 파일 수준 오류(import 실패 등)
open(dst, "w").write("".join(x + "\n" for x in out))
PY
rm -f "$json"
exit $status
