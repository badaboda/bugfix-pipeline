"""bp_gate — R-CONTROL 캐시 · 기준선 캐시 · record-sweep."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_regress  # noqa: E402
from bp_fixture import (fix_commit, formal_ready, gate, git, ledger, make_host,  # noqa: E402
                        red_commit, write_profile)


def _at_p3(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    return root, ws, red


def _verdict(ws, n):
    return json.loads((ws / f"verdict_{n}.json").read_text())


def test_control_is_reused_on_the_same_head(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    gate(root, "run", "b1")
    gate(root, "run", "b1")
    assert _verdict(ws, 2)["rows"]["R-CONTROL"].get("cached") is True


def test_control_is_remeasured_after_a_new_commit(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    gate(root, "run", "b1")
    fix_commit(root, red)
    gate(root, "run", "b1")
    assert not _verdict(ws, 2)["rows"]["R-CONTROL"].get("cached")


def test_baseline_side_is_reused_across_runs(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    gate(root, "run", "b1")
    fix_commit(root, red, subject="fix: 한 번 더", value="good")
    gate(root, "run", "b1")
    meta = (ws / "run_2" / "regress" / "META").read_text()
    assert "base_cached=1" in meta


def test_baseline_cache_is_invalid_when_regress_changes(tmp_path):
    root, base = make_host(tmp_path, ["t::a"], ["t::a"])
    cache = tmp_path / "cache"
    assert bp_regress.run(base, root, tmp_path / "o1", root=root, base_cache=cache) == 0
    write_profile(root, {"regress.not_fully": "PARTIALLY"})
    bp_regress.run(base, root, tmp_path / "o2", root=root, base_cache=cache)
    assert "base_cached=1" not in (tmp_path / "o2" / "META").read_text()


def test_record_sweep_counts_a_code(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    gate(root, "run", "b1")
    (ws / "gate_round1.md").write_text("회귀 확정")
    assert gate(root, "record-sweep", "b1", "--regression", "gate_round1.md") == 1
    led = ledger(root, "b1")
    assert led["history"][-1]["kind"] == "sweep" and led["code_count"] == 1


def test_record_sweep_evidence_must_be_in_the_workspace(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert gate(root, "record-sweep", "b1", "--regression", "../../value.txt") == 2


def _passed(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
    return root, ws


def _pr_body(root, ws):
    gate(root, "status", "b1", "--pr-body")
    return (ws / "pr_body.md").read_text()


def test_pr_body_says_when_p5b_was_not_recorded(tmp_path):
    # 종단 2회차: 정식 PR 본문에 P5b 결과가 없었다 — 기록이 없으면 «없다»가 드러나야 한다
    root, ws = _passed(tmp_path)
    assert "P5b: 기록 없음" in _pr_body(root, ws)


def test_clean_sweep_is_recorded_without_a_verdict(tmp_path):
    root, ws = _passed(tmp_path)
    (ws / "gate_round1.md").write_text("후보 5 · 확정 0 · 기각 5")
    assert gate(root, "record-sweep", "b1", "--clean", "gate_round1.md") == 0
    led = ledger(root, "b1")
    assert led["code_count"] == 0 and led["sweeps"][-1]["kind"] == "clean"
    assert "P5b: 확정 회귀 0" in _pr_body(root, ws)


def test_skipped_sweep_reason_reaches_the_pr_body(tmp_path):
    root, ws = _passed(tmp_path)
    assert gate(root, "record-sweep", "b1", "--skipped", "ui 없음") == 0
    assert "P5b: 생략 — ui 없음" in _pr_body(root, ws)


def test_record_sweep_takes_exactly_one_outcome(tmp_path):
    root, ws = _passed(tmp_path)
    (ws / "g.md").write_text("x")
    assert gate(root, "record-sweep", "b1", "--clean", "g.md", "--skipped", "ui 없음") == 2
    assert gate(root, "record-sweep", "b1") == 2
