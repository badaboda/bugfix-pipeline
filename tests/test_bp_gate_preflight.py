"""P0 사전 점검 — preflight · env.json · 루브릭 행의 needs.

원천 실행(S0): 끝낼 수 없는 행(키 · 스택이 없는 호스트)을 P5 에서야 알았다. P0 에서 잴 수 있었다.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
import bp_profile  # noqa: E402
from bp_fixture import RUBRIC_OK, fix_commit, formal_ready, gate, ledger, red_commit  # noqa: E402

KEY = "BP_TEST_PREFLIGHT_KEY"
CHECKS = {"preflight.checks": [
    {"name": "api-key", "cmd": ["sh", "-c", f'test -n "${KEY}"']},
    {"name": "always", "cmd": ["true"]},
]}


def _needs(row, *names):
    rub = copy.deepcopy(RUBRIC_OK)
    rub[row]["needs"] = list(names)
    return rub


# 프로파일 ---------------------------------------------------------------

def test_profile_reads_preflight_checks(tmp_path):
    p = bp_profile.load(bp_fixture.make_root(tmp_path, CHECKS))
    assert [c.name for c in p.checks] == ["api-key", "always"]
    assert p.checks[1].cmd == ("true",)


def test_profile_without_preflight_has_no_checks(tmp_path):
    assert bp_profile.load(bp_fixture.make_root(tmp_path)).checks == ()


@pytest.mark.parametrize("checks, needle", [
    ([], "비어"),
    ([{"name": "a"}], "cmd"),
    ([{"name": "Bad Name", "cmd": ["true"]}], "name"),
    ([{"name": "a", "cmd": ["true"]}, {"name": "a", "cmd": ["true"]}], "겹친다"),
    ([{"name": "a", "cmd": ["true"], "why": "x"}], "모르는 키: preflight.checks[0].why"),
])
def test_profile_rejects_bad_checks(tmp_path, checks, needle):
    root = bp_fixture.make_root(tmp_path, {"preflight.checks": checks})
    with pytest.raises(bp_profile.ProfileError) as e:
        bp_profile.load(root)
    assert any(needle in p for p in e.value.problems), e.value.problems


# preflight 명령 ----------------------------------------------------------

def test_preflight_writes_env_json(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    root = bp_fixture.make_gate_host(tmp_path, CHECKS)
    gate(root, "init", "b1")
    assert gate(root, "preflight", "b1") == 0
    env = json.loads((root / ".bugfix-pipeline" / "b1" / "env.json").read_text())
    assert env["exec"]["ok"] is True
    assert env["checks"]["api-key"]["ok"] is False and env["checks"]["always"]["ok"] is True
    assert env["sections"] == {"exec": False, "regress": True, "ui": False}
    assert env["head"] == bp_fixture.git(root, "rev-parse", "HEAD")


def test_preflight_fails_when_exec_cannot_assemble(tmp_path):
    root = bp_fixture.make_gate_host(tmp_path)
    (root / "bin" / "exec.sh").write_text("#!/bin/sh\nexit 125\n")
    (root / "bin" / "exec.sh").chmod(0o755)
    bp_fixture.write_profile(root, {"exec.exec_cmd": ["bin/exec.sh"]})
    gate(root, "init", "b1")
    assert gate(root, "preflight", "b1") == 2
    env = json.loads((root / ".bugfix-pipeline" / "b1" / "env.json").read_text())
    assert env["exec"] == {"ok": False, "exit": 125}


# needs — freeze 에서 거부 ---------------------------------------------------

def test_freeze_refuses_a_row_whose_need_is_unmet(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(KEY, raising=False)
    root, _ = formal_ready(tmp_path, rubric=_needs("R-SYMPTOM", "api-key"), overrides=CHECKS)
    assert gate(root, "freeze", "b1") == 2
    err = capsys.readouterr().err
    assert "R-SYMPTOM" in err and "api-key" in err and "①" in err and "③" in err


def test_freeze_refuses_an_unknown_need(tmp_path, capsys):
    root, _ = formal_ready(tmp_path, rubric=_needs("R-CAUSE", "nope"), overrides=CHECKS)
    assert gate(root, "freeze", "b1") == 2
    assert "nope" in capsys.readouterr().err


def test_freeze_accepts_a_met_need(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY, "x")
    root, _ = formal_ready(tmp_path, rubric=_needs("R-SYMPTOM", "api-key", "always"), overrides=CHECKS)
    assert gate(root, "freeze", "b1") == 0


# needs — run 에서는 ENV ------------------------------------------------------

def test_unmet_need_at_run_time_is_env_not_anchor(tmp_path, monkeypatch):
    # 키가 없으면 probe 가 «돌았는데 FAIL» 처럼 보여 ANCHOR 로 오분류된다 — needs 가 그것을 ENV 로 가른다
    monkeypatch.setenv(KEY, "x")
    rub = _needs("R-SYMPTOM", "api-key")
    rub["R-SYMPTOM"]["probe"] = ["sh", "-c", f'test -n "${KEY}" && cat {{tree}}/value.txt']
    root, _ = formal_ready(tmp_path, rubric=rub, overrides=CHECKS)
    assert gate(root, "freeze", "b1") == 0
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    monkeypatch.delenv(KEY)
    assert gate(root, "run", "b1") == 1
    last = ledger(root, "b1")["history"][-1]
    assert last["attribution"] == "ENV"
    rows = json.loads((root / ".bugfix-pipeline" / "b1" / "verdict_1.json").read_text())["rows"]
    assert rows["R-SYMPTOM"]["needs_unmet"] == ["api-key"]


def test_same_rubric_with_the_key_passes(tmp_path, monkeypatch):
    # 위 테스트의 양성 대조 — 키가 있으면 같은 루브릭이 PASS 다(ENV 가 루브릭 탓이 아님)
    monkeypatch.setenv(KEY, "x")
    rub = _needs("R-SYMPTOM", "api-key")
    rub["R-SYMPTOM"]["probe"] = ["sh", "-c", f'test -n "${KEY}" && cat {{tree}}/value.txt']
    root, _ = formal_ready(tmp_path, rubric=rub, overrides=CHECKS)
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    assert gate(root, "run", "b1") == 0
