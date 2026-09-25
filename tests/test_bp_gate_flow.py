"""bp_gate — 트랙이 막다른 길 없이 끝까지 가는지(플랜 B 리뷰 실측: ANCHOR · 승급 · P5b 서빙)."""
import copy
import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from bp_fixture import (RUBRIC_OK, UI_OVERRIDES, fix_commit, formal_ready, gate, git,  # noqa: E402
                        ledger, light_ready, red_commit)


def _anchored(tmp_path):
    rub = copy.deepcopy(RUBRIC_OK)
    rub["R-SYMPTOM"]["assert"] = ["grep", "-q", "nope", "{out}"]
    root, ws = formal_ready(tmp_path, rubric=rub)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1 and ledger(root, "b1")["phase"] == "P2"
    return root, ws, red


def _rewrite_red(root):
    (root / "tests" / "red.sh").write_text("sh check.sh  # 다시 쓴 RED\n")
    git(root, "commit", "-q", "-am", "test: RED 재작성")


def test_anchor_lets_the_red_test_be_rewritten_and_rebaselined(tmp_path):
    root, ws, red = _anchored(tmp_path)
    before = ledger(root, "b1")["baseline_sha"]
    _rewrite_red(root)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 0
    led = ledger(root, "b1")
    assert led["baseline_sha"] == before and led["phase"] == "P3"
    assert led["red_files"]["tests/red.sh"] == git(root, "rev-parse", "HEAD:tests/red.sh")
    assert any(h.get("kind") == "rebaseline" for h in led["history"])
    assert gate(root, "run", "b1") != 2          # 변조로 막히지 않는다


def test_cause_change_reopens_p2_for_a_new_red(tmp_path):
    root, ws, red = _anchored(tmp_path)
    for name in ("rubric.json", "root_cause.json"):
        data = json.loads((ws / name).read_text())
        data["cause_id"] = "value-02"
        (ws / name).write_text(json.dumps(data, ensure_ascii=False))
    assert gate(root, "refreeze", "b1", "--reason", "원인 교체") == 0
    assert ledger(root, "b1")["phase"] == "P2"
    _rewrite_red(root)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 0


def test_rebaseline_is_refused_after_a_pass(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 2


def test_promote_requires_the_light_fix_to_be_reverted(tmp_path, capsys):
    root, ws = light_ready(tmp_path)
    (root / "value.txt").write_text("good\n")
    git(root, "commit", "-q", "-am", "fix: value")
    assert gate(root, "promote", "b1", "--reason", "첫 가설 실패") == 2
    assert "revert" in capsys.readouterr().err
    git(root, "revert", "--no-edit", "HEAD")
    assert gate(root, "promote", "b1", "--reason", "첫 가설 실패") == 0
    led = ledger(root, "b1")
    assert led["base_sha"] == git(root, "rev-parse", "HEAD")   # 가벼운 커밋은 감사 범위 밖으로


def _serve(root, side):
    return subprocess.Popen([sys.executable, str(SCRIPTS / "bp_gate.py"), "serve", "b1", "--side", side],
                            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _url(proc):
    for line in proc.stdout:
        if line.startswith("BP_URL="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("BP_URL 이 나오지 않았다")


@pytest.mark.parametrize("side,value", [("baseline", b"bad\n"), ("after", b"good\n")])
def test_serve_serves_each_side_and_cleans_up(tmp_path, side, value):
    root, ws = formal_ready(tmp_path, overrides=UI_OVERRIDES)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    proc = _serve(root, side)
    try:
        url = _url(proc)
        assert urllib.request.urlopen(url + "/value.txt", timeout=5).read() == value
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=2)
    assert len(git(root, "worktree", "list").splitlines()) == 1   # 사본이 남지 않는다
    assert not git(root, "status", "--porcelain")


def test_serve_without_ui_is_exit_2(tmp_path, capsys):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    assert gate(root, "serve", "b1", "--side", "after") == 2
    assert "ui 가 없다" in capsys.readouterr().err   # argparse 거부가 아니라 ui 부재로
