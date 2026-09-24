"""bp_gate — baseline · 커밋 감사 · 변조 검사."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_gate  # noqa: E402
from bp_fixture import fix_commit, formal_ready, gate, git, ledger, red_commit  # noqa: E402


def _frozen(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    return root, ws


def test_baseline_is_the_parent_of_the_first_red_commit(tmp_path):
    root, _ = _frozen(tmp_path)
    before = git(root, "rev-parse", "HEAD")
    red = red_commit(root)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 0
    led = ledger(root, "b1")
    assert (led["baseline_sha"], led["red_commit"]) == (before, red)
    assert led["red_files"]["tests/red.sh"] == git(root, "rev-parse", "HEAD:tests/red.sh")


def test_baseline_without_a_red_commit_is_refused(tmp_path):
    root, _ = _frozen(tmp_path)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 2


def test_baseline_before_freeze_is_refused(tmp_path):
    root, _ = formal_ready(tmp_path)
    red_commit(root)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 2


def _based(tmp_path):
    root, ws = _frozen(tmp_path)
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    return root, ws, red


def test_audit_accepts_a_fix_carrying_the_red_sha(tmp_path):
    root, ws, red = _based(tmp_path)
    fix_commit(root, red)
    bp_gate._audit_commits(root, ledger(root, "b1"))


def test_audit_rejects_a_fix_without_red(tmp_path):
    root, ws, red = _based(tmp_path)
    fix_commit(root, red, body="본문만")
    with pytest.raises(bp_gate.GateError):
        bp_gate._audit_commits(root, ledger(root, "b1"))


def test_audit_rejects_red_pointing_outside_the_range(tmp_path):
    root, ws, red = _based(tmp_path)
    outside = ledger(root, "b1")["baseline_sha"]
    fix_commit(root, red, body=f"RED: {outside}")
    with pytest.raises(bp_gate.GateError):
        bp_gate._audit_commits(root, ledger(root, "b1"))


def test_audit_checks_every_fix_commit(tmp_path):
    root, ws, red = _based(tmp_path)
    fix_commit(root, red)
    fix_commit(root, red, body="두 번째엔 RED 없음", subject="fix: 두 번째")
    with pytest.raises(bp_gate.GateError) as e:
        bp_gate._audit_commits(root, ledger(root, "b1"))
    assert "두 번째" in str(e.value)


def test_audit_ignores_non_feat_fix_commits(tmp_path):
    root, ws, red = _based(tmp_path)
    git(root, "commit", "-q", "--allow-empty", "-m", "docs: 메모")
    bp_gate._audit_commits(root, ledger(root, "b1"))


def test_tamper_detects_an_edited_rubric(tmp_path):
    root, ws, red = _based(tmp_path)
    (ws / "rubric.json").write_text((ws / "rubric.json").read_text() + " ")
    with pytest.raises(bp_gate.GateError):
        bp_gate._check_tamper(root, ws, ledger(root, "b1"))


def test_tamper_detects_edited_repro_sh(tmp_path):
    root, ws, red = _based(tmp_path)
    (ws / "repro.sh").write_text("#!/bin/sh\necho good\n")
    with pytest.raises(bp_gate.GateError):
        bp_gate._check_tamper(root, ws, ledger(root, "b1"))


def test_tamper_detects_an_edited_red_test(tmp_path):
    root, ws, red = _based(tmp_path)
    (Path(root) / "tests" / "red.sh").write_text("true\n")
    git(root, "commit", "-q", "-am", "test: 슬쩍")
    with pytest.raises(bp_gate.GateError):
        bp_gate._check_tamper(root, ws, ledger(root, "b1"))
