"""bp_gate — run."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import (RUBRIC_OK, fix_commit, formal_ready, gate, git, ledger,  # noqa: E402
                        red_commit, set_failures)


def _at_p3(tmp_path, rubric=None, overrides=None):
    root, ws = formal_ready(tmp_path, rubric=rubric, overrides=overrides)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    return root, ws, red


def _last(root):
    return ledger(root, "b1")["history"][-1]


def test_full_flow_passes(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
    h = _last(root)
    assert h["attribution"] == "PASS" and ledger(root, "b1")["phase"] == "P5b"
    assert (ws / "verdict_1.json").is_file()


def test_no_fix_is_code(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert gate(root, "run", "b1") == 1
    assert _last(root)["attribution"] == "CODE" and ledger(root, "b1")["code_count"] == 1


def test_control_that_does_not_go_red_is_void(tmp_path):
    rub = copy.deepcopy(RUBRIC_OK)
    rub["R-CONTROL"]["axes"] = [{"name": "무관", "mutate": {"checkout": "HEAD"}}]
    root, ws, red = _at_p3(tmp_path, rubric=rub)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1
    assert _last(root)["attribution"] == "VOID"


def test_symptom_failure_is_anchor(tmp_path):
    rub = copy.deepcopy(RUBRIC_OK)
    rub["R-SYMPTOM"]["assert"] = ["grep", "-q", "nope", "{out}"]
    root, ws, red = _at_p3(tmp_path, rubric=rub)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1
    assert _last(root)["attribution"] == "ANCHOR"


def test_probe_that_cannot_run_is_env(tmp_path):
    rub = copy.deepcopy(RUBRIC_OK)
    rub["R-CAUSE"]["probe"] = ["{exec}", "{tree}", "--", "no-such-command-bp"]
    root, ws, red = _at_p3(tmp_path, rubric=rub)
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1
    assert _last(root)["attribution"] == "ENV"


def test_regress_new_red_is_code(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    set_failures(root, ["t::broke"])
    git(root, "add", "failures.txt")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1
    h = _last(root)
    assert h["attribution"] == "CODE" and h["args"]["regress"] is False


def test_cap_reached_on_third_code(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert [gate(root, "run", "b1") for _ in range(3)] == [1, 1, 4]
    assert ledger(root, "b1")["phase"] == "DEFERRED"
    assert gate(root, "run", "b1") == 4
    assert len(ledger(root, "b1")["history"]) == 3


def test_tampered_rubric_is_exit_2(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red)
    (ws / "rubric.json").write_text((ws / "rubric.json").read_text() + "\n")
    assert gate(root, "run", "b1") == 2


def test_fix_without_red_is_exit_2(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    fix_commit(root, red, body="RED 없음")
    assert gate(root, "run", "b1") == 2


def test_run_leaves_no_worktrees_even_when_env_fails(tmp_path):
    rub = copy.deepcopy(RUBRIC_OK)
    rub["R-CAUSE"]["probe"] = ["{exec}", "{tree}", "--", "no-such-command-bp"]
    root, ws, red = _at_p3(tmp_path, rubric=rub)
    gate(root, "run", "b1")
    assert git(root, "worktree", "list").count("\n") == 0


def test_refund_last_code_needs_a_code(tmp_path):
    root, ws, red = _at_p3(tmp_path)
    assert gate(root, "refreeze", "b1", "--reason", "측정 결함", "--refund-last") == 2
    gate(root, "run", "b1")
    # 환불은 측정을 고친 재동결에서만 — 동결 파일 하나를 실제로 고친다(A2 리뷰 I2)
    (ws / "repro.md").write_text((ws / "repro.md").read_text().replace("where: 로컬", "where: 로컬 (보정)"))
    assert gate(root, "refreeze", "b1", "--reason", "측정 결함", "--refund-last") == 0
    led = ledger(root, "b1")
    assert led["code_count"] == 0 and led["history"][0]["refunded"]


def test_copy_that_measures_differently_from_the_root_is_env(tmp_path):
    # 사본에는 git 이 무시하는 생성 파일이 없다(실측: hatch-vcs _version.py — import 가 exit 1).
    # 사본이 «망가져서» 빨개지면 R-CONTROL 축이 공허하게 통과한다 — 변이 전 사본을 원본과 대조해 ENV 로
    root, ws, red = _at_p3(tmp_path)
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + "gen\n")
    (root / "gen").write_text("x\n")
    (root / "check.sh").write_text('[ -e gen ] && [ "$(cat value.txt)" = good ] && [ ! -e broken ]\n')
    git(root, "commit", "-q", "-am", "chore: 생성 파일에 기대는 불변식")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 1
    h = _last(root)
    assert h["attribution"] == "ENV"
