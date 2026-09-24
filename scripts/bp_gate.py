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
import bp_regress  # noqa: E402
import bp_ui  # noqa: E402
from bugfix_verdict import Attribution, verdict  # noqa: E402

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
EXIT_OK, EXIT_JUDGED, EXIT_CONFIG, EXIT_UNEXPECTED, EXIT_CAP = 0, 1, 2, 3, 4
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


def _require_clean(root):
    """게이트는 «커밋된» 트리를 잰다. 커밋 안 된 수정은 감사·변조 검사를 비껴가 PASS 를 만든다(A2 리뷰 실측)."""
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all", check=True).stdout.strip()
    if dirty:
        raise GateError("작업 트리에 커밋 안 된 변경이 있다 — 게이트는 커밋된 트리를 잰다. 커밋하거나 되돌린다:\n"
                        + "\n".join(f"  {line}" for line in dirty.splitlines()[:10]))


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


def _argv(value, name, required, problems, allow_url=False):
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
                if not allow_url:
                    problems.append(f"{name}: {{url}} 은 프로파일에 ui 가 있어야 쓸 수 있다")
            elif ph not in PLACEHOLDERS:
                problems.append(f"{name}: 모르는 자리표시자 {ph}")


def _validate_rubric(root, ws, rub, problems, allow_url):
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
        _argv(r.get("probe"), f"{row}.probe", True, problems, allow_url)
        _argv(r.get("assert"), f"{row}.assert", False, problems, allow_url)
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
        _argv(ax.get("alive"), f"{name}.alive", False, problems, allow_url)
    return patches


def _validate_frozen_set(root, ws, profile):
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
    patches = _validate_rubric(root, ws, rub, problems, profile.ui is not None) if rub is not None else []
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
    if led["track"] != "formal":
        raise GateError("기준선은 정식 트랙에서만 잡는다")
    if led["frozen"] is None:
        raise GateError("동결 후에 기준선을 잡는다 — freeze 먼저")
    if led["baseline_sha"] is not None:
        # 다시 잡게 두면 변조 흔적(RED 블롭)과 감사 범위를 지울 수 있다(A2 리뷰 실측)
        raise GateError("기준선은 한 번만 잡는다 — 다시 시작하려면 새 slug 로")
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
    # RED «이전»의 수정 커밋은 위 범위 밖이다 — 트리아지 이후 RED 전까지 feat/fix 가 있으면 거부
    early = _git(root, "log", "--format=%H%x1f%s", f"{led['base_sha']}..{base}", check=True).stdout
    for line in early.splitlines():
        sha, subject = (line.split("\x1f") + [""])[:2]
        if _FEAT_FIX.match(subject):
            problems.append(f"{sha[:7]} {subject!r} — RED 커밋보다 먼저 들어간 수정이다")
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
    cause_id, frozen = _validate_frozen_set(root, ws, _profile(root))
    led.update(cause_id=cause_id, frozen=frozen, phase="P2")
    _save(ws, led)
    print(f"freeze OK — cause_id={cause_id} 파일 {len(frozen)}개")
    return EXIT_OK


def cmd_refreeze(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["frozen"] is None:
        raise GateError("아직 동결 전이다 — freeze")
    cause_id, frozen = _validate_frozen_set(root, ws, _profile(root))
    entry = {"kind": "refreeze", "reason": a.reason, "at": _now(),
             "from_cause": led["cause_id"], "to_cause": cause_id}
    if cause_id != led["cause_id"]:
        led["cause_changes"].append(entry)
    entry["changed"] = sorted(k for k in set(frozen) | set(led["frozen"]) if frozen.get(k) != led["frozen"].get(k))
    if a.refund_last:
        if not entry["changed"]:
            # 아무것도 안 바뀐 재동결로 cap 을 되돌리면 cap 이 무한이 된다(A2 리뷰 실측)
            raise GateError("환불은 측정을 고친 재동결에서만 — 동결 파일이 하나도 바뀌지 않았다")
        _refund_last(led, entry)
        if led["phase"] == "DEFERRED" and led["code_count"] < CAP:
            led["phase"] = "P5"
    led["history"].append(entry)
    led.update(cause_id=cause_id, frozen=frozen)
    _save(ws, led)
    print(f"refreeze OK — cause_id={cause_id}")
    return EXIT_OK


def _refund_last(led, entry):
    last = next((h for h in reversed(led["history"]) if h.get("kind") in ("run", "sweep")), None)
    if not last or last["attribution"] != "CODE" or last.get("refunded"):
        raise GateError("직전 판정이 환불 가능한 CODE 가 아니다")
    last["refunded"] = True
    led["code_count"] -= 1
    entry["refunded"] = last["n"]


def _run_repro(profile, root, ws, tree):
    argv = bp_profile.exec_argv(profile, tree, ["sh", str(ws / REPRO_SH), str(tree)])
    r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, errors="replace")
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
    if led["phase"] == "DEFERRED":
        raise GateError("DEFERRED — cap 에 도달한 버그는 트랙을 바꿔 계속하지 않는다")
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
    if led["phase"] == "DEFERRED":
        # cap 을 가벼운 트랙으로 빠져나가면 표지 없는 PR 이 된다(A2 리뷰 실측)
        raise GateError("DEFERRED — cap 에 도달한 버그는 트랙을 바꿔 계속하지 않는다")
    _change_track(led, "light", a.reason, a.kind)
    led["phase"] = "L1"
    _save(ws, led)
    print(f"to-light: light · L1 ({a.kind})")
    return EXIT_OK


class _CopyFailed(Exception):
    pass


def _copy_parent(profile):
    roots = profile.regress.allowed_roots if profile.regress else ()
    return str(roots[0]) if roots else None


@contextmanager
def _copy(root, profile, rev):
    """레포 «밖»에 rev 의 git worktree 사본 — 루트 쪽 스위트가 사본 테스트를 수집하지 않게. 늘 폐기."""
    try:
        parent = tempfile.mkdtemp(prefix="bp-copy-", dir=_copy_parent(profile))
    except OSError as e:
        raise _CopyFailed(f"사본 자리를 만들지 못했다: {e}")
    path = Path(parent) / "tree"
    try:
        r = _git(root, "worktree", "add", "-q", "--detach", str(path), rev)
        if r.returncode:
            raise _CopyFailed(f"사본을 만들지 못했다({rev}): {r.stderr.strip()}")
        yield path
    finally:
        _git(root, "worktree", "remove", "--force", str(path))
        _git(root, "worktree", "prune")
        shutil.rmtree(parent, ignore_errors=True)


def _exec_prefix(profile):
    if profile.exec_cmd:
        return list(profile.exec_cmd)
    return [sys.executable, str(HERE / "bp_exec_local.py")]


def _expand(argv, profile, tree, out, ws, url=None):
    res = []
    for tok in argv:
        if tok == "{exec}":
            res.extend(_exec_prefix(profile))
            continue
        res.append(tok.replace("{tree}", str(tree)).replace("{out}", str(out))
                   .replace("{repro}", str(ws / REPRO_SH)).replace("{url}", url or ""))
    return res


def _needs_url(row):
    return any("{url}" in tok for key in ("probe", "assert") for tok in row.get(key) or [])


def _run_row(profile, root, ws, row, tree, out):
    """{url} 이 든 행은 «그 트리»로 앱을 띄워 잰다 — 사본은 사본의 코드를 서빙해야 한다."""
    if not _needs_url(row):
        return _run_row_at(profile, root, ws, row, tree, out, None)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with bp_ui.serve(profile, tree, out.with_suffix(".serve.log")) as url:
            return _run_row_at(profile, root, ws, row, tree, out, url)
    except bp_ui.UiError as e:
        out.write_text(f"화면 서버: {e}\n")
        return False, None, {"probe": row["probe"], "ui_error": str(e), "out": str(out)}


def _run_row_at(profile, root, ws, row, tree, out, url):
    """(ran, passed, record). ran=False 는 «돌지 못했다»(125 · 실행 실패) — probe_ok=False."""
    probe = _expand(row["probe"], profile, tree, out, ws, url=url)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        try:
            pr = subprocess.run(probe, cwd=str(root), stdout=f, stderr=subprocess.STDOUT).returncode
        except OSError as e:
            f.write(str(e).encode())
            pr = ENV_FAILED
    rec = {"probe": probe, "probe_exit": pr, "out": str(out)}
    if pr == ENV_FAILED:
        return False, None, rec
    if "assert" not in row:
        return True, pr == 0, rec
    argv = _expand(row["assert"], profile, tree, out, ws, url=url)
    try:
        ar = subprocess.run(argv, cwd=str(root), capture_output=True).returncode
    except OSError:
        ar = ENV_FAILED
    rec.update(assert_argv=argv, assert_exit=ar)
    if ar == ENV_FAILED:
        return False, None, rec
    return True, ar == 0, rec


def _mutate(root, ws, led, copy_path, m):
    if "patch" in m:
        return _git(copy_path, "apply", str(ws / m["patch"])).returncode == 0
    ref = led["baseline_sha"] if m["checkout"] == BASELINE_REF else m["checkout"]
    return _git(copy_path, "checkout", "-q", "--detach", ref).returncode == 0


def _exec_hash(profile):
    h = hashlib.sha256(repr(profile.exec_cmd).encode())
    wrapper = Path(profile.exec_cmd[0]) if profile.exec_cmd else HERE / "bp_exec_local.py"
    if wrapper.is_file():
        h.update(wrapper.read_bytes())
    return h.hexdigest()


def _control_cached(profile, root, ws, led, rub, rundir):
    # 키: 측정을 바꾸는 것 전부 — HEAD · 동결 집합 전체(patch · repro.sh 포함) · @baseline 이 가리킬 sha · exec
    frozen = hashlib.sha256(json.dumps(led["frozen"], sort_keys=True).encode()).hexdigest()
    key = f"{_head(root)}:{frozen}:{led['baseline_sha']}:{_exec_hash(profile)}"
    path = ws / "control_cache.json"
    if path.is_file():
        c = json.loads(path.read_text())
        if c.get("key") == key:
            return True, c["control"], {"cached": True, "axes": c["axes"]}
    ran, control, info = _control(profile, root, ws, led, rub, rundir)
    if ran:
        path.write_text(json.dumps({"key": key, "control": control, "axes": info["axes"]}, ensure_ascii=False))
    return ran, control, info


def _control(profile, root, ws, led, rub, rundir):
    """축마다 사본 → 변이 → R-CAUSE → 폐기. 변이 후 R-CAUSE 가 빨개지고 alive 는 초록이어야 축 통과."""
    axes = []
    for i, ax in enumerate(rub["R-CONTROL"]["axes"]):
        try:
            with _copy(root, profile, "HEAD") as cp:
                if not _mutate(root, ws, led, cp, ax["mutate"]):
                    return False, None, {"axes": axes, "failed": ax["name"], "why": "변이를 적용하지 못했다"}
                ran, passed, rec = _run_row(profile, root, ws, rub["R-CAUSE"], cp, rundir / f"control_{i}.out")
                if not ran:
                    return False, None, {"axes": axes, "failed": ax["name"], "record": rec}
                alive = True
                if "alive" in ax:
                    a_ran, a_pass, _ = _run_row(profile, root, ws, {"probe": ax["alive"]}, cp, rundir / f"alive_{i}.out")
                    if not a_ran:
                        return False, None, {"axes": axes, "failed": ax["name"], "why": "alive 가 돌지 못했다"}
                    alive = a_pass
                axes.append({"name": ax["name"], "cause_red": not passed, "alive": alive})
        except _CopyFailed as e:
            return False, None, {"axes": axes, "failed": ax["name"], "why": str(e)}
    return True, all(a["cause_red"] and a["alive"] for a in axes), {"axes": axes}


def _regress(profile, root, ws, led, rundir):
    try:
        with _copy(root, profile, led["baseline_sha"]) as base:
            code = bp_regress.run(base, root, rundir / "regress", root=root,
                                  base_cache=ws / "baseline_cache" / led["baseline_sha"])
    except _CopyFailed as e:
        return False, None, {"why": str(e)}
    rec = {"exit": code, "out": str(rundir / "regress")}
    if code not in (0, 1):
        return False, None, rec
    return True, code == 0, rec


_NEXT_PHASE = {"PASS": "P5b", "CODE": "P3", "ANCHOR": "P2", "VOID": "P5", "ENV": "P5"}


def _judge(ws, led, head, args, rows, kind):
    v = verdict(**args)
    n = len([h for h in led["history"] if h.get("kind") in ("run", "sweep")]) + 1
    led["code_count"] += v.cap_delta
    entry = {"kind": kind, "n": n, "at": _now(), "head": head, "cause_id": led["cause_id"],
             "attribution": v.attribution.value, "cap_delta": v.cap_delta, "reason": v.reason, "args": args}
    led["history"].append(entry)
    (ws / f"verdict_{n}.json").write_text(
        json.dumps({**entry, "rows": rows}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    code = EXIT_OK if v.attribution is Attribution.PASS else EXIT_JUDGED
    if led["code_count"] >= CAP:
        led["phase"] = "DEFERRED"
        code = EXIT_CAP
    else:
        led["phase"] = _NEXT_PHASE[v.attribution.value]
    _save(ws, led)
    print(f"ATTRIBUTION={v.attribution.value} — {v.reason} · loop {led['code_count']}/{CAP} · phase {led['phase']}")
    return code


def cmd_run(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "formal" or led["frozen"] is None or led["baseline_sha"] is None:
        raise GateError("run 은 정식 트랙 · 동결 · 기준선 이후에")
    if led["phase"] == "DEFERRED" or led["code_count"] >= CAP:
        raise GateError(f"cap 도달 ({led['code_count']}/{CAP}) — DEFERRED", EXIT_CAP)
    profile = _profile(root)
    if profile.regress is None:
        raise GateError("regress 섹션이 없다 — 정식 트랙은 스위트가 필요하다")
    _require_clean(root)
    _check_tamper(root, ws, led)
    _audit_commits(root, led)
    rub = json.loads((ws / RUBRIC).read_text(encoding="utf-8"))
    head = _head(root)
    n = len([h for h in led["history"] if h.get("kind") in ("run", "sweep")]) + 1
    rundir = ws / f"run_{n}"
    rundir.mkdir(exist_ok=True)
    args = {"probe_ok": True, "control": None, "cause": None, "symptom": None, "regress": None}
    rows = {}
    steps = [
        ("R-CONTROL", "control", lambda: _control_cached(profile, root, ws, led, rub, rundir)),
        ("R-CAUSE", "cause", lambda: _run_row(profile, root, ws, rub["R-CAUSE"], root, rundir / "cause.out")),
        ("R-SYMPTOM", "symptom", lambda: _run_row(profile, root, ws, rub["R-SYMPTOM"], root, rundir / "symptom.out")),
        ("R-REGRESS", "regress", lambda: _regress(profile, root, ws, led, rundir)),
    ]
    for name, key, step in steps:
        ran, passed, rec = step()
        rows[name] = rec
        if not ran:
            args["probe_ok"] = False
            break
        args[key] = passed
        if not passed:
            break
    code = _judge(ws, led, head, args, rows, "run")
    if args["regress"] is False:
        print(f"  새 빨강: {rundir / 'regress' / 'new_red.txt'} — 원인과 무관해 보이면 SPEC 으로 GATE 1 재진입(사용자 판단)")
    return code


def cmd_record_sweep(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "formal" or led["frozen"] is None:
        raise GateError("record-sweep 은 정식 트랙 · 동결 이후에")
    ev = (ws / a.regression).resolve()
    if ws.resolve() not in ev.parents or not ev.is_file():
        raise GateError(f"근거 파일은 작업공간 안에 있어야 한다: {a.regression}")
    if led["phase"] == "DEFERRED" or led["code_count"] >= CAP:
        raise GateError(f"cap 도달 ({led['code_count']}/{CAP}) — DEFERRED", EXIT_CAP)
    # P5b 는 cap 을 직접 세지 않는다 — 확정 회귀를 R-REGRESS 실패로 표현해 같은 진리표에 넣는다
    args = {"probe_ok": True, "control": True, "cause": True, "symptom": True, "regress": False}
    return _judge(ws, led, _head(root), args, {"R-REGRESS": {"sweep_evidence": str(ev)}}, "sweep")


def cmd_light_verify(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "light":
        raise GateError("가벼운 트랙이 아니다")
    profile = _profile(root)
    head, base = _head(root), led["base_sha"]
    if head == base:
        raise GateError("수정 커밋이 없다 — 가벼운 트랙도 «커밋된» 트리를 잰다")
    _require_clean(root)
    vdir = ws / f"light_{len(led['light_verifications']) + 1}"
    vdir.mkdir(exist_ok=True)  # 중단된 지난 시도의 잔해 — 이번 결과로 덮어쓴다
    observed = _repro_fields(ws).get("observed", "")
    rec = {"head": head, "at": _now(), "repro": None, "regress": None}
    if (ws / REPRO_SH).is_file() and observed:
        if led["triage"]["deterministic"]:
            try:
                with _copy(root, profile, base) as cp:
                    b_exit, b_out = _run_repro(profile, root, ws, cp)
            except _CopyFailed as e:
                b_exit, b_out = ENV_FAILED, str(e)
            a_exit, a_out = _run_repro(profile, root, ws, root)
            (vdir / "repro_before.out").write_text(b_out)
            (vdir / "repro_after.out").write_text(a_out)
            rec["repro"] = {"mode": "deterministic", "before_exit": b_exit, "before_observed": observed in b_out,
                            "after_exit": a_exit, "after_observed": observed in a_out}
        else:
            exits, hits = [], 0
            for i in range(LIGHT_REPRO_RUNS):
                code, out = _run_repro(profile, root, ws, root)
                (vdir / f"repro_{i}.out").write_text(out)
                exits.append(code)
                hits += observed in out
            rec["repro"] = {"mode": "repeated", "runs": LIGHT_REPRO_RUNS, "observed_hits": hits, "exits": exits}
    if profile.regress is not None:
        try:
            with _copy(root, profile, base) as cp:
                code = bp_regress.run(cp, root, vdir / "regress", root=root,
                                      base_cache=ws / "baseline_cache" / base)
        except _CopyFailed:
            code = bp_regress.EXIT_VOID
        red_file = vdir / "regress" / "new_red.txt"
        rec["regress"] = {"exit": code,
                          "new_red": red_file.read_text().split() if code == 1 and red_file.is_file() else []}
    led["light_verifications"].append(rec)
    led["phase"] = "L-verified"
    _save(ws, led)
    print(f"light-verify — repro={rec['repro'] and rec['repro']['mode']} regress={rec['regress'] and rec['regress']['exit']}")
    return EXIT_OK


def _light_labels(led):
    last = led["light_verifications"][-1] if led["light_verifications"] else None
    repro = last and last["repro"]
    clean = bool(
        repro and repro["mode"] == "deterministic"
        and repro["before_observed"] and repro["before_exit"] != ENV_FAILED
        and not repro["after_observed"] and repro["after_exit"] in (0, repro["before_exit"])
    )  # 수정 후 재현이 «죽어서» observed 가 안 나온 것은 고쳐진 것이 아니다(A2 리뷰 실측)
    unstable = any(c["to"] == "light" and c["kind"] in ("cannot-measure", "unstable") for c in led["track_changes"])
    labels = []
    if not clean or unstable:
        labels.append(LABEL_NO_DETERMINISM)
    reg = last and last["regress"]
    if not reg or reg["exit"] not in (0, 1):
        labels.append(LABEL_NO_REGRESS)
    return labels


def _changed_files(root, base):
    return _git(root, "diff", "--name-only", f"{base}..HEAD", check=True).stdout.split()


def cmd_light_report(root, a):
    ws = _ws(root, a.slug)
    led = _load(ws)
    if led["track"] != "light":
        raise GateError("가벼운 트랙이 아니다")
    last = led["light_verifications"][-1] if led["light_verifications"] else None
    if last and last["head"] != _head(root):
        raise GateError("light-verify 이후 커밋이 더 있다 — 검증이 낡았다. light-verify 를 다시")
    labels = _light_labels(led)
    changed = _changed_files(root, led["base_sha"])
    cause = json.loads((ws / LIGHT_CAUSE).read_text()) if (ws / LIGHT_CAUSE).is_file() else {}
    # 🔴 PR 본문은 명령 출력 원문을 읽지 않는다 — 판정·종료코드·이름·표지·파일 목록만
    body = [f"## 버그 수정 — {led['slug']}", "", "트랙: 가벼운", f"표지: {', '.join(labels) or '없음'}"]
    if cause.get("file"):
        body.append(f"원인: `{cause['file']}:{cause.get('line', '?')}` — {cause.get('summary', '')}")
    if last and last["repro"]:
        r = last["repro"]
        if r["mode"] == "deterministic":
            body.append(f"재현: 수정 전 재현={r['before_observed']}(exit {r['before_exit']}) · "
                        f"수정 후 재현={r['after_observed']}(exit {r['after_exit']})")
        else:
            body.append(f"재현: {r['runs']}회 중 {r['observed_hits']}회 관측 (비결정)")
    if last and last["regress"]:
        g = last["regress"]
        body.append(f"회귀: exit {g['exit']}" + (f" · 새 빨강 {', '.join(g['new_red'])}" if g["new_red"] else ""))
    body += ["", "변경 파일:"] + [f"- `{f}`" for f in changed]
    (ws / PR_BODY).write_text("\n".join(body) + "\n", encoding="utf-8")
    report = body + ["", "---", "로컬 전용 — 원문 발췌"]
    vdir = ws / f"light_{len(led['light_verifications'])}"
    for f in sorted(vdir.glob("*.out")) if last else []:
        report += ["", f"### {f.name}", "```", f.read_text()[-2000:], "```"]
    (ws / LIGHT_REPORT).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"light-report — 표지: {', '.join(labels) or '없음'} · {ws / LIGHT_REPORT}")
    return EXIT_OK


def _formal_pr_body(root, ws, led):
    rc = json.loads((ws / ROOT_CAUSE).read_text()) if (ws / ROOT_CAUSE).is_file() else {}
    judged = [h for h in led["history"] if h.get("kind") in ("run", "sweep")]
    changed = _changed_files(root, led["baseline_sha"]) if led["baseline_sha"] else []
    off = sorted(set(changed) - set(rc.get("fix_scope", [])) - set(led["red_files"] or {}))
    lines = [f"## 버그 수정 — {led['slug']}", "", "트랙: 정식",
             f"원인: `{rc.get('file')}:{rc.get('line')}` (cause_id {led['cause_id']})",
             f"판정: {' → '.join(h['attribution'] for h in judged) or '없음'} · 루프 {led['code_count']}/{CAP}",
             f"원인 교체: {len(led['cause_changes'])}",
             f"RED 커밋: {(led['red_commit'] or '')[:7]}",
             f"카드 밖 변경 파일: {', '.join(off) or '0'}"]
    return "\n".join(lines) + "\n"


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
    if a.pr_body:
        if led["track"] != "formal":
            raise GateError("가벼운 트랙의 PR 본문은 light-report 가 쓴다")
        (ws / PR_BODY).write_text(_formal_pr_body(root, ws, led), encoding="utf-8")
        print(f"pr_body: {ws / PR_BODY}")
    last2 = [h["attribution"] for h in led["history"] if h.get("kind") == "run"][-2:]
    if len(last2) == 2 and set(last2) <= {"VOID", "ENV"}:
        print("  제안: VOID/ENV 연속 2회 — to-light --kind unstable 이관을 사용자에게")
    return EXIT_OK


def _parser():
    p = argparse.ArgumentParser(prog="bp_gate.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("slug")
    s = sub.add_parser("status")
    s.add_argument("slug")
    s.add_argument("--close", choices=sorted(_CLOSED))
    s.add_argument("--pr-body", action="store_true")
    s = sub.add_parser("light-verify")
    s.add_argument("slug")
    s = sub.add_parser("light-report")
    s.add_argument("slug")
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
    s = sub.add_parser("run")
    s.add_argument("slug")
    s = sub.add_parser("record-sweep")
    s.add_argument("slug")
    s.add_argument("--regression", required=True)
    return p


COMMANDS = {"init": cmd_init, "status": cmd_status, "triage": cmd_triage,
            "promote": cmd_promote, "to-light": cmd_to_light,
            "freeze": cmd_freeze, "refreeze": cmd_refreeze, "baseline": cmd_baseline,
            "run": cmd_run, "record-sweep": cmd_record_sweep,
            "light-verify": cmd_light_verify, "light-report": cmd_light_report}


def _selftest() -> int:
    """설치처용 — 정식 트랙 한 바퀴(CODE→PASS) · 변조 · 가벼운 트랙 표지를 임시 레포에서 돌린다."""
    import bp_fixture as fx
    failures = []

    def expect(name, got, want):
        if got != want:
            failures.append(f"{name}: 기대 {want!r}, 실제 {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        root, ws = fx.formal_ready(Path(tmp) / "a")
        expect("freeze", fx.gate(root, "freeze", "b1"), 0)
        red = fx.red_commit(root)
        expect("baseline", fx.gate(root, "baseline", "b1", "--red", "tests/red.sh"), 0)
        expect("수정 전 run = CODE", fx.gate(root, "run", "b1"), 1)
        fx.fix_commit(root, red)
        expect("수정 후 run = PASS", fx.gate(root, "run", "b1"), 0)
        (ws / "rubric.json").write_text((ws / "rubric.json").read_text() + " ")
        expect("변조 = 2", fx.gate(root, "run", "b1"), 2)
    with tempfile.TemporaryDirectory() as tmp:
        root, ws = fx.light_ready(Path(tmp) / "b", overrides={"regress": None})
        (root / "value.txt").write_text("good\n")
        fx.git(root, "commit", "-q", "-am", "fix: value")
        expect("light-verify", fx.gate(root, "light-verify", "b1"), 0)
        expect("표지", _light_labels(fx.ledger(root, "b1")), [LABEL_NO_REGRESS])
    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("selftest OK — 정식 한 바퀴(CODE→PASS) · 변조 · 가벼운 트랙 표지")
    return 0


def main(argv) -> int:
    if argv == ["--selftest"]:
        return _selftest()
    try:
        a = _parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_CONFIG if e.code else EXIT_OK
    try:
        return COMMANDS[a.cmd](_root(), a)
    except GateError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except Exception:
        # 마지막 방어선 — 예상 못 한 예외가 exit 1(«판정이 PASS 아님»)로 읽히지 않게
        import traceback
        traceback.print_exc()
        print("bp_gate: 예상 못 한 예외", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
