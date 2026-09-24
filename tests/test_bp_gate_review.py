"""bp_gate — A2 최종 리뷰가 실측으로 찾은 거짓 PASS · cap 우회 · 예외 경로."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_gate  # noqa: E402
import bp_regress  # noqa: E402
from bp_fixture import (REPRO_SH_TEXT, RUBRIC_OK, fix_commit, formal_ready, gate, git,  # noqa: E402
                        ledger, light_ready, make_host, red_commit, set_mode)

PATCH_ONLY = copy.deepcopy(RUBRIC_OK)
PATCH_ONLY["R-CONTROL"]["axes"] = [RUBRIC_OK["R-CONTROL"]["axes"][1]]


def _at_p3(tmp_path, rubric=None):
    root, ws = formal_ready(tmp_path, rubric=rubric)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    return root, ws, red


# ── C1 · 커밋 안 된 수정 ──────────────────────────────────────────────────────


def test_run_refuses_an_uncommitted_fix(tmp_path, capsys):
    root, ws, red = _at_p3(tmp_path)
    (root / "value.txt").write_text("good\n")
    assert gate(root, "run", "b1") == 2
    assert "커밋" in capsys.readouterr().err


def test_run_refuses_an_uncommitted_red_edit(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    (root / "tests" / "red.sh").write_text("true\n")
    assert gate(root, "run", "b1") == 2


def test_light_verify_refuses_an_uncommitted_fix(tmp_path):
    root, ws = light_ready(tmp_path)
    git(root, "commit", "-q", "--allow-empty", "-m", "chore: 빈 커밋")
    (root / "value.txt").write_text("good\n")
    assert gate(root, "light-verify", "b1") == 2


# ── C2 · baseline 재실행 ─────────────────────────────────────────────────────


def test_baseline_twice_is_refused(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 2


def test_baseline_needs_the_formal_track(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    gate(root, "to-light", "b1", "--kind", "size", "--reason", "작다")
    red_commit(root)
    assert gate(root, "baseline", "b1", "--red", "tests/red.sh") == 2


# ── I1 · RED 이전의 fix ──────────────────────────────────────────────────────


def test_a_fix_committed_before_the_red_commit_is_refused(tmp_path):
    root, ws = formal_ready(tmp_path, rubric=PATCH_ONLY)
    gate(root, "freeze", "b1")
    fix_commit(root, "0000000", body="RED 없음")
    red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    assert gate(root, "run", "b1") == 2


# ── I2 · I3 · I4 · 환불과 cap ────────────────────────────────────────────────


def test_refund_without_any_change_is_refused(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    gate(root, "run", "b1")
    assert gate(root, "refreeze", "b1", "--reason", "그대로", "--refund-last") == 2


def _change_frozen(ws):
    text = (ws / "repro.md").read_text().replace("where: 로컬", "where: 로컬 (측정 조건 보정)")
    (ws / "repro.md").write_text(text)


def test_refund_after_deferred_reopens_the_loop(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert [gate(root, "run", "b1") for _ in range(3)] == [1, 1, 4]
    _change_frozen(ws)
    assert gate(root, "refreeze", "b1", "--reason", "측정 결함", "--refund-last") == 0
    led = ledger(root, "b1")
    assert led["code_count"] == 2 and led["phase"] != "DEFERRED"
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0


def test_to_light_from_deferred_is_refused(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    for _ in range(3):
        gate(root, "run", "b1")
    assert gate(root, "to-light", "b1", "--kind", "size", "--reason", "우회") == 2


# ── I5 · 망가진 재현을 «고쳐짐»으로 ──────────────────────────────────────────


def test_a_crashing_repro_after_the_fix_is_labelled(tmp_path):
    root, ws = light_ready(tmp_path)
    git(root, "rm", "-q", "value.txt")
    git(root, "commit", "-q", "-m", "fix: 값을 지웠다")
    gate(root, "light-verify", "b1")
    assert bp_gate.LABEL_NO_DETERMINISM in bp_gate._light_labels(ledger(root, "b1"))


# ── I6 · R-CONTROL 캐시 키 ───────────────────────────────────────────────────


def test_control_cache_misses_when_a_frozen_patch_changes(tmp_path):
    root, ws, red = _at_p3(tmp_path, rubric=PATCH_ONLY)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
    harmless = (ws / "control" / "broken.diff").read_text().replace("broken", "other")
    (ws / "control" / "broken.diff").write_text(harmless)
    assert gate(root, "refreeze", "b1", "--reason", "변이 교체") == 0
    assert gate(root, "run", "b1") == 1
    assert ledger(root, "b1")["history"][-1]["attribution"] == "VOID"


# ── I7 · 예외 경로 ───────────────────────────────────────────────────────────


def test_non_utf8_repro_output_does_not_crash_triage(tmp_path):
    root = formal_ready.__globals__["make_gate_host"](tmp_path)
    gate(root, "init", "b1")
    ws = root / ".bugfix-pipeline" / "b1"
    (ws / "repro.md").write_text("steps: x\nobserved: bad\nwhere: y\nexpected_after:\n")
    (ws / "repro.sh").write_text("#!/bin/sh\nprintf '\\377'\n" + REPRO_SH_TEXT.split("\n", 1)[1])
    assert gate(root, "triage", "b1", "--repro-confirmed") == 0


def test_light_verify_retries_over_a_leftover_directory(tmp_path):
    root, ws = light_ready(tmp_path)
    (root / "value.txt").write_text("good\n")
    git(root, "commit", "-q", "-am", "fix: value")
    (ws / "light_1").mkdir()
    assert gate(root, "light-verify", "b1") == 0


def test_an_unexpected_exception_is_exit_3_not_1(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    (ws / "ledger.json").write_text("{깨짐")
    assert gate(root, "status", "b1") == 3


# ── I8 · 무효한 기준선을 캐시하지 않는다 ─────────────────────────────────────


def test_an_invalid_base_run_is_not_cached(tmp_path):
    root, base = make_host(tmp_path, ["t::a"], ["t::a"])
    cache = tmp_path / "cache"
    set_mode(base, "partial")
    assert bp_regress.run(base, root, tmp_path / "o1", root=root, base_cache=cache) == 3
    (base / "mode").unlink()
    assert bp_regress.run(base, root, tmp_path / "o2", root=root, base_cache=cache) == 0
    assert "base_cached=1" not in (tmp_path / "o2" / "META").read_text()
