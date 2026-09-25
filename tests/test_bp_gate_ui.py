"""bp_gate — {url} 행 · 화면이 필요한 재현."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import (REPRO_URL_SH, RUBRIC_OK, UI_OVERRIDES, fix_commit, formal_ready,  # noqa: E402
                        gate, red_commit)

URL_RUBRIC = copy.deepcopy(RUBRIC_OK)
URL_RUBRIC["R-SYMPTOM"]["probe"] = ["{exec}", "{tree}", "--", "sh", "{repro}", "{tree}", "{url}"]
URL_RUBRIC["R-CAUSE"] = {"probe": ["{exec}", "{tree}", "--", "sh", "{repro}", "{tree}", "{url}"],
                         "assert": ["grep", "-q", "good", "{out}"]}
# 이 R-CAUSE 는 서빙된 value.txt 만 본다 — broken 파일 변이로는 빨개질 수 없다(그 축은 VOID 가 옳다)
URL_RUBRIC["R-CONTROL"]["axes"] = [RUBRIC_OK["R-CONTROL"]["axes"][0]]


def _ready(tmp_path, overrides=UI_OVERRIDES):
    root, ws = formal_ready(tmp_path, rubric=URL_RUBRIC, overrides=overrides)
    (ws / "repro.sh").write_text(REPRO_URL_SH)
    return root, ws


def test_url_rows_freeze_when_ui_exists(tmp_path):
    root, ws = _ready(tmp_path)
    assert gate(root, "freeze", "b1") == 0


def test_url_rows_are_refused_without_ui(tmp_path, capsys):
    root, ws = _ready(tmp_path, overrides=None)
    assert gate(root, "freeze", "b1") == 2
    assert "ui" in capsys.readouterr().err


def test_url_rows_pass_end_to_end(tmp_path):
    root, ws = _ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0


def test_url_row_serves_the_measured_tree(tmp_path):
    # R-CONTROL 의 @baseline 축은 «사본»을 서빙해야 빨개진다 — 원본을 서빙하면 초록(VOID)
    root, ws = _ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    gate(root, "run", "b1")
    axes = json.loads((ws / "verdict_1.json").read_text())["rows"]["R-CONTROL"]["axes"]
    assert axes[0]["cause_red"] is True


import subprocess  # noqa: E402

import bp_gate  # noqa: E402
import bp_fixture  # noqa: E402
from bp_fixture import git, ledger, make_gate_host  # noqa: E402


def _ui_repro(ws, url=""):
    (ws / "repro.md").write_text(
        f"steps: 화면\nobserved: bad\nwhere: 로컬\nneeds_ui: yes\nurl: {url}\nexpected_after: good\n")
    (ws / "repro.sh").write_text(REPRO_URL_SH)


def test_triage_serves_a_ui_repro(tmp_path):
    root = make_gate_host(tmp_path, UI_OVERRIDES)
    gate(root, "init", "b1")
    _ui_repro(root / ".bugfix-pipeline" / "b1")
    gate(root, "triage", "b1", "--repro-confirmed")
    assert ledger(root, "b1")["triage"]["deterministic"] is True


def _user_server(root):
    """사용자 개발 서버 흉내 — 작업 트리를 서빙한다. (프로세스, 포트)"""
    server = subprocess.Popen([sys.executable, "-u", "-c",
                               "import functools,http.server,socketserver,sys\n"
                               "h=functools.partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])\n"
                               "s=socketserver.TCPServer(('127.0.0.1',0),h)\n"
                               "print(s.server_address[1],flush=True)\n"
                               "s.serve_forever()", str(root)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return server, server.stdout.readline().strip()


def test_triage_without_ui_is_not_deterministic(tmp_path):
    # 사용자 서버로 재현이 «매번» 되어도 기준선 사본은 잴 수 없다 — 결정적으로 치지 않는다
    root = make_gate_host(tmp_path)
    server, port = _user_server(root)
    try:
        gate(root, "init", "b1")
        _ui_repro(root / ".bugfix-pipeline" / "b1", url=f"http://127.0.0.1:{port}")
        gate(root, "triage", "b1", "--repro-confirmed")
        t = ledger(root, "b1")["triage"]
        assert all(r["observed"] for r in t["runs"]) and t["deterministic"] is False
    finally:
        server.terminate()
        server.wait()


def test_light_with_ui_measures_before_and_after(tmp_path):
    root = make_gate_host(tmp_path, UI_OVERRIDES)
    gate(root, "init", "b1")
    _ui_repro(root / ".bugfix-pipeline" / "b1")
    gate(root, "triage", "b1", "--repro-confirmed", "--light")
    (root / "value.txt").write_text("good\n")
    git(root, "commit", "-q", "-am", "fix: value")
    gate(root, "light-verify", "b1")
    rec = ledger(root, "b1")["light_verifications"][-1]["repro"]
    assert rec["mode"] == "deterministic" and rec["before_observed"] and not rec["after_observed"]


def test_light_without_ui_measures_after_only_and_labels(tmp_path):
    root = make_gate_host(tmp_path)
    server = subprocess.Popen([sys.executable, "-u", "-c",
                               "import functools,http.server,socketserver,sys\n"
                               "h=functools.partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])\n"
                               "s=socketserver.TCPServer(('127.0.0.1',0),h)\n"
                               "print(s.server_address[1],flush=True)\n"
                               "s.serve_forever()", str(root)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        port = server.stdout.readline().strip()
        gate(root, "init", "b1")
        ws = root / ".bugfix-pipeline" / "b1"
        _ui_repro(ws, url=f"http://127.0.0.1:{port}")
        gate(root, "triage", "b1", "--repro-confirmed")
        assert all(r["observed"] for r in ledger(root, "b1")["triage"]["runs"])  # 트리아지가 버그를 봤다
        (root / "value.txt").write_text("good\n")
        git(root, "commit", "-q", "-am", "fix: value")
        assert gate(root, "light-verify", "b1") == 0
        rec = ledger(root, "b1")["light_verifications"][-1]["repro"]
        assert rec["mode"] == "after-only" and not rec["after_observed"]
        labels = bp_gate._light_labels(ledger(root, "b1"))
        assert bp_gate.LABEL_NO_BASELINE_REPRO in labels and bp_gate.LABEL_NO_DETERMINISM not in labels
    finally:
        server.terminate()
        server.wait()


def test_control_cache_is_invalidated_by_a_serve_wrapper_change(tmp_path):
    # 래퍼가 git 에 안 보이게 바뀌면(무시 · 레포 밖) 같은 HEAD 에서 캐시가 옛 control=True 를 준다 — 거짓 PASS
    root, ws = _ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
    git(root, "update-index", "--skip-worktree", "bin/serve.sh")
    # 새 래퍼는 주어진 트리를 무시하고 원본만 서빙한다 — 사본 측정이 무의미해져 VOID 여야 한다
    (root / "bin" / "serve.sh").write_text(
        bp_fixture.SERVE_SH.replace('"$1"', f'"{root}"'))
    assert gate(root, "run", "b1") != 0


def test_after_only_keeps_the_determinism_label_for_a_flaky_triage():
    # 트리아지 3회가 [관측, 미관측, 관측] 이면 수정 후 한 번 안 보인 것은 증거가 아니다
    led = {"track_changes": [],
           "triage": {"runs": [{"exit": 0, "observed": True}, {"exit": 0, "observed": False},
                               {"exit": 0, "observed": True}]},
           "light_verifications": [{"repro": {"mode": "after-only", "after_exit": 0, "after_observed": False},
                                    "regress": {"exit": 0, "new_red": []}}]}
    labels = bp_gate._light_labels(led)
    assert bp_gate.LABEL_NO_DETERMINISM in labels and bp_gate.LABEL_NO_BASELINE_REPRO in labels
    led["triage"]["runs"][1]["observed"] = True
    assert bp_gate.LABEL_NO_DETERMINISM not in bp_gate._light_labels(led)
