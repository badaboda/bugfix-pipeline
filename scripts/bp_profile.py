"""bugfix-pipeline 프로파일 v2 — 호스트 프로젝트가 파이프라인에 주는 값.

사람이 쓰고(.claude/bugfix-pipeline.json) 이 파일이 잰다 — 추정해서 채우지 않는다.
파일이 없으면 기본값(가벼운 트랙만). 섹션 exec · regress · ui 는 모두 선택이다.

  python3 scripts/bp_profile.py check [호출 루트]
  python3 scripts/bp_profile.py init [호출 루트]
  python3 scripts/bp_profile.py --selftest

설계: docs/superpowers/specs/2026-09-25-skill-v1-design.md §4 · §10
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
SCHEMA = 2
DRAFT_KEY = "_draft"
DEFAULT_READY_TIMEOUT_S = 120
_TOP_KEYS = {"schema", "exec", "regress", "ui"}
_EXEC_KEYS = {"exec_cmd"}
_REGRESS_KEYS = {"side_cmd", "ran_fully", "not_fully", "tree_marker", "allowed_roots"}
_UI_KEYS = {"serve_cmd", "ready_marker", "ready_timeout_s"}


class ProfileError(Exception):
    """프로파일 문제 — 첫 문제만이 아니라 «전부»를 담는다."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Regress:
    side_cmd: Tuple[str, ...]
    ran_fully: str
    not_fully: Optional[str]
    tree_marker: str
    allowed_roots: Tuple[Path, ...]


@dataclass(frozen=True)
class Ui:
    serve_cmd: Tuple[str, ...]
    ready_marker: str
    ready_timeout_s: int


@dataclass(frozen=True)
class Profile:
    root: Path
    from_file: bool
    exec_cmd: Optional[Tuple[str, ...]]
    regress: Optional[Regress]
    ui: Optional[Ui]


def _unknown(d, allowed, prefix):
    # 모르는 키를 무시하면 선택 필드의 오타가 그 검사를 조용히 끈다
    return [f"모르는 키: {prefix}{k}" for k in sorted(set(d) - allowed)]


def _cmd(root, value, name, problems):
    """argv 배열 — 첫 요소에 / 가 있으면 호출 루트 기준 파일, 없으면 PATH 명령."""
    if not (isinstance(value, list) and value and all(isinstance(x, str) and x for x in value)):
        problems.append(f"{name} 는 비어 있지 않은 문자열 배열이어야 한다")
        return ()
    first = value[0]
    if "/" not in first:
        if shutil.which(first) is None:
            problems.append(f"{name} 명령을 PATH 에서 못 찾는다: {first}")
        return tuple(value)
    exe = root / first  # 상대면 호출 루트 기준 — 두 쪽이 «같은» 래퍼를 쓴다
    if not exe.is_file():
        problems.append(f"{name} 파일이 없다: {exe}")
    elif not os.access(exe, os.X_OK):
        problems.append(f"{name} 에 실행 권한이 없다: {exe}")
    return (str(exe), *value[1:])


def _pattern(section, prefix, key, required, problems):
    name = f"{prefix}.{key}"
    if key not in section:
        if required:
            problems.append(f"{name} 가 없다")
        return None
    value = section[key]
    if not isinstance(value, str) or not value:
        problems.append(f"{name} 는 비어 있지 않은 문자열이어야 한다")
        return None
    if "\n" in value:
        # grep 은 개행을 «패턴 여러 개»로 읽는다
        problems.append(f"{name} 에 개행이 있다")
        return None
    # 파이썬 re 가 아니라 실제로 쓸 엔진으로 잰다 — 문법이 달라 re 검사는 거짓 통과를 낸다
    syntax = subprocess.run(["grep", "-E", "-e", value, os.devnull], capture_output=True)
    if syntax.returncode == 2:
        problems.append(f"{name} 가 grep -E 패턴이 아니다: {value!r}")
        return None
    empty = subprocess.run(["grep", "-qE", "-e", value], input=b"\n", capture_output=True)
    if empty.returncode == 0:
        problems.append(f"{name} 가 빈 줄에도 걸린다 — 모든 로그에 걸려 검사가 아니다: {value!r}")
        return None
    return value


def _tree_marker(root, value, problems):
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


def _section(data, key, keys, problems):
    """없으면 None. 있으면 객체인지·모르는 키가 없는지 본다."""
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, dict):
        problems.append(f"{key} 는 객체여야 한다")
        return None
    problems += _unknown(value, keys, f"{key}.")
    return value


def _load_exec(root, data, problems):
    sec = _section(data, "exec", _EXEC_KEYS, problems)
    if sec is None:
        return None
    if "exec_cmd" not in sec:
        problems.append("exec.exec_cmd 가 없다 — 기본값을 쓰려면 exec 섹션을 뺀다")
        return None
    return _cmd(root, sec["exec_cmd"], "exec.exec_cmd", problems)


def _load_regress(root, data, problems):
    reg = _section(data, "regress", _REGRESS_KEYS, problems)
    if reg is None:
        return None
    side_cmd = _cmd(root, reg.get("side_cmd"), "regress.side_cmd", problems)
    ran_fully = _pattern(reg, "regress", "ran_fully", True, problems)
    not_fully = _pattern(reg, "regress", "not_fully", False, problems)
    tree_marker = _tree_marker(root, reg.get("tree_marker"), problems)
    allowed_roots = _allowed_roots(reg, problems)
    return Regress(side_cmd, ran_fully, not_fully, tree_marker, allowed_roots)


def _load_ui(root, data, problems):
    sec = _section(data, "ui", _UI_KEYS, problems)
    if sec is None:
        return None
    serve_cmd = _cmd(root, sec.get("serve_cmd"), "ui.serve_cmd", problems)
    ready_marker = _pattern(sec, "ui", "ready_marker", True, problems)
    timeout = sec.get("ready_timeout_s", DEFAULT_READY_TIMEOUT_S)
    if type(timeout) is not int or timeout <= 0:  # True 는 int 이므로 타입을 따로 묻는다
        problems.append(f"ui.ready_timeout_s 는 양의 정수여야 한다: {timeout!r}")
    return Ui(serve_cmd, ready_marker, timeout)


def load(root) -> Profile:
    root = Path(root).resolve()
    path = root / PROFILE_PATH
    if not path.is_file():
        return Profile(root, False, None, None, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProfileError([f"JSON 으로 읽히지 않는다: {e}"])
    if not isinstance(data, dict):
        raise ProfileError(["최상위가 객체가 아니다"])
    problems = []
    if DRAFT_KEY in data:
        problems.append(f"초안이다 — 내용을 확인한 뒤 {DRAFT_KEY} 키를 지운다")
    problems += _unknown(data, _TOP_KEYS | {DRAFT_KEY}, "")
    schema = data.get("schema")
    if schema == 1 and type(schema) is int:
        problems.append('schema 1 은 지원하지 않는다 — 섹션은 그대로 두고 "schema": 2 로 바꾼다')
    elif type(schema) is not int or schema != SCHEMA:  # True == 1 이라 타입을 따로 묻는다
        problems.append(f"schema 는 정수 {SCHEMA} 이어야 한다: {schema!r}")
    exec_cmd = _load_exec(root, data, problems)
    regress = _load_regress(root, data, problems)
    ui = _load_ui(root, data, problems)
    if problems:
        raise ProfileError(problems)
    return Profile(root, True, exec_cmd, regress, ui)


def exec_argv(profile, tree, cmd) -> list:
    """«이 트리에서 이 명령» argv. 프로파일 exec 가 없으면 내장 기본값(bp_exec_local)."""
    if profile.exec_cmd:
        return [*profile.exec_cmd, str(tree), "--", *cmd]
    local = Path(__file__).resolve().parent / "bp_exec_local.py"
    return [sys.executable, str(local), str(tree), "--", *cmd]


def toplevel(cwd) -> Path:
    r = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if r.returncode:
        raise ProfileError([f"git 트리 안에서 불러야 한다 — 호출 루트를 못 정한다: {cwd}"])
    return Path(r.stdout.strip())


TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
WRAPPER_DIR = ".claude/bugfix-pipeline"
# 스택 → 그 스택을 가리키는 파일들(앞에 있을수록 우선 — 첫 번째 발견이 tree_marker 가 된다)
STACK_SIGNALS = {
    "pytest": ["pyproject.toml", "pytest.ini", "setup.cfg", "setup.py"],
    "vitest": ["vitest.config.ts", "vitest.config.mts", "vitest.config.js", "vitest.config.mjs"],
}


def _detect(root):
    found = {}
    for stack, files in STACK_SIGNALS.items():
        hit = next((f for f in files if (root / f).is_file()), None)
        if hit:
            found[stack] = hit
    return found


def init(root) -> int:
    """초안을 쓴다. 0 = 썼다 · 2 = 쓰지 않았다(이유는 stderr). 추정하지 않는다 — 신호가 하나일 때만."""
    root = Path(root).resolve()
    profile = root / PROFILE_PATH
    if profile.exists():
        print(f"init: 이미 있다 — 덮어쓰지 않는다: {profile}", file=sys.stderr)
        return 2
    found = _detect(root)
    if len(found) != 1:
        listed = ", ".join(f"{s}({f})" for s, f in found.items()) or "없음"
        print(f"init: 스택 신호가 하나가 아니다 — {listed}. 고르지 않는다 — templates/ 에서 직접 복사한다",
              file=sys.stderr)
        return 2
    (stack, signal), = found.items()
    src = TEMPLATES / stack
    dst = root / WRAPPER_DIR
    for name in ("bp_exec.sh", "bp_side.sh"):
        if (dst / name).exists():
            print(f"init: 이미 있다 — 덮어쓰지 않는다: {dst / name}", file=sys.stderr)
            return 2
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("bp_exec.sh", "bp_side.sh"):
        shutil.copyfile(src / name, dst / name)
        (dst / name).chmod(0o755)
    data = json.loads((src / "profile.json").read_text(encoding="utf-8"))
    data["regress"]["tree_marker"] = signal
    draft = {DRAFT_KEY: f"{stack} 템플릿 초안 — 래퍼와 패턴을 확인한 뒤 이 키를 지운다", **data}
    profile.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"init: {stack} 초안을 썼다 — {profile} · {dst}/")
    print(f"  확인 후 {DRAFT_KEY} 키를 지우고: python3 {Path(__file__).name} check")
    return 0


def _check(argv) -> int:
    try:
        root = Path(argv[0]) if argv else toplevel(Path.cwd())
        p = load(root)
    except ProfileError as e:
        print("profile FAIL:", file=sys.stderr)
        for problem in e.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    if not p.from_file:
        print(f"profile 없음 — 기본값 (가벼운 트랙만): {p.root / PROFILE_PATH}")
        return 0
    print(f"profile OK — {p.root / PROFILE_PATH}")
    print(f"  exec={list(p.exec_cmd) if p.exec_cmd else '기본값(bp_exec_local)'}")
    if p.regress:
        r = p.regress
        roots = [str(x) for x in r.allowed_roots] or "제약 없음"
        print(f"  regress side_cmd={list(r.side_cmd)} ran_fully={r.ran_fully!r} not_fully={r.not_fully!r}")
        print(f"          tree_marker={r.tree_marker} allowed_roots={roots}")
    else:
        print("  regress=없음 (정식 트랙 불가)")
    print(f"  ui={'serve_cmd=' + str(list(p.ui.serve_cmd)) if p.ui else '없음 (P5b 생략)'}")
    return 0


# (이름, overrides, 거부 문구 — None 이면 통과해야 한다)
_SELFTEST_CASES = [
    ("정상", {}, None),
    ("schema 3", {"schema": 3}, "schema"),
    ("schema 1", {"schema": 1}, '"schema": 2'),
    ("schema true", {"schema": True}, "schema"),
    ("초안", {DRAFT_KEY: "x"}, DRAFT_KEY),
    ("모르는 최상위 키", {"extra": 1}, "모르는 키: extra"),
    ("모르는 regress 키", {"regress.not_fuly": "x"}, "모르는 키: regress.not_fuly"),
    ("regress 없음", {"regress": None}, None),
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
    ("exec 정상", {"exec.exec_cmd": ["sh"]}, None),
    ("exec_cmd 없음", {"exec.x": 1}, "exec.exec_cmd"),
    ("ui 정상", {"ui.serve_cmd": ["sh"], "ui.ready_marker": "^BP_URL="}, None),
    ("ui 타임아웃 0", {"ui.serve_cmd": ["sh"], "ui.ready_marker": "^U", "ui.ready_timeout_s": 0}, "ready_timeout_s"),
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
    with tempfile.TemporaryDirectory() as tmp:
        root = bp_fixture.make_root(tmp)
        (root / PROFILE_PATH).unlink()
        if load(root).from_file:
            failures.append("파일 없음: 기본값이어야 한다")
    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"selftest OK — 프로파일 {len(_SELFTEST_CASES)}개 사례 + 파일 없음")
    return 0


def main(argv) -> int:
    if argv[:1] == ["check"] and len(argv) <= 2:
        return _check(argv[1:])
    if argv[:1] == ["init"] and len(argv) <= 2:
        try:
            return init(Path(argv[1]) if len(argv) == 2 else toplevel(Path.cwd()))
        except ProfileError as e:
            print("\n".join(e.problems), file=sys.stderr)
            return 2
    if argv == ["--selftest"]:
        return _selftest()
    print("사용법: bp_profile.py check [호출 루트] | init [호출 루트] | --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
