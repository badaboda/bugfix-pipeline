"""bp_gate — triage · promote · to-light."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import REPRO_SH_TEXT, gate, git, ledger, make_gate_host  # noqa: E402

WS = ".bugfix-pipeline"


def _ready(tmp_path, repro=REPRO_SH_TEXT, observed="bad", overrides=None):
    root = make_gate_host(tmp_path, overrides)
    gate(root, "init", "b1")
    ws = root / WS / "b1"
    (ws / "repro.md").write_text(f"steps: 화면을 연다\nobserved: {observed}\nwhere: 로컬\nexpected_after:\n")
    if repro is not None:
        (ws / "repro.sh").write_text(repro)
    return root, ws


def test_deterministic_repro_with_suite_is_formal(tmp_path):
    root, _ = _ready(tmp_path)
    assert gate(root, "triage", "b1", "--repro-confirmed") == 0
    led = ledger(root, "b1")
    assert led["track"] == "formal" and led["phase"] == "P1"
    assert led["triage"]["deterministic"] and led["base_sha"] == git(root, "rev-parse", "HEAD")


def test_repro_sh_without_confirmation_is_refused(tmp_path, capsys):
    root, _ = _ready(tmp_path)
    assert gate(root, "triage", "b1") == 2
    assert "--repro-confirmed" in capsys.readouterr().err


def test_no_repro_sh_is_light(tmp_path):
    root, _ = _ready(tmp_path, repro=None)
    assert gate(root, "triage", "b1") == 0
    assert ledger(root, "b1")["track"] == "light"


def test_flaky_repro_is_light(tmp_path):
    flaky = '#!/bin/sh\nn=$(cat "$0.n" 2>/dev/null || echo 0)\necho $((n+1)) > "$0.n"\n[ "$n" = 1 ] && echo ok || cat "$1/value.txt"\n'
    root, _ = _ready(tmp_path, repro=flaky)
    gate(root, "triage", "b1", "--repro-confirmed")
    led = ledger(root, "b1")
    assert led["track"] == "light" and not led["triage"]["deterministic"]


def test_no_regress_section_is_light(tmp_path):
    root, _ = _ready(tmp_path, overrides={"regress": None})
    gate(root, "triage", "b1", "--repro-confirmed")
    led = ledger(root, "b1")
    assert led["track"] == "light" and not led["triage"]["suite"]


def test_light_flag_forces_light(tmp_path):
    root, _ = _ready(tmp_path)
    gate(root, "triage", "b1", "--repro-confirmed", "--light")
    assert ledger(root, "b1")["track"] == "light"


def test_triage_twice_is_refused(tmp_path):
    root, _ = _ready(tmp_path)
    gate(root, "triage", "b1", "--repro-confirmed")
    assert gate(root, "triage", "b1", "--repro-confirmed") == 2


def test_promote_needs_the_formal_premises(tmp_path, capsys):
    root, _ = _ready(tmp_path, repro=None)
    gate(root, "triage", "b1")
    assert gate(root, "promote", "b1", "--reason", "두 파일") == 2
    assert "GATE L" in capsys.readouterr().err


def test_promote_from_a_light_request_when_premises_hold(tmp_path):
    root, _ = _ready(tmp_path)
    gate(root, "triage", "b1", "--repro-confirmed", "--light")
    assert gate(root, "promote", "b1", "--reason", "공유 파일") == 0
    led = ledger(root, "b1")
    assert led["track"] == "formal" and led["phase"] == "P1"
    assert led["track_changes"][-1]["to"] == "formal"


def test_to_light_records_kind_and_reason(tmp_path):
    root, _ = _ready(tmp_path)
    gate(root, "triage", "b1", "--repro-confirmed")
    assert gate(root, "to-light", "b1", "--kind", "unstable", "--reason", "VOID 2회") == 0
    change = ledger(root, "b1")["track_changes"][-1]
    assert (change["to"], change["kind"], change["reason"]) == ("light", "unstable", "VOID 2회")
