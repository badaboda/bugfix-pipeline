"""테스트·selftest 공용 픽스처 — 임시 호스트 레포와 가짜 side_cmd. 운영 코드가 아니다.

bp_profile·bp_regress 의 --selftest(설치처, 의존 0)와 tests/(개발, pytest)가 같이 쓴다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROFILE_DEFAULTS = {
    "schema": 2,
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
  commit_other) git -c user.name=t -c user.email=t@t -c commit.gpgsign=false -C "$(cat "$tree/other")" commit -q --allow-empty -m moved ;;
esac
cp "$tree/failures.txt" "$names"
echo "DONE $(wc -l < "$names" | tr -d ' ') failed"
exit 1
"""


def write_profile(root, overrides=None) -> None:
    """overrides: {"schema": 2} · {"regress.not_fully": "x"} · 값이 None 이면 그 키를 뺀다."""
    data = json.loads(json.dumps(PROFILE_DEFAULTS))
    for key, value in (overrides or {}).items():
        if "." in key:
            section, name = key.split(".", 1)
            parent = data.setdefault(section, {})
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


def git(tree, *args) -> str:
    r = subprocess.run(
        ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def set_failures(tree, names) -> None:
    (Path(tree) / "failures.txt").write_text("".join(n + "\n" for n in names))


def set_mode(tree, mode) -> None:
    (Path(tree) / "mode").write_text(mode)


def make_host(tmp, base_failures=(), after_failures=(), overrides=None):
    """(호출 루트 = 수정 후 트리, 기준선 트리). 기준선은 커밋 A 의 워크트리, 수정 후는 A 위 커밋 B."""
    tmp = Path(tmp).resolve()
    root = make_root(tmp, overrides)
    set_failures(root, base_failures)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "A")
    base = tmp / "base"
    git(root, "worktree", "add", "-q", "--detach", str(base), "HEAD")
    set_failures(root, after_failures)
    git(root, "commit", "-q", "--allow-empty", "-am", "B")
    return root, base


CHECK_SH = """#!/bin/sh
# 불변식: value.txt 가 good 이고 broken 파일이 없다
[ "$(cat value.txt)" = good ] && [ ! -e broken ]
"""

REPRO_SH_TEXT = """#!/bin/sh
# repro.sh <트리> — 화면 대신 value.txt 를 보인다
cat "$1/value.txt"
"""


def make_gate_host(tmp, overrides=None):
    """게이트용 호스트 — value.txt=bad(버그), check.sh(불변식), fake side_cmd, 무시된 작업공간."""
    tmp = Path(tmp).resolve()
    root = make_root(tmp, overrides)
    set_failures(root, [])
    (root / "value.txt").write_text("bad\n")
    (root / "check.sh").write_text(CHECK_SH)
    (root / ".gitignore").write_text(".bugfix-pipeline/\nmode\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def gate(root, *args) -> int:
    """cwd 를 root 로 두고 bp_gate.main 을 부른다."""
    import os
    import bp_gate
    prev = os.getcwd()
    os.chdir(root)
    try:
        return bp_gate.main([str(a) for a in args])
    finally:
        os.chdir(prev)


def ledger(root, slug) -> dict:
    return json.loads((Path(root) / ".bugfix-pipeline" / slug / "ledger.json").read_text())
