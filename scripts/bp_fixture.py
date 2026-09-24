"""테스트·selftest 공용 픽스처 — 임시 호스트 레포와 가짜 side_cmd. 운영 코드가 아니다.

bp_profile·bp_regress 의 --selftest(설치처, 의존 0)와 tests/(개발, pytest)가 같이 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_DEFAULTS = {
    "schema": 1,
    "regress": {
        "side_cmd": ["bin/side.sh"],
        "ran_fully": "^DONE ",
        "not_fully": "PARTIAL",
        "tree_marker": "tests/marker",
    },
}

# 가짜 러너. <트리>/failures.txt 를 이름 파일로 옮기고 완료 문구를 낸다.
# <트리>/mode 로 비정상 동작을 흉내 낸다. 받은 argv 를 로그 첫 줄에 남긴다.
FAKE_SIDE = """#!/bin/sh
echo "argv: $#|$1|$2"
tree=$1; names=$2
mode=$(cat "$tree/mode" 2>/dev/null || true)
case "$mode" in
  partial) echo "PARTIAL run" ;;
  nonames) echo "DONE 0 failed"; exit 0 ;;
  commit) git -c user.name=t -c user.email=t@t -c commit.gpgsign=false -C "$tree" commit -q --allow-empty -m moved ;;
esac
cp "$tree/failures.txt" "$names"
echo "DONE $(wc -l < "$names" | tr -d ' ') failed"
exit 1
"""


def write_profile(root, overrides=None) -> None:
    """overrides: {"schema": 2} · {"regress.not_fully": "x"} · 값이 None 이면 그 키를 뺀다."""
    data = json.loads(json.dumps(PROFILE_DEFAULTS))
    for key, value in (overrides or {}).items():
        if key.startswith("regress."):
            parent, name = data["regress"], key.split(".", 1)[1]
        else:
            parent, name = data, key
        if value is None:
            parent.pop(name, None)
        else:
            parent[name] = value
    path = Path(root) / ".claude" / "bugfix-pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_root(tmp, overrides=None) -> Path:
    """git 없는 호출 루트 — 가짜 래퍼·표지 파일·프로파일."""
    root = Path(tmp).resolve() / "host"
    (root / "bin").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "tests" / "marker").write_text("")
    side = root / "bin" / "side.sh"
    side.write_text(FAKE_SIDE)
    side.chmod(0o755)
    write_profile(root, overrides)
    return root
