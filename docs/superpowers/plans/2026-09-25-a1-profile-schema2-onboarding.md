# 계획 A1 — 프로파일 schema 2 · 온보딩 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로파일을 schema 2 로 올리고(파일·`exec`·`regress`·`ui` 모두 선택), 내장 `exec` 기본값 · 스택별 템플릿 · 검사를 통과하지 못하는 초안 생성 · 작업 트리를 오염시키지 않는 훅 설치를 더한다.

**Architecture:** `bp_profile.py` 가 섹션별 dataclass(`Regress` · `Ui`)를 가진 `Profile` 을 낸다. 파일이 없으면 기본 `Profile`. `bp_profile.exec_argv()` 가 «트리에서 명령 하나» argv 를 만들고, `exec` 가 없으면 `bp_exec_local.py` 로 떨어진다. `bp_regress.py` 는 `profile.regress` 를 요구한다. `templates/<스택>/` 을 `bp_profile.py init` 이 호스트의 `.claude/bugfix-pipeline/` 로 복사하고 `_draft` 키가 든 프로파일을 쓴다.

**Tech Stack:** Python 3.9 표준 라이브러리 · POSIX sh · git ≥ 2.31(`--path-format`) · 템플릿 측정용 pytest(`uvx`)·vitest(`npx`)

**Spec:** `docs/superpowers/specs/2026-09-25-skill-v1-design.md` (§4 · §8 · §10 · §11 · §14 계획 A1)

## Global Constraints

- 파이썬 3.9 호환 · 표준 라이브러리만. 외부 도구는 `sh` · `grep` · `comm` · `git` · `python3`
- 프로파일 경로 `.claude/bugfix-pipeline.json`, `schema` 는 정수 `2`. schema 1 은 이전 안내와 함께 거부
- 초안 표지 키 `_draft`. 이 키가 있으면 `load()` 가 거부한다
- 호스트에 복사되는 래퍼 위치 `.claude/bugfix-pipeline/`
- `exec` 계약: `<exec…> <트리> -- <명령…>`, cwd 는 호출 루트, 명령 종료코드 그대로, 환경 조립 실패는 **125**
- 템플릿은 **실제로 돌려 본 것만** 커밋한다(스펙 §10). 이 머신에 go 가 없으므로 go 템플릿은 이 계획에서 뺀다
- 공개 레포 — 원천 프로젝트 이름·경로·러너 문구 금지. 커밋 전 스캔(Task 6)
- Bash 는 절대경로 + 한 번에 한 명령 + `cd` 금지
- 커밋은 경로 지정: 새 파일은 `git -C /Users/marcus.k/Sandbox/bugfix-pipeline add <경로>` 선행 후
  `git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "…" -- <경로…>`.
  메시지 끝:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` 와 `Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8`
- TDD — 테스트 먼저, 실패 확인, 구현, 통과. 구현 중 테스트를 고치지 않는다
- 양성 대조 — 핵심 검사마다 깨서 빨개지는지 보고 복원
- pytest: `uvx --with pytest pytest <테스트 절대경로> -q -p no:cacheprovider --rootdir /Users/marcus.k/Sandbox/bugfix-pipeline -o pythonpath=/Users/marcus.k/Sandbox/bugfix-pipeline`

## Review Focus

1. **0.1.2 사용자의 schema 1 파일** — 거부하되 «숫자만 2 로 바꾸면 된다»는 안내가 나와야 한다 (Task 1 `test_schema_1_is_rejected_with_migration_hint`)
2. **프로파일 없는 레포에서 `bp_regress run`** — 트레이스백이 아니라 exit 2 + «regress 섹션이 없다» (Task 1 `test_missing_regress_section_is_a_config_error`)
3. **`_draft` 와 다른 문제가 함께 있을 때** — 둘 다 보고되어야 한다(초안을 고치다 생긴 실수를 한 번에 본다) (Task 1 `test_draft_is_reported_with_other_problems`)
4. **사본에서 템플릿 실행** — 템플릿의 존재 이유(사본엔 `.venv`·`node_modules` 가 없다)를 실제 `git worktree` 사본에서 잰다 (Task 4 측정 단계)
5. **심볼릭 링크 tmp 경로에서 훅 설치** — macOS `/var` → `/private/var` 차이로 정상 레포를 «작업 트리 안»으로 오판하지 않아야 한다 (Task 3 `test_install_via_symlinked_path_is_not_refused`)

---

### Task 1: 프로파일 schema 2 로더 + `bp_regress` 연결

**Files:**
- Modify: `scripts/bp_profile.py` (전면 교체 — 아래 코드)
- Modify: `scripts/bp_fixture.py` (`PROFILE_DEFAULTS` · `write_profile`)
- Modify: `scripts/bp_regress.py` (`regress` 섹션 요구)
- Modify: `tests/test_bp_profile.py` · `tests/test_bp_regress.py`

**Interfaces:**
- Produces:
  - `bp_profile.SCHEMA = 2`, `PROFILE_PATH`, `DRAFT_KEY = "_draft"`, `ProfileError(problems)`
  - `bp_profile.Regress` — `side_cmd: Tuple[str,...]`, `ran_fully: str`, `not_fully: Optional[str]`, `tree_marker: str`, `allowed_roots: Tuple[Path,...]`
  - `bp_profile.Ui` — `serve_cmd: Tuple[str,...]`, `ready_marker: str`, `ready_timeout_s: int`
  - `bp_profile.Profile` — `root: Path`, `from_file: bool`, `exec_cmd: Optional[Tuple[str,...]]`, `regress: Optional[Regress]`, `ui: Optional[Ui]`
  - `bp_profile.load(root) -> Profile` (파일 없으면 기본값) · `toplevel(cwd)` · `main(argv)`
  - `bp_fixture.write_profile(root, overrides)` — 키 `"섹션.이름"` 또는 최상위 이름. 값 `None` 이면 뺀다

- [ ] **Step 1: 픽스처를 schema 2 로 올린다**

`scripts/bp_fixture.py` 의 `PROFILE_DEFAULTS` 첫 줄 `"schema": 1,` 을 `"schema": 2,` 로 바꾸고, `write_profile` 의 분기 부분을 교체한다:

```python
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
```

- [ ] **Step 2: 테스트를 schema 2 에 맞게 고치고 새 테스트를 쓴다**

`tests/test_bp_profile.py`:
- `test_missing_profile_file_is_named` 를 지우고 아래 `test_missing_profile_file_means_defaults` 로 대체
- `test_every_problem_is_reported_not_only_the_first` · `test_check_cli_exit_codes` 의 `{"schema": 2}` 를 `{"schema": 3}` 으로
- `test_valid_profile_resolves_side_cmd_against_the_invocation_root` 의 `p.side_cmd` · `p.ran_fully` · `p.not_fully` · `p.tree_marker` · `p.allowed_roots` 를 `p.regress.<같은 이름>` 으로
- 파일 끝에 추가:

```python
def test_missing_profile_file_means_defaults(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    (root / PROFILE_PATH).unlink()
    p = load(root)
    assert (p.from_file, p.exec_cmd, p.regress, p.ui) == (False, None, None, None)


def test_schema_1_is_rejected_with_migration_hint(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"schema": 1}), "\"schema\": 2")


def test_regress_section_is_optional(tmp_path):
    p = load(bp_fixture.make_root(tmp_path, {"regress": None}))
    assert p.from_file and p.regress is None


def test_exec_cmd_is_resolved_like_side_cmd(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"exec.exec_cmd": ["bin/side.sh"]})
    assert load(root).exec_cmd == (str(root / "bin" / "side.sh"),)


def test_exec_section_without_exec_cmd_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"exec.other": 1}), "exec.exec_cmd")


def test_unknown_key_inside_exec_is_rejected(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"exec.exec_cmd": ["sh"], "exec.typo": 1})
    _one(root, "모르는 키: exec.typo")


def test_ui_section_defaults_the_timeout(tmp_path):
    root = bp_fixture.make_root(
        tmp_path, {"ui.serve_cmd": ["bin/side.sh"], "ui.ready_marker": "^BP_URL="}
    )
    assert load(root).ui.ready_timeout_s == 120


def test_ui_boolean_timeout_is_rejected(tmp_path):
    root = bp_fixture.make_root(
        tmp_path,
        {"ui.serve_cmd": ["sh"], "ui.ready_marker": "^BP_URL=", "ui.ready_timeout_s": True},
    )
    _one(root, "ready_timeout_s")


def test_ui_ready_marker_gets_the_pattern_checks(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"ui.serve_cmd": ["sh"], "ui.ready_marker": ".*"})
    _one(root, "빈 줄")


def test_draft_is_reported_with_other_problems(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"_draft": "확인 후 지운다", "regress.typo": 1})
    problems = _problems(root)
    assert any("_draft" in p for p in problems) and any("regress.typo" in p for p in problems)
```

`tests/test_bp_regress.py`:
- `test_early_stop_overwrites_a_stale_exit_file` 의 `{"schema": 2}` 를 `{"schema": 3}` 으로
- 파일 끝에 추가:

```python
def test_missing_regress_section_is_a_config_error(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    bp_fixture.write_profile(root, {"regress": None})
    assert run(base, root, tmp_path / "out", root=root) == 2
```

- [ ] **Step 3: 실패를 확인한다**

Run: `uvx --with pytest pytest /Users/marcus.k/Sandbox/bugfix-pipeline/tests -q -p no:cacheprovider --rootdir /Users/marcus.k/Sandbox/bugfix-pipeline -o pythonpath=/Users/marcus.k/Sandbox/bugfix-pipeline --tb=no`
Expected: 다수 FAIL — schema 1 로더가 schema 2 픽스처를 거부한다(`schema 는 정수 1`)

- [ ] **Step 4: `bp_profile.py` 를 교체한다**

`scripts/bp_profile.py` 전체:

```python
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
    if argv == ["--selftest"]:
        return _selftest()
    print("사용법: bp_profile.py check [호출 루트] | init [호출 루트] | --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: `bp_regress.py` 를 `regress` 섹션에 연결한다**

`scripts/bp_regress.py`:

(a) `run()` 에서 `profile = bp_profile.load(root)` 를 담은 `try/except` 블록 바로 뒤에 추가:

```python
        reg = profile.regress
        if reg is None:
            raise _Stop(
                EXIT_CONFIG,
                "설정 오류: 프로파일에 regress 섹션이 없다 — R-REGRESS 는 테스트 스위트가 있는 프로젝트에서만 잰다",
            )
```

(b) 같은 함수 안의 `_preflight(profile, …)` · `" ".join(profile.side_cmd)` · `_run_side(profile, …)` 두 곳 · `_judge(profile, out)` 의 `profile` 을 `reg` 로 바꾼다. `_run_side` 두 호출에는 마지막 인자로 `profile.root` 를 더한다.

(c) `_run_side` 시그니처를 `def _run_side(reg, side, tree, out, meta, checked_head, root) -> None:` 로 바꾸고, 본문의 `profile.side_cmd` → `reg.side_cmd`, `cwd=str(profile.root)` → `cwd=str(root)`.

(d) `_preflight` · `_judge` 의 매개변수 이름 `profile` 을 `reg` 로 바꾼다(본문의 `profile.` 도 `reg.`). `Regress` 가 같은 필드 이름(`allowed_roots` · `tree_marker` · `ran_fully` · `not_fully`)을 가지므로 본문 로직은 그대로다.

(e) `_case_bad_profile` 의 `{"schema": 2}` 를 `{"schema": 3}` 으로.

- [ ] **Step 6: 통과를 확인한다**

Run: 위 pytest 명령 (`--tb=short`)
Expected: 전부 통과 (기존 217 − 1 + 11 = 227)

Run: `python3 /Users/marcus.k/Sandbox/bugfix-pipeline/scripts/bp_profile.py --selftest` → `selftest OK — 프로파일 22개 사례 + 파일 없음`
Run: `python3 /Users/marcus.k/Sandbox/bugfix-pipeline/scripts/bp_regress.py --selftest` → `selftest OK — 시나리오 10개 + argv 대칭`

- [ ] **Step 7: 양성 대조**

(a) `load()` 의 `if DRAFT_KEY in data:` 두 줄만 지운다(`_unknown` 은 `DRAFT_KEY` 를 계속 제외) → 초안이 어떤 문구로도 보고되지 않으므로 `test_draft_is_reported_with_other_problems` FAIL. 복원.
(b) `run()` 의 `if reg is None:` 블록을 지운다 → `test_missing_regress_section_is_a_config_error` 가 3(예외 방어선) 으로 FAIL. 복원.

- [ ] **Step 8: 커밋**

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "feat(profile): schema 2 — 파일·exec·regress·ui 모두 선택, 초안 표지, schema 1 이전 안내

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- scripts/bp_profile.py scripts/bp_fixture.py scripts/bp_regress.py tests/test_bp_profile.py tests/test_bp_regress.py
```
Expected: `5 files changed`

---

### Task 2: `exec` 기본값 — `bp_exec_local.py` 와 `exec_argv()`

**Files:**
- Create: `scripts/bp_exec_local.py`
- Modify: `scripts/bp_profile.py` (`exec_argv` 추가)
- Test: `tests/test_bp_exec.py`

**Interfaces:**
- Consumes: `bp_profile.Profile.exec_cmd` (Task 1)
- Produces: `bp_profile.exec_argv(profile, tree, cmd) -> list` · `python3 scripts/bp_exec_local.py <트리> -- <명령…>` (환경 실패 125)

- [ ] **Step 1: 실패하는 테스트**

`tests/test_bp_exec.py`:

```python
"""exec 계약 — 기본값(bp_exec_local)과 프로파일 exec_cmd 가 같은 모양의 argv 를 낸다."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
import bp_profile  # noqa: E402


def _run(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def test_default_exec_runs_the_command_inside_the_tree(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    tree = tmp_path / "tree"
    tree.mkdir()
    argv = bp_profile.exec_argv(bp_profile.load(root), tree, ["pwd"])
    r = _run(argv, root)
    assert r.returncode == 0 and Path(r.stdout.strip()).resolve() == tree.resolve()


def test_default_exec_passes_the_exit_code_through(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), root, ["sh", "-c", "exit 7"])
    assert _run(argv, root).returncode == 7


def test_default_exec_missing_tree_is_125(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), tmp_path / "nope", ["true"])
    assert _run(argv, root).returncode == 125


def test_default_exec_missing_command_is_125(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), root, ["no-such-command-bp"])
    assert _run(argv, root).returncode == 125


def test_profile_exec_cmd_gets_tree_and_separator(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"exec.exec_cmd": ["bin/side.sh", "--flag"]})
    p = bp_profile.load(root)
    assert bp_profile.exec_argv(p, root, ["pytest", "-q"]) == [
        str(root / "bin" / "side.sh"), "--flag", str(root), "--", "pytest", "-q",
    ]
```

- [ ] **Step 2: 실패 확인**

Run: `uvx --with pytest pytest /Users/marcus.k/Sandbox/bugfix-pipeline/tests/test_bp_exec.py -q -p no:cacheprovider --rootdir /Users/marcus.k/Sandbox/bugfix-pipeline -o pythonpath=/Users/marcus.k/Sandbox/bugfix-pipeline --tb=line`
Expected: 5 FAIL — `AttributeError: module 'bp_profile' has no attribute 'exec_argv'`

- [ ] **Step 3: 구현**

`scripts/bp_exec_local.py`:

```python
"""내장 exec 기본값 — 프로파일에 exec 가 없을 때 «트리에서 명령 하나»를 그대로 돈다.

  python3 scripts/bp_exec_local.py <트리> -- <명령…>

명령의 종료코드를 그대로 돌려준다. 명령을 «돌리지 못하면»(트리 없음·명령 없음) 125 —
exec 계약에서 125 는 「probe 가 돌지 못했다」(ENV)다. 사본에는 git 이 추적하지 않는 파일이
없다는 것을 이 기본값은 해결하지 않는다 — 그런 프로젝트는 프로파일에 exec 를 둔다.
"""
import subprocess
import sys
from pathlib import Path

ENV_FAILED = 125


def main(argv) -> int:
    if len(argv) < 3 or argv[1] != "--":
        print("사용법: bp_exec_local.py <트리> -- <명령…>", file=sys.stderr)
        return ENV_FAILED
    tree = Path(argv[0])
    if not tree.is_dir():
        print(f"bp_exec_local: 트리가 없다 — {tree}", file=sys.stderr)
        return ENV_FAILED
    try:
        return subprocess.run(argv[2:], cwd=str(tree)).returncode
    except OSError as e:
        print(f"bp_exec_local: 명령을 돌리지 못했다 — {e}", file=sys.stderr)
        return ENV_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`scripts/bp_profile.py` 의 `toplevel` 바로 위에 추가:

```python
def exec_argv(profile, tree, cmd) -> list:
    """«이 트리에서 이 명령» argv. 프로파일 exec 가 없으면 내장 기본값(bp_exec_local)."""
    if profile.exec_cmd:
        return [*profile.exec_cmd, str(tree), "--", *cmd]
    local = Path(__file__).resolve().parent / "bp_exec_local.py"
    return [sys.executable, str(local), str(tree), "--", *cmd]
```

- [ ] **Step 4: 통과 확인** — Step 2 명령 → `5 passed`

- [ ] **Step 5: 양성 대조** — `bp_exec_local.py` 의 `except OSError` 분기를 지운다 → `test_default_exec_missing_command_is_125` FAIL(트레이스백 exit 1). 복원.

- [ ] **Step 6: 커밋**

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline add scripts/bp_exec_local.py tests/test_bp_exec.py
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "feat(exec): 내장 exec 기본값 bp_exec_local · exec_argv — 무설정으로 트리에서 명령 하나

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- scripts/bp_exec_local.py scripts/bp_profile.py tests/test_bp_exec.py
```
Expected: `3 files changed`

---

### Task 3: 훅 설치가 작업 트리를 오염시키지 않게

**Files:**
- Modify: `hooks/install.sh` (install 분기)
- Test: `tests/test_install_sh.py`

**Interfaces:**
- Produces: `hooks/install.sh install` — hooks 경로가 작업 트리 안(공용 git 디렉토리 밖)이면 exit 1 + `작업 트리 안` 문구, 파일을 만들지 않는다

- [ ] **Step 1: 실패하는 테스트**

`tests/test_install_sh.py`:

```python
"""hooks/install.sh — core.hooksPath 레포에서 작업 트리에 파일을 흘리지 않는다 (스펙 §8 실측)."""
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "hooks" / "install.sh"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _repo(path, hooks_path=None, existing_hook=False):
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "fix/a")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    if hooks_path:
        _git(path, "config", "core.hooksPath", hooks_path)
        (path / hooks_path).mkdir()
        if existing_hook:
            hook = path / hooks_path / "commit-msg"
            hook.write_text("#!/bin/sh\nexit 0\n")
            hook.chmod(0o755)
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def _install(cwd):
    return subprocess.run(["sh", str(INSTALL), "install"], cwd=cwd, capture_output=True, text=True)


def test_plain_repo_installs_into_git_hooks(tmp_path):
    repo = _repo(tmp_path / "r")
    assert _install(repo).returncode == 0
    assert (repo / ".git" / "hooks" / "commit-msg").is_file()


def test_hooks_path_inside_the_worktree_is_refused_without_writing(tmp_path):
    repo = _repo(tmp_path / "r", hooks_path=".husky")
    r = _install(repo)
    assert r.returncode == 1 and "작업 트리 안" in r.stderr
    assert not (repo / ".husky" / "commit-msg").exists()
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_existing_hook_is_still_not_overwritten(tmp_path):
    repo = _repo(tmp_path / "r", hooks_path=".husky", existing_hook=True)
    r = _install(repo)
    assert r.returncode == 1
    assert (repo / ".husky" / "commit-msg").read_text() == "#!/bin/sh\nexit 0\n"


def test_linked_worktree_still_installs(tmp_path):
    repo = _repo(tmp_path / "r")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "fix/b", str(wt))
    assert _install(wt).returncode == 0


def test_install_via_symlinked_path_is_not_refused(tmp_path):
    repo = _repo(tmp_path / "real" / "r")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    assert _install(link / "r").returncode == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uvx --with pytest pytest /Users/marcus.k/Sandbox/bugfix-pipeline/tests/test_install_sh.py -q -p no:cacheprovider --rootdir /Users/marcus.k/Sandbox/bugfix-pipeline -o pythonpath=/Users/marcus.k/Sandbox/bugfix-pipeline --tb=line`
Expected: `test_hooks_path_inside_the_worktree_is_refused_without_writing` FAIL (지금은 rc 0 으로 설치한다). 나머지는 통과할 수 있다 — 기존 동작의 회귀 고정이다

- [ ] **Step 3: 구현**

`hooks/install.sh` 의 `install)` 분기 첫 줄 `mkdir -p "$hooks_dir"` **앞에** 넣는다:

```sh
    # 🔴 core.hooksPath 가 작업 트리 안(.husky 등)을 가리키면 거기 쓰는 순간 사용자 레포에 파일이 생긴다
    # (실측 2026-09-25: `?? .husky/`). 공용 git 디렉토리 밖이면서 작업 트리 안이면 거부한다 — 판정은
    # bp_gate 의 커밋 감사가 하므로 이 훅은 선택이다(스펙 §8).
    abs_hooks=$(git rev-parse --path-format=absolute --git-path hooks)
    abs_common=$(git rev-parse --path-format=absolute --git-common-dir)
    abs_top=$(git rev-parse --show-toplevel)
    case "$abs_hooks" in
      /*) ;;
      *) echo "git 2.31+ 가 필요하다 (--path-format)" >&2; exit 1 ;;
    esac
    case "$abs_hooks/" in
      "$abs_common"/*) ;;
      "$abs_top"/*)
        echo "훅 경로가 작업 트리 안이다 — 설치하지 않는다: $abs_hooks" >&2
        echo "  (RED 규칙은 bp_gate run 의 커밋 감사가 집행한다. 이 훅은 선택이다)" >&2
        exit 1 ;;
    esac
```

- [ ] **Step 4: 통과 확인** — Step 2 명령 → `5 passed`. 대칭 경로 테스트가 실패하면(심볼릭 링크 때문에 `abs_top` 과 `abs_hooks` 의 접두가 다르게 나오면) 테스트를 고치지 말고 `pwd -P` 로 세 값을 정규화하는 것을 Ruling 으로 남기고 고친다

- [ ] **Step 5: 기존 검증 재확인** — `python3 /private/tmp/claude-501/-Users-marcus-k-Sandbox-bugfix-pipeline/3ff54c8c-1632-4673-b6f2-0ab8ad1755da/scratchpad/repro_hook.py /Users/marcus.k/Sandbox/bugfix-pipeline/hooks` → 여섯 항목 PASS (파일이 없으면 이 단계는 Task 3 테스트가 대신한다 — Ruling 으로 남긴다)

- [ ] **Step 6: 양성 대조** — 추가한 `"$abs_top"/*)` 분기를 지운다 → 작업 트리 안 테스트 FAIL. 복원.

- [ ] **Step 7: 커밋**

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline add tests/test_install_sh.py
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "fix(hooks): core.hooksPath 가 작업 트리 안이면 설치 거부 — 사용자 레포에 파일을 흘리지 않는다

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- hooks/install.sh tests/test_install_sh.py
```

---

### Task 4: 스택별 템플릿 — pytest · vitest (실측)

**Files:**
- Create: `templates/pytest/bp_exec.sh` · `templates/pytest/bp_side.sh` · `templates/pytest/profile.json`
- Create: `templates/vitest/bp_exec.sh` · `templates/vitest/bp_side.sh` · `templates/vitest/profile.json`

**Interfaces:**
- Produces: 템플릿 디렉토리 규약 — `templates/<스택>/{bp_exec.sh, bp_side.sh, profile.json}`. `profile.json` 의 래퍼 경로는 `.claude/bugfix-pipeline/<파일>`, `tree_marker` 는 `"__SIGNAL__"`(init 이 치환)

이 태스크는 코드 TDD 가 아니라 **측정 주도**다 — 각 템플릿을 «실패 1 · 통과 1 · 오류 1» 샘플 트리와 그 트리의 `git worktree` 사본에서 돌려 이름 파일과 `ran_fully` 를 확인한 뒤에만 커밋한다. 측정 결과와 다르면 템플릿을 고치고 다시 잰다.

- [ ] **Step 1: pytest 템플릿을 쓴다**

`templates/pytest/bp_exec.sh`:

```sh
#!/bin/sh
# bp_exec.sh <트리> -- <명령…> — 그 트리에서 명령 하나. cwd 는 호출 루트(계약).
# 사본에는 git 이 추적하지 않는 .venv 가 없다 — 호출 루트의 .venv 를 PATH 앞에 둔다.
tree=$1; shift
[ "$1" = "--" ] || { echo "사용법: bp_exec.sh <트리> -- <명령…>" >&2; exit 125; }
shift
[ -d "$tree" ] || { echo "bp_exec: 트리가 없다 — $tree" >&2; exit 125; }
root=$(pwd)
if [ ! -d "$tree/.venv" ] && [ -d "$root/.venv" ]; then
  PATH="$root/.venv/bin:$PATH"; export PATH
fi
cd "$tree" || exit 125
exec "$@"
```

`templates/pytest/bp_side.sh`:

```sh
#!/bin/sh
# bp_side.sh <트리> <이름 출력> — 그 트리에서 전체 스위트를 돌리고 실패·오류 id 를 쓴다.
# stdout 이 곧 로그다 — 프로파일의 ran_fully 가 여기서 요약 줄을 찾는다.
tree=$1; names=$2
here=$(cd "$(dirname "$0")" && pwd)
raw="$names.raw"
"$here/bp_exec.sh" "$tree" -- ${BP_PYTEST:-python3 -m pytest} -rfE -p no:cacheprovider > "$raw" 2>&1
status=$?
cat "$raw"
# FAILED 만 세면 fixture·setup 오류(ERROR)가 빠진다 — 그것도 «새 빨강»이다
grep -E '^(FAILED|ERROR) ' "$raw" | sed -E 's/^(FAILED|ERROR) //; s/ - .*//' > "$names"
rm -f "$raw"
exit $status
```

`templates/pytest/profile.json`:

```json
{
  "schema": 2,
  "exec": { "exec_cmd": [".claude/bugfix-pipeline/bp_exec.sh"] },
  "regress": {
    "side_cmd": [".claude/bugfix-pipeline/bp_side.sh"],
    "ran_fully": "^=+ .*[0-9]+ (passed|failed|errors?)",
    "not_fully": "Interrupted|INTERNALERROR",
    "tree_marker": "__SIGNAL__"
  }
}
```

- [ ] **Step 2: pytest 템플릿을 잰다**

scratchpad 에 git 레포 `/private/tmp/claude-501/-Users-marcus-k-Sandbox-bugfix-pipeline/3ff54c8c-1632-4673-b6f2-0ab8ad1755da/scratchpad/tpl/py` 를 만든다: `pyproject.toml`(빈 `[project]` 이름만) · `tests/test_x.py`(통과 1 · 실패 1 · fixture 오류 1 — 이전 `errtree` 와 같은 내용) · `.claude/bugfix-pipeline/` 에 두 래퍼 복사(실행 권한) · `.venv` 는 `uv venv` + `uv pip install pytest` 로 루트에만. 커밋 후 `git worktree add --detach ../py-copy HEAD`.

루트와 사본 각각에서(cwd = 루트 — 계약):
- `.claude/bugfix-pipeline/bp_side.sh <트리> <이름 출력>` → 이름 파일이 정확히 두 줄(실패·오류), 로그 마지막 요약 줄이 `ran_fully` 에 `grep -cE` 로 1
- 사본 측정이 루트와 같은 결과인지 — `.venv` 공유가 실제로 먹는지가 이 템플릿의 존재 이유다
- 수집 오류 트리(문법 오류 파일 하나 추가)에서 `not_fully` 가 걸리는지

결과를 Step 6 커밋 메시지에 적는다. 다르면 템플릿을 고치고 다시 잰다.

- [ ] **Step 3: vitest 템플릿을 쓴다**

`templates/vitest/bp_exec.sh`:

```sh
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
```

`templates/vitest/bp_side.sh`:

```sh
#!/bin/sh
# bp_side.sh <트리> <이름 출력> — 그 트리에서 전체 스위트를 돌리고 실패 id 를 쓴다.
# 이름은 JSON 리포터에서 뽑는다(텍스트 출력은 버전마다 모양이 다르다). stdout 은 기본 리포터 — 로그다.
tree=$1; names=$2
here=$(cd "$(dirname "$0")" && pwd)
json="$names.json"
"$here/bp_exec.sh" "$tree" -- npx vitest run --reporter=default --reporter=json --outputFile.json="$json" 2>&1
status=$?
python3 - "$json" "$names" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
out = []
try:
    data = json.load(open(src))
except (OSError, ValueError):
    data = {"testResults": []}
for f in data.get("testResults", []):
    failed = [a for a in f.get("assertionResults", []) if a.get("status") == "failed"]
    for a in failed:
        out.append(f"{f.get('name')} > {a.get('fullName')}")
    if f.get("status") == "failed" and not failed:
        out.append(f"{f.get('name')}")  # 파일 수준 오류(import 실패 등)
open(dst, "w").write("".join(x + "\n" for x in out))
PY
rm -f "$json"
exit $status
```

`templates/vitest/profile.json`:

```json
{
  "schema": 2,
  "exec": { "exec_cmd": [".claude/bugfix-pipeline/bp_exec.sh"] },
  "regress": {
    "side_cmd": [".claude/bugfix-pipeline/bp_side.sh"],
    "ran_fully": "^ +Tests +[0-9]+",
    "tree_marker": "__SIGNAL__"
  }
}
```

- [ ] **Step 4: vitest 템플릿을 잰다**

scratchpad `tpl/vt` git 레포: `package.json`(`"type": "module"`, devDependency vitest) · `npm install` · `src/x.test.js`(통과 1 · 실패 1) · `src/bad.test.js`(import 실패) · 래퍼 복사 · 커밋(`node_modules` 는 `.gitignore`) · `git worktree add --detach ../vt-copy HEAD`.

루트와 사본에서 Step 2 와 같은 항목을 잰다: 이름 파일(실패 1 + 파일 오류 1), `ran_fully`(요약 `Tests` 줄), 사본에서 `node_modules` 링크가 먹는지. vitest 요약 줄 모양이 가정과 다르면 `ran_fully` 를 실측에 맞춰 고치고 Ruling 으로 남긴다. **파일 오류만 있고 테스트가 하나도 안 돈 경우**에도 `ran_fully` 가 걸리는지 확인하고, 걸리지 않으면 그 사실을 템플릿 주석과 커밋 메시지에 적는다.

- [ ] **Step 5: 템플릿 파일 권한** — `chmod +x` 네 래퍼. `git -C /Users/marcus.k/Sandbox/bugfix-pipeline add templates` 후 `git -C … ls-files -s templates` 로 모드가 `100755` 인지 확인.

- [ ] **Step 6: 커밋** — 메시지에 측정 결과(루트·사본 이름 줄 수, 요약 줄 매치)를 적는다.

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "feat(templates): pytest · vitest 래퍼 템플릿 — 루트·사본 실측 <결과>

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- templates
```

---

### Task 5: `bp_profile.py init` — 검사를 통과하지 못하는 초안

**Files:**
- Modify: `scripts/bp_profile.py` (`init` 추가, `main` 분기)
- Test: `tests/test_bp_profile_init.py`

**Interfaces:**
- Consumes: `templates/<스택>/` (Task 4) · `DRAFT_KEY` · `load` (Task 1)
- Produces: `bp_profile.init(root) -> int` (0 초안 씀 · 2 쓰지 않음) · `STACK_SIGNALS: dict` · CLI `init [root]`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_bp_profile_init.py`:

```python
"""init — 레포 신호로 템플릿을 골라 «검사를 통과하지 못하는» 초안을 쓴다."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_profile  # noqa: E402
from bp_profile import PROFILE_PATH, ProfileError, init, load  # noqa: E402


def test_pyproject_gets_a_pytest_draft_that_check_rejects(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert init(tmp_path) == 0
    data = json.loads((tmp_path / PROFILE_PATH).read_text())
    assert data["regress"]["tree_marker"] == "pyproject.toml"
    with pytest.raises(ProfileError) as e:
        load(tmp_path)
    assert any("_draft" in p for p in e.value.problems)


def test_draft_passes_once_the_draft_key_is_removed(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    init(tmp_path)
    path = tmp_path / PROFILE_PATH
    data = json.loads(path.read_text())
    del data["_draft"]
    path.write_text(json.dumps(data))
    p = load(tmp_path)
    assert p.regress.side_cmd[0].endswith(".claude/bugfix-pipeline/bp_side.sh")


def test_vitest_config_gets_a_vitest_draft(tmp_path):
    (tmp_path / "vitest.config.ts").write_text("export default {}\n")
    assert init(tmp_path) == 0
    assert (tmp_path / ".claude" / "bugfix-pipeline" / "bp_side.sh").read_text().count("vitest") >= 1


def test_existing_profile_is_never_overwritten(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".claude").mkdir()
    (tmp_path / PROFILE_PATH).write_text('{"schema": 2}')
    assert init(tmp_path) == 2
    assert (tmp_path / PROFILE_PATH).read_text() == '{"schema": 2}'


def test_no_signal_writes_nothing(tmp_path, capsys):
    assert init(tmp_path) == 2
    assert not (tmp_path / ".claude").exists()


def test_two_stacks_are_listed_not_guessed(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "vitest.config.ts").write_text("")
    assert init(tmp_path) == 2
    err = capsys.readouterr().err
    assert "pytest" in err and "vitest" in err
    assert not (tmp_path / PROFILE_PATH).exists()


def test_copied_wrappers_are_executable(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    init(tmp_path)
    for name in ("bp_side.sh", "bp_exec.sh"):
        assert (tmp_path / ".claude" / "bugfix-pipeline" / name).stat().st_mode & 0o111
```

- [ ] **Step 2: 실패 확인** — `ImportError: cannot import name 'init'`

- [ ] **Step 3: 구현** — `scripts/bp_profile.py` 의 `_check` 위에 추가:

```python
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
```

`main` 에 분기 추가(`check` 분기 아래):

```python
    if argv[:1] == ["init"] and len(argv) <= 2:
        try:
            return init(Path(argv[1]) if len(argv) == 2 else toplevel(Path.cwd()))
        except ProfileError as e:
            print("\n".join(e.problems), file=sys.stderr)
            return 2
```

- [ ] **Step 4: 통과 확인** — `7 passed`. 전체 스위트도 돌린다.

- [ ] **Step 5: 양성 대조** — `draft = {DRAFT_KEY: …, **data}` 를 `draft = data` 로 → 첫 테스트 FAIL. 복원.

- [ ] **Step 6: 커밋**

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline add tests/test_bp_profile_init.py
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "feat(profile): init — 신호 하나일 때만 템플릿 초안, _draft 로 확인 전 사용 불가

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- scripts/bp_profile.py tests/test_bp_profile_init.py
```

---

### Task 6: 문서와 전체 검증

**Files:**
- Modify: `docs/profile.md` (schema 2 로 갱신)
- Modify: `README.md` · `CLAUDE.md`

- [ ] **Step 1: `docs/profile.md` 를 schema 2 로 고친다** — 다음을 담는다: 파일 선택(없으면 가벼운 트랙만) · 섹션 `exec`(계약 · 125 · 기본값 `bp_exec_local` · 사본 의존성 공유 패턴 — Task 4 템플릿의 `.venv`·`node_modules` 방식을 발췌) · `regress`(기존 내용 유지, schema 표기만 2) · `ui`(계약 · `ready_marker` · 타임아웃 · 종료 신호) · schema 1 이전(숫자만 2 로) · `init` 사용법과 `_draft` · 지원 스택(pytest · vitest 실측, go 는 미측정이라 템플릿 없음). 예시 JSON 은 Task 4 템플릿에서 그대로 가져온다 — 문서에만 있는 값을 만들지 않는다.

- [ ] **Step 2: README 현재 상태 표** — `scripts/bp_profile.py · scripts/bp_regress.py` 행을 `프로파일 v2(schema 2) · init 초안 · bp_exec_local 기본값` 으로 갱신하고 `templates/` 행(pytest · vitest 실측, go 없음)을 추가한다.

- [ ] **Step 3: CLAUDE.md** — 레이아웃 블록에 `templates/<스택>/  bp_exec.sh · bp_side.sh · profile.json (실측한 것만)` 한 줄, `scripts/` 줄에 `bp_exec_local.py`. 자체 검사 블록은 그대로(selftest 명령 불변).

- [ ] **Step 4: 전체 검증**
- `python3 …/scripts/bugfix_verdict.py --selftest` · `sh …/scripts/regress.sh selftest` · `python3 …/scripts/bp_profile.py --selftest` · `python3 …/scripts/bp_regress.py --selftest` — 모두 OK
- 전체 pytest — 모두 통과(개수를 적는다)
- `claude plugin validate /Users/marcus.k/Sandbox/bugfix-pipeline` — passed

- [ ] **Step 5: 공개 레포 스캔** — `git -C /Users/marcus.k/Sandbox/bugfix-pipeline grep --untracked --exclude-standard -n -i -E "admitcraft|badaboda/Admit|PR #|calendar|_workspace|colima|run_unit_chunked|합계" -- . ":!docs/superpowers/plans/"` → 0 줄

- [ ] **Step 6: 커밋**

```
git -C /Users/marcus.k/Sandbox/bugfix-pipeline -c user.name=marcus.k -c user.email=badaboda@gmail.com commit -m "docs(profile): schema 2 · exec 기본값 · ui · init · 템플릿

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SFmjruLueEe4B2fcz43TM8" -- docs/profile.md README.md CLAUDE.md
```

push 와 버전 올리기는 사용자 승인 후 — 이 계획의 범위가 아니다.
