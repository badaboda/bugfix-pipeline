"""bugfix-pipeline 게이트 — 파이프라인의 상태와 판정을 코드가 집행한다.

  python3 scripts/bp_gate.py <명령> <slug> [옵션]
  init · triage · freeze · baseline · run · refreeze · record-sweep ·
  promote · to-light · light-verify · light-report · status   ·   --selftest

상태는 <호출 루트>/.bugfix-pipeline/<slug>/ledger.json 한 파일 — 재진입 정본.
종료코드: 0 성공(run 은 PASS) · 1 run 판정이 PASS 아님 · 2 설정 오류·변조·감사 실패 · 4 cap 도달
설계: docs/superpowers/specs/2026-09-25-skill-v1-design.md §3 · §5 · §6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bp_profile  # noqa: E402

WORKSPACE_DIR = ".bugfix-pipeline"
LEDGER = "ledger.json"
REPRO_MD = "repro.md"
REPRO_SH = "repro.sh"
ROOT_CAUSE = "root_cause.json"
RUBRIC = "rubric.json"
LIGHT_CAUSE = "light_cause.json"
LIGHT_REPORT = "light_report.md"
PR_BODY = "pr_body.md"
CAP = 3
TRIAGE_RUNS = 3
LIGHT_REPRO_RUNS = 5
ENV_FAILED = 125
EXIT_OK, EXIT_JUDGED, EXIT_CONFIG, EXIT_CAP = 0, 1, 2, 4
LABEL_NO_DETERMINISM = "결정론 판정 없음"
LABEL_NO_REGRESS = "회귀 미검증"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CLOSED = {"done", "abandoned"}
REPRO_TEMPLATE = """# 재현 — {slug}

steps:
observed:
where:
expected_after:
"""


class GateError(Exception):
    def __init__(self, message, code=EXIT_CONFIG):
        super().__init__(message)
        self.code = code


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _git(root, *args, check=False):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise GateError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r


def _head(root):
    return _git(root, "rev-parse", "HEAD", check=True).stdout.strip()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _root():
    try:
        return bp_profile.toplevel(Path.cwd()).resolve()
    except bp_profile.ProfileError as e:
        raise GateError(e.problems[0])


def _profile(root):
    try:
        return bp_profile.load(root)
    except bp_profile.ProfileError as e:
        raise GateError("프로파일 오류:\n" + "\n".join(f"  - {p}" for p in e.problems))


def _ws(root, slug):
    if not _SLUG.match(slug):
        raise GateError(f"slug 는 소문자·숫자·- (최대 64자): {slug!r}")
    return root / WORKSPACE_DIR / slug


def _load(ws):
    path = ws / LEDGER
    if not path.is_file():
        raise GateError(f"작업공간이 없다 — 먼저 init: {ws}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(ws, ledger):
    tmp = ws / (LEDGER + ".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(ws / LEDGER)


def _new_ledger(slug):
    return {
        "slug": slug, "track": None, "phase": "P0", "created": _now(),
        "base_sha": None, "triage": None, "cause_id": None, "frozen": None,
        "baseline_sha": None, "red_commit": None, "red_files": None,
        "code_count": 0, "history": [], "cause_changes": [], "track_changes": [],
        "light_verifications": [],
    }


def _repro_fields(ws):
    path = ws / REPRO_MD
    if not path.is_file():
        raise GateError(f"repro.md 가 없다: {path}")
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(steps|observed|where|expected_after):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def _active_slugs(root, except_slug):
    base = root / WORKSPACE_DIR
    active = []
    for path in sorted(base.glob(f"*/{LEDGER}")) if base.is_dir() else []:
        slug = path.parent.name
        if slug != except_slug and json.loads(path.read_text())["phase"] not in _CLOSED:
            active.append(slug)
    return active


def cmd_init(root, a):
    ws = _ws(root, a.slug)
    if (ws / LEDGER).exists():
        raise GateError(f"이미 있다 — 재진입은 status: {ws}")
    rel = (ws / LEDGER).relative_to(root)
    if _git(root, "check-ignore", "-q", str(rel)).returncode != 0:
        raise GateError(f"{WORKSPACE_DIR}/ 가 git 무시 경로가 아니다 — .gitignore 에 {WORKSPACE_DIR}/ 를 더한다")
    _profile(root)
    active = _active_slugs(root, a.slug)
    if active:
        raise GateError(f"이 워크트리에 진행 중인 버그가 있다: {', '.join(active)} — 한 워크트리에 버그 하나")
    ws.mkdir(parents=True)
    (ws / REPRO_MD).write_text(REPRO_TEMPLATE.format(slug=a.slug), encoding="utf-8")
    _save(ws, _new_ledger(a.slug))
    print(f"init OK — {ws}")
    return EXIT_OK


PLACEHOLDERS = ("{exec}", "{tree}", "{out}", "{repro}")
_RUBRIC_KEYS = {"cause_id", "R-CAUSE", "R-SYMPTOM", "R-CONTROL"}
BASELINE_REF = "@baseline"


def _read_json(path, problems):
    if not path.is_file():
        problems.append(f"{path.name} 가 없다")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        problems.append(f"{path.name} 가 JSON 이 아니다: {e}")
        return None
    if not isinstance(data, dict):
        problems.append(f"{path.name} 최상위가 객체가 아니다")
        return None
    return data


def _argv(value, name, required, problems):
    if value is None:
        if required:
            problems.append(f"{name} 가 없다")
        return
    if not (isinstance(value, list) and value and all(isinstance(x, str) and x for x in value)):
        problems.append(f"{name} 는 비어 있지 않은 문자열 배열이어야 한다")
        return
    for tok in value:
        for ph in re.findall(r"\{[^{}]*\}", tok):
            if ph == "{url}":
                problems.append(f"{name}: {{url}} 은 화면 서버(계획 A3) 이후에 쓸 수 있다")
            elif ph not in PLACEHOLDERS:
                problems.append(f"{name}: 모르는 자리표시자 {ph}")


def _validate_rubric(root, ws, rub, problems):
    """문제를 모으고 동결할 patch 상대경로 목록을 돌려준다."""
    for k in sorted(set(rub) - _RUBRIC_KEYS):
        problems.append(f"rubric 모르는 키: {k}")
    if not isinstance(rub.get("cause_id"), str) or not rub.get("cause_id"):
        problems.append("rubric.cause_id 가 없다")
    for row in ("R-CAUSE", "R-SYMPTOM"):
        r = rub.get(row)
        if not isinstance(r, dict):
            problems.append(f"{row} 가 없다")
            continue
        for k in sorted(set(r) - {"probe", "assert"}):
            problems.append(f"{row} 모르는 키: {k}")
        _argv(r.get("probe"), f"{row}.probe", True, problems)
        _argv(r.get("assert"), f"{row}.assert", False, problems)
    patches = []
    ctl = rub.get("R-CONTROL")
    if not isinstance(ctl, dict) or not isinstance(ctl.get("axes"), list) or not ctl["axes"]:
        problems.append("R-CONTROL.axes 가 비었다 — 축이 하나 이상 있어야 한다")
        return patches
    for k in sorted(set(ctl) - {"axes"}):
        problems.append(f"R-CONTROL 모르는 키: {k}")
    for i, ax in enumerate(ctl["axes"]):
        name = f"R-CONTROL.axes[{i}]"
        if not isinstance(ax, dict):
            problems.append(f"{name} 는 객체여야 한다")
            continue
        for k in sorted(set(ax) - {"name", "mutate", "alive"}):
            problems.append(f"{name} 모르는 키: {k}")
        if not isinstance(ax.get("name"), str) or not ax.get("name"):
            problems.append(f"{name}.name 이 없다")
        m = ax.get("mutate")
        if isinstance(m, dict) and set(m) == {"patch"} and isinstance(m["patch"], str):
            rel = Path(m["patch"])
            if rel.is_absolute() or ".." in rel.parts:
                problems.append(f"{name}.mutate.patch 는 작업공간 안 상대 경로여야 한다")
            elif not (ws / rel).is_file():
                problems.append(f"{name}.mutate.patch 파일이 없다: {rel}")
            else:
                patches.append(rel.as_posix())
        elif isinstance(m, dict) and set(m) == {"checkout"} and isinstance(m["checkout"], str):
            ref = m["checkout"]
            if ref != BASELINE_REF and _git(root, "rev-parse", "--verify", "-q", ref + "^{commit}").returncode:
                problems.append(f"{name}.mutate.checkout 커밋이 없다: {ref}")
        else:
            problems.append(f'{name}.mutate 는 {{"patch": …}} 또는 {{"checkout": …}} 이어야 한다')
        _argv(ax.get("alive"), f"{name}.alive", False, problems)
    return patches


def _validate_frozen_set(root, ws):
    problems = []
    rc = _read_json(ws / ROOT_CAUSE, problems)
    rub = _read_json(ws / RUBRIC, problems)
    if not _repro_fields(ws).get("expected_after"):
        problems.append("repro.md 의 expected_after 가 비었다 — GATE 1 에서 사용자가 채운다")
    if rc is not None:
        v = rc.get("verdict")
        if v == "CANNOT-MEASURE":
            problems.append("판정 CANNOT-MEASURE — 동결하지 않는다. to-light --kind cannot-measure 로 이관한다")
        elif v not in ("BUG", "NOT-A-BUG"):
            problems.append(f"root_cause.verdict 가 BUG/NOT-A-BUG 가 아니다: {v!r}")
    patches = _validate_rubric(root, ws, rub, problems) if rub is not None else []
    if rc is not None and rub is not None and rc.get("cause_id") != rub.get("cause_id"):
        problems.append("root_cause.json 과 rubric.json 의 cause_id 가 다르다")
    if problems:
        raise GateError("동결 거부:\n" + "\n".join(f"  - {p}" for p in problems))
    files = [ROOT_CAUSE, RUBRIC, REPRO_MD] + ([REPRO_SH] if (ws / REPRO_SH).is_file() else []) + patches
    return rub["cause_id"], {f: _sha256(ws / f) for f in files}


_FEAT_FIX = re.compile(r"^(feat|fix)(\(|!|:)")


def cmd_baseline(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["frozen"] is None:
        raise GateError("동결 후에 기준선을 잡는다 — freeze 먼저")
    base = led["base_sha"]
    log = _git(root, "log", "--format=%H", "--reverse", f"{base}..HEAD", "--", *a.red, check=True).stdout.split()
    if not log:
        raise GateError(f"{base[:7]}..HEAD 에 RED 파일을 건드린 커밋이 없다")
    red = log[0]
    blobs = {}
    for f in a.red:
        r = _git(root, "rev-parse", f"HEAD:{f}")
        if r.returncode:
            raise GateError(f"RED 파일이 HEAD 에 없다: {f}")
        blobs[f] = r.stdout.strip()
    led.update(baseline_sha=_git(root, "rev-parse", f"{red}^", check=True).stdout.strip(),
               red_commit=red, red_files=blobs, phase="P3")
    _save(ws, led)
    print(f"baseline OK — 기준선 {led['baseline_sha'][:7]} · RED {red[:7]}")
    return EXIT_OK


def _audit_commits(root, led):
    """feat/fix 커밋은 본문에 «기준선 이후의 다른 커밋»을 가리키는 RED: <sha> 가 있어야 한다."""
    base = led["baseline_sha"]
    in_range = _git(root, "rev-list", f"{base}..HEAD", check=True).stdout.split()
    raw = _git(root, "log", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..HEAD", check=True).stdout
    problems = []
    for rec in raw.split("\x1e"):
        if not rec.strip():
            continue
        sha, subject, body = (rec.strip("\n").split("\x1f") + ["", ""])[:3]
        if not _FEAT_FIX.match(subject):
            continue
        reds = re.findall(r"^RED: ([0-9a-f]{7,40})\s*$", body, re.M)
        ok = any(
            any(c.startswith(r) and c != sha for c in in_range) and not sha.startswith(r)
            for r in reds
        )
        if not ok:
            problems.append(f"{sha[:7]} {subject!r} — 본문에 기준선 이후 다른 커밋의 RED: <sha> 가 없다")
    if problems:
        raise GateError("커밋 감사:\n" + "\n".join(f"  - {p}" for p in problems))


def _check_tamper(root, ws, led):
    problems = []
    for rel, sha in led["frozen"].items():
        p = ws / rel
        if not p.is_file() or _sha256(p) != sha:
            problems.append(f"동결 파일이 바뀌었다: {rel}")
    for rel, blob in (led["red_files"] or {}).items():
        r = _git(root, "rev-parse", f"HEAD:{rel}")
        if r.returncode or r.stdout.strip() != blob:
            problems.append(f"RED 테스트가 바뀌었다: {rel}")
    if problems:
        raise GateError("변조:\n" + "\n".join(f"  - {p}" for p in problems))


def cmd_freeze(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "formal":
        raise GateError("정식 트랙에서만 동결한다")
    if led["frozen"] is not None:
        raise GateError("이미 동결됐다 — 바꾸려면 refreeze --reason")
    cause_id, frozen = _validate_frozen_set(root, ws)
    led.update(cause_id=cause_id, frozen=frozen, phase="P2")
    _save(ws, led)
    print(f"freeze OK — cause_id={cause_id} 파일 {len(frozen)}개")
    return EXIT_OK


def cmd_refreeze(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["frozen"] is None:
        raise GateError("아직 동결 전이다 — freeze")
    cause_id, frozen = _validate_frozen_set(root, ws)
    entry = {"kind": "refreeze", "reason": a.reason, "at": _now(),
             "from_cause": led["cause_id"], "to_cause": cause_id}
    if cause_id != led["cause_id"]:
        led["cause_changes"].append(entry)
    if a.refund_last:
        _refund_last(led, entry)
    led["history"].append(entry)
    led.update(cause_id=cause_id, frozen=frozen)
    _save(ws, led)
    print(f"refreeze OK — cause_id={cause_id}")
    return EXIT_OK


def _refund_last(led, entry):
    raise GateError("환불은 Task 5 에서")


def _run_repro(profile, root, ws, tree):
    argv = bp_profile.exec_argv(profile, tree, ["sh", str(ws / REPRO_SH), str(tree)])
    r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def cmd_triage(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] is not None:
        raise GateError(f"이미 트리아지됐다 — track={led['track']}")
    profile = _profile(root)
    observed = _repro_fields(ws).get("observed", "")
    has_sh = (ws / REPRO_SH).is_file()
    if has_sh and not a.repro_confirmed:
        raise GateError("repro.sh 는 사용자가 「이게 내가 본 것」을 확인한 뒤에 쓴다 — 확인 후 --repro-confirmed")
    runs = []
    if has_sh and observed:
        for _ in range(TRIAGE_RUNS):
            code, out = _run_repro(profile, root, ws, root)
            runs.append({"exit": code, "observed": observed in out})
    deterministic = (
        bool(runs)
        and all(r["observed"] and r["exit"] != ENV_FAILED for r in runs)
        and len({r["exit"] for r in runs}) == 1
    )
    suite = profile.regress is not None
    track = "formal" if deterministic and suite and not a.light else "light"
    led.update(
        track=track, phase="P1" if track == "formal" else "L1", base_sha=_head(root),
        triage={"deterministic": deterministic, "suite": suite, "light_requested": a.light,
                "runs": runs, "repro_confirmed": a.repro_confirmed,
                "exec_default": profile.exec_cmd is None, "at": _now()},
    )
    _save(ws, led)
    print(f"triage: {track} (결정적 재현={deterministic} · 스위트={suite} · 가볍게={a.light})")
    if profile.exec_cmd is None:
        print("  경고: exec 기본값 — 사본에 추적 안 되는 의존성이 필요하면 사본 측정이 빨개진다")
    return EXIT_OK


def _change_track(led, to, reason, kind):
    led["track_changes"].append({"from": led["track"], "to": to, "kind": kind, "reason": reason,
                                 "at": _now(), "code_count": led["code_count"]})
    led["track"] = to


def cmd_promote(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "light":
        raise GateError("가벼운 트랙이 아니다")
    t = led["triage"]
    if not (t["deterministic"] and t["suite"]):
        raise GateError("정식 트랙의 전제(결정적 재현 · 스위트)가 없다 — 승급하지 않고 GATE L 에서 사용자에게 올린다")
    _change_track(led, "formal", a.reason, "promote")
    led["phase"] = "P1"
    _save(ws, led)
    print("promote: formal · P1")
    return EXIT_OK


def cmd_to_light(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "formal":
        raise GateError("정식 트랙이 아니다")
    _change_track(led, "light", a.reason, a.kind)
    led["phase"] = "L1"
    _save(ws, led)
    print(f"to-light: light · L1 ({a.kind})")
    return EXIT_OK


def cmd_status(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if a.close:
        led["phase"] = a.close
        _save(ws, led)
    judged = [h for h in led["history"] if h.get("kind") in ("run", "sweep")]
    print(f"slug={led['slug']} track={led['track']} phase={led['phase']} loop={led['code_count']}/{CAP}")
    print(f"  cause_id={led['cause_id']} 원인 교체={len(led['cause_changes'])} 트랙 변경={len(led['track_changes'])}")
    for h in judged:
        print(f"  #{h['n']} {h['kind']} {h['attribution']}{' (환불)' if h.get('refunded') else ''} @ {h['head'][:7]}")
    return EXIT_OK


def _parser():
    p = argparse.ArgumentParser(prog="bp_gate.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("slug")
    s = sub.add_parser("status")
    s.add_argument("slug")
    s.add_argument("--close", choices=sorted(_CLOSED))
    s = sub.add_parser("triage")
    s.add_argument("slug")
    s.add_argument("--light", action="store_true")
    s.add_argument("--repro-confirmed", action="store_true")
    s = sub.add_parser("promote")
    s.add_argument("slug")
    s.add_argument("--reason", required=True)
    s = sub.add_parser("to-light")
    s.add_argument("slug")
    s.add_argument("--kind", required=True, choices=["cannot-measure", "unstable", "size"])
    s.add_argument("--reason", required=True)
    s = sub.add_parser("freeze")
    s.add_argument("slug")
    s = sub.add_parser("refreeze")
    s.add_argument("slug")
    s.add_argument("--reason", required=True)
    s.add_argument("--refund-last", action="store_true")
    s = sub.add_parser("baseline")
    s.add_argument("slug")
    s.add_argument("--red", nargs="+", required=True)
    return p


COMMANDS = {"init": cmd_init, "status": cmd_status, "triage": cmd_triage,
            "promote": cmd_promote, "to-light": cmd_to_light,
            "freeze": cmd_freeze, "refreeze": cmd_refreeze, "baseline": cmd_baseline}


def main(argv) -> int:
    try:
        a = _parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_CONFIG if e.code else EXIT_OK
    try:
        return COMMANDS[a.cmd](_root(), a)
    except GateError as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
