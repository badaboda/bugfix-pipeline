"""bp_gate — 가벼운 트랙 검증 · 보고 · PR 본문 위생."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_gate  # noqa: E402
from bp_fixture import (fix_commit, formal_ready, gate, git, ledger, light_ready,  # noqa: E402
                        red_commit)


def _fix(root):
    (Path(root) / "value.txt").write_text("good\n")
    git(root, "commit", "-q", "-am", "fix: value")


def test_verify_needs_a_fix_commit(tmp_path):
    root, _ = light_ready(tmp_path)
    assert gate(root, "light-verify", "b1") == 2


def test_deterministic_repro_before_and_after(tmp_path):
    root, _ = light_ready(tmp_path)
    _fix(root)
    assert gate(root, "light-verify", "b1") == 0
    rec = ledger(root, "b1")["light_verifications"][-1]
    assert rec["repro"]["before_observed"] and not rec["repro"]["after_observed"]
    assert rec["regress"]["exit"] == 0


def test_fully_verified_has_no_labels(tmp_path):
    root, _ = light_ready(tmp_path)
    _fix(root)
    gate(root, "light-verify", "b1")
    assert bp_gate._light_labels(ledger(root, "b1")) == []


def test_no_regress_section_is_labelled(tmp_path):
    root, _ = light_ready(tmp_path, overrides={"regress": None})
    _fix(root)
    gate(root, "light-verify", "b1")
    assert bp_gate.LABEL_NO_REGRESS in bp_gate._light_labels(ledger(root, "b1"))


def test_no_repro_is_labelled_nondeterministic(tmp_path):
    root, _ = light_ready(tmp_path, repro=None)
    _fix(root)
    gate(root, "light-verify", "b1")
    assert bp_gate.LABEL_NO_DETERMINISM in bp_gate._light_labels(ledger(root, "b1"))


def test_unverified_axes_are_labelled(tmp_path):
    root, _ = light_ready(tmp_path)
    labels = bp_gate._light_labels(ledger(root, "b1"))
    assert bp_gate.LABEL_NO_DETERMINISM in labels and bp_gate.LABEL_NO_REGRESS in labels


def test_unstable_to_light_is_labelled_even_if_repro_is_clean(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "to-light", "b1", "--kind", "unstable", "--reason", "VOID 2회")
    _fix(root)
    gate(root, "light-verify", "b1")
    assert bp_gate.LABEL_NO_DETERMINISM in bp_gate._light_labels(ledger(root, "b1"))


def test_size_to_light_is_not_labelled(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "to-light", "b1", "--kind", "size", "--reason", "한 파일")
    _fix(root)
    gate(root, "light-verify", "b1")
    assert bp_gate._light_labels(ledger(root, "b1")) == []


def test_report_is_stale_after_a_new_commit(tmp_path):
    root, _ = light_ready(tmp_path)
    _fix(root)
    gate(root, "light-verify", "b1")
    git(root, "commit", "-q", "--allow-empty", "-m", "chore: 더")
    assert gate(root, "light-report", "b1") == 2


def test_pr_body_never_contains_command_output(tmp_path):
    leak = '#!/bin/sh\necho "SECRET-TOKEN-bp42"\ncat "$1/value.txt"\n'
    root, ws = light_ready(tmp_path, repro=leak)
    _fix(root)
    gate(root, "light-verify", "b1")
    assert gate(root, "light-report", "b1") == 0
    assert "SECRET-TOKEN-bp42" not in (ws / "pr_body.md").read_text()
    assert "SECRET-TOKEN-bp42" in (ws / "light_report.md").read_text()


def test_formal_pr_body_has_no_output(tmp_path):
    root, ws = formal_ready(tmp_path)
    (ws / "repro.sh").write_text('#!/bin/sh\necho "SECRET-TOKEN-bp42"\ncat "$1/value.txt"\n')
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    gate(root, "run", "b1")
    assert gate(root, "status", "b1", "--pr-body") == 0
    body = (ws / "pr_body.md").read_text()
    assert "SECRET-TOKEN-bp42" not in body and "PASS" in body
