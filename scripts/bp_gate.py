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
    return p


COMMANDS = {"init": cmd_init, "status": cmd_status}


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
