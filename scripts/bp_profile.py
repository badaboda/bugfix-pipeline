"""bugfix-pipeline 프로파일 v1 — 호스트 프로젝트가 R-REGRESS 실행부에 주는 값.

사람이 쓰고(.claude/bugfix-pipeline.json) 이 파일이 잰다 — 추정해서 채우지 않는다.

  python3 scripts/bp_profile.py check [호출 루트]
  python3 scripts/bp_profile.py --selftest

설계: docs/superpowers/specs/2026-09-24-profile-v1-design.md §3·§4·§7
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

PROFILE_PATH = ".claude/bugfix-pipeline.json"
SCHEMA = 1
_TOP_KEYS = {"schema", "regress"}
_REGRESS_KEYS = {"side_cmd", "ran_fully", "not_fully", "tree_marker", "allowed_roots"}


class ProfileError(Exception):
    """프로파일 문제 — 첫 문제만이 아니라 «전부»를 담는다."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Profile:
    root: Path
    side_cmd: Tuple[str, ...]
    ran_fully: str
    not_fully: Optional[str]
    tree_marker: str
    allowed_roots: Tuple[Path, ...]


def _unknown(d, allowed, prefix):
    # 모르는 키를 무시하면 선택 필드의 오타가 그 검사를 조용히 끈다
    return [f"모르는 키: {prefix}{k}" for k in sorted(set(d) - allowed)]


def _side_cmd(root, reg, problems):
    value = reg.get("side_cmd")
    if not (isinstance(value, list) and value and all(isinstance(x, str) and x for x in value)):
        problems.append("regress.side_cmd 는 비어 있지 않은 문자열 배열이어야 한다")
        return ()
    first = value[0]
    if "/" not in first:
        if shutil.which(first) is None:
            problems.append(f"regress.side_cmd 명령을 PATH 에서 못 찾는다: {first}")
        return tuple(value)
    exe = root / first  # 상대면 호출 루트 기준 — 두 쪽이 «같은» 래퍼를 쓴다
    if not exe.is_file():
        problems.append(f"regress.side_cmd 파일이 없다: {exe}")
    elif not os.access(exe, os.X_OK):
        problems.append(f"regress.side_cmd 에 실행 권한이 없다: {exe}")
    return (str(exe), *value[1:])


def _pattern(reg, key, required, problems):
    if key not in reg:
        if required:
            problems.append(f"regress.{key} 가 없다")
        return None
    value = reg[key]
    if not isinstance(value, str) or not value:
        problems.append(f"regress.{key} 는 비어 있지 않은 문자열이어야 한다")
        return None
    if "\n" in value:
        # grep 은 개행을 «패턴 여러 개»로 읽는다
        problems.append(f"regress.{key} 에 개행이 있다")
        return None
    # 파이썬 re 가 아니라 실제로 쓸 엔진으로 잰다 — 문법이 달라 re 검사는 거짓 통과를 낸다
    syntax = subprocess.run(["grep", "-E", "--", value, os.devnull], capture_output=True)
    if syntax.returncode == 2:
        problems.append(f"regress.{key} 가 grep -E 패턴이 아니다: {value!r}")
        return None
    empty = subprocess.run(["grep", "-qE", "--", value], input=b"\n", capture_output=True)
    if empty.returncode == 0:
        problems.append(f"regress.{key} 가 빈 줄에도 걸린다 — 모든 로그에 걸려 검사가 아니다: {value!r}")
        return None
    return value


def _tree_marker(root, reg, problems):
    value = reg.get("tree_marker")
    if not isinstance(value, str) or not value:
        problems.append("regress.tree_marker 는 비어 있지 않은 문자열이어야 한다")
        return ""
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        problems.append(f"regress.tree_marker 는 트리 안의 상대 경로여야 한다: {value}")
    elif not (root / rel).exists():
        problems.append(f"regress.tree_marker 가 호출 루트에 없다: {value}")
    return value


def _allowed_roots(reg, problems):
    if "allowed_roots" not in reg:
        return ()
    value = reg["allowed_roots"]
    if not (isinstance(value, list) and all(isinstance(x, str) and x for x in value)):
        problems.append("regress.allowed_roots 는 문자열 배열이어야 한다")
        return ()
    if not value:
        problems.append("regress.allowed_roots 가 비어 있다 — 제약을 없애려면 키를 뺀다")
        return ()
    roots = []
    for x in value:
        p = Path(os.path.expanduser(x))
        if p.is_absolute():
            roots.append(p.resolve())
        else:
            problems.append(f"regress.allowed_roots 는 절대 경로여야 한다 (~ 허용): {x}")
    return tuple(roots)


def load(root) -> Profile:
    root = Path(root).resolve()
    path = root / PROFILE_PATH
    if not path.is_file():
        raise ProfileError([f"프로파일이 없다: {path}"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProfileError([f"JSON 으로 읽히지 않는다: {e}"])
    if not isinstance(data, dict):
        raise ProfileError(["최상위가 객체가 아니다"])
    problems = _unknown(data, _TOP_KEYS, "")
    schema = data.get("schema")
    if type(schema) is not int or schema != SCHEMA:  # True == 1 이라 타입을 따로 묻는다
        problems.append(f"schema 는 정수 {SCHEMA} 이어야 한다: {schema!r}")
    reg = data.get("regress")
    if not isinstance(reg, dict):
        raise ProfileError(problems + ["regress 가 없거나 객체가 아니다"])
    problems += _unknown(reg, _REGRESS_KEYS, "regress.")
    side_cmd = _side_cmd(root, reg, problems)
    ran_fully = _pattern(reg, "ran_fully", True, problems)
    not_fully = _pattern(reg, "not_fully", False, problems)
    tree_marker = _tree_marker(root, reg, problems)
    allowed_roots = _allowed_roots(reg, problems)
    if problems:
        raise ProfileError(problems)
    return Profile(root, side_cmd, ran_fully, not_fully, tree_marker, allowed_roots)


def toplevel(cwd) -> Path:
    r = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if r.returncode:
        raise ProfileError([f"git 트리 안에서 불러야 한다 — 호출 루트를 못 정한다: {cwd}"])
    return Path(r.stdout.strip())


def _check(argv) -> int:
    try:
        root = Path(argv[0]) if argv else toplevel(Path.cwd())
        p = load(root)
    except ProfileError as e:
        print("profile FAIL:", file=sys.stderr)
        for problem in e.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    print(f"profile OK — {p.root / PROFILE_PATH}")
    print(f"  side_cmd={list(p.side_cmd)}")
    print(f"  ran_fully={p.ran_fully!r} not_fully={p.not_fully!r}")
    roots = [str(r) for r in p.allowed_roots] or "제약 없음"
    print(f"  tree_marker={p.tree_marker} allowed_roots={roots}")
    return 0


# (이름, overrides, 거부 문구 — None 이면 통과해야 한다)
_SELFTEST_CASES = [
    ("정상", {}, None),
    ("schema 2", {"schema": 2}, "schema"),
    ("schema true", {"schema": True}, "schema"),
    ("모르는 최상위 키", {"extra": 1}, "모르는 키: extra"),
    ("모르는 regress 키", {"regress.not_fuly": "x"}, "모르는 키: regress.not_fuly"),
    ("side_cmd 없음", {"regress.side_cmd": None}, "side_cmd"),
    ("side_cmd 파일 없음", {"regress.side_cmd": ["bin/nope.sh"]}, "파일이 없다"),
    ("ran_fully 없음", {"regress.ran_fully": None}, "ran_fully 가 없다"),
    ("ERE 문법 오류", {"regress.ran_fully": "("}, "grep -E"),
    ("빈 줄에 걸리는 패턴", {"regress.ran_fully": "x*"}, "빈 줄"),
    ("개행 든 패턴", {"regress.not_fully": "a\nb"}, "개행"),
    ("tree_marker 절대 경로", {"regress.tree_marker": "/etc/hosts"}, "상대 경로"),
    ("tree_marker 없음", {"regress.tree_marker": "nope"}, "호출 루트에 없다"),
    ("allowed_roots 상대", {"regress.allowed_roots": ["rel"]}, "절대 경로"),
    ("allowed_roots 빈 배열", {"regress.allowed_roots": []}, "비어"),
]


def _selftest() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import bp_fixture

    failures = []
    for name, overrides, want in _SELFTEST_CASES:
        with tempfile.TemporaryDirectory() as tmp:
            root = bp_fixture.make_root(tmp, overrides)
            try:
                load(root)
                got = None
            except ProfileError as e:
                got = "\n".join(e.problems)
        if want is None and got is not None:
            failures.append(f"{name}: 통과해야 하는데 거부됐다 — {got}")
        elif want is not None and (got is None or want not in got):
            failures.append(f"{name}: '{want}' 로 거부돼야 한다 — 실제 {got!r}")
    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"selftest OK — 프로파일 {len(_SELFTEST_CASES)}개 사례")
    return 0


def main(argv) -> int:
    if argv[:1] == ["check"] and len(argv) <= 2:
        return _check(argv[1:])
    if argv == ["--selftest"]:
        return _selftest()
    print("사용법: bp_profile.py check [호출 루트] | --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
