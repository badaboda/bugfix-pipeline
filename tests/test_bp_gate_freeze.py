"""bp_gate — freeze · refreeze."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import RUBRIC_OK, formal_ready, gate, ledger  # noqa: E402


def _rubric(**changes):
    r = copy.deepcopy(RUBRIC_OK)
    r.update(changes)
    return r


def test_valid_set_is_frozen_with_hashes(tmp_path):
    root, _ = formal_ready(tmp_path)
    assert gate(root, "freeze", "b1") == 0
    led = ledger(root, "b1")
    assert led["cause_id"] == "value-01" and led["phase"] == "P2"
    assert set(led["frozen"]) == {"root_cause.json", "rubric.json", "repro.md", "repro.sh", "control/broken.diff"}


def test_missing_expected_after_is_refused(tmp_path, capsys):
    root, ws = formal_ready(tmp_path)
    (ws / "repro.md").write_text("steps: x\nobserved: bad\nwhere: y\nexpected_after:\n")
    assert gate(root, "freeze", "b1") == 2
    assert "expected_after" in capsys.readouterr().err


def test_cannot_measure_is_refused_with_to_light_hint(tmp_path, capsys):
    root, ws = formal_ready(tmp_path)
    (ws / "root_cause.json").write_text(json.dumps({"cause_id": "value-01", "verdict": "CANNOT-MEASURE"}))
    assert gate(root, "freeze", "b1") == 2
    assert "to-light" in capsys.readouterr().err


def test_cause_id_mismatch_is_refused(tmp_path):
    root, _ = formal_ready(tmp_path, rubric=_rubric(cause_id="other"))
    assert gate(root, "freeze", "b1") == 2


def test_url_and_unknown_placeholders_are_refused(tmp_path, capsys):
    bad = _rubric(**{"R-CAUSE": {"probe": ["{exec}", "{tree}", "--", "curl", "{url}", "{nope}"]}})
    root, _ = formal_ready(tmp_path, rubric=bad)
    assert gate(root, "freeze", "b1") == 2
    err = capsys.readouterr().err
    assert "{url}" in err and "{nope}" in err


def test_missing_patch_file_is_refused(tmp_path):
    root, ws = formal_ready(tmp_path)
    (ws / "control" / "broken.diff").unlink()
    assert gate(root, "freeze", "b1") == 2


def test_empty_control_axes_are_refused(tmp_path):
    root, _ = formal_ready(tmp_path, rubric=_rubric(**{"R-CONTROL": {"axes": []}}))
    assert gate(root, "freeze", "b1") == 2


def test_freeze_needs_the_formal_track(tmp_path):
    root, _ = formal_ready(tmp_path)
    gate(root, "to-light", "b1", "--kind", "size", "--reason", "작다")
    assert gate(root, "freeze", "b1") == 2


def test_freeze_twice_is_refused(tmp_path):
    root, _ = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    assert gate(root, "freeze", "b1") == 2


def test_refreeze_records_a_cause_change(tmp_path):
    root, ws = formal_ready(tmp_path)
    gate(root, "freeze", "b1")
    (ws / "root_cause.json").write_text(json.dumps(
        {"cause_id": "value-02", "verdict": "BUG", "fix_scope": ["value.txt"]}))
    (ws / "rubric.json").write_text(json.dumps(_rubric(cause_id="value-02")))
    assert gate(root, "refreeze", "b1", "--reason", "원인이 달랐다") == 0
    led = ledger(root, "b1")
    assert led["cause_id"] == "value-02"
    assert led["cause_changes"][-1]["from_cause"] == "value-01"


def test_code_braces_in_inline_probes_are_not_placeholders(tmp_path):
    # 종단 실측(TS 라이브러리): 인라인 node -e 의 객체 리터럴 · 블록이 «모르는 자리표시자»로 거부됐다 —
    # 조사자 문서는 probe 를 인라인으로 쓰라고 한다. 자리표시자는 중괄호 안 «소문자 한 단어»뿐이다
    code = 'const j=require("jiti")(__filename,{fsCache:false});for(const s of ["a"]){if(s)process.exit(0)}'
    ok = _rubric(**{"R-CAUSE": {"probe": ["{exec}", "{tree}", "--", "node", "-e", code]}})
    root, _ = formal_ready(tmp_path, rubric=ok)
    assert gate(root, "freeze", "b1") == 0


def test_unfilled_expected_after_placeholder_in_assert_is_refused(tmp_path, capsys):
    # 조사자는 R-SYMPTOM.assert 에 자리표시만 남긴다 — 리더가 GATE 1 에서 옮기지 않으면 매번 FAIL 이 ANCHOR 로 읽힌다
    rub = _rubric(**{"R-SYMPTOM": {"probe": RUBRIC_OK["R-SYMPTOM"]["probe"],
                                   "assert": ["grep", "-q", "-F", "-e", "<expected_after 의 문구>", "{out}"]}})
    root, _ = formal_ready(tmp_path, rubric=rub)
    assert gate(root, "freeze", "b1") == 2
    assert "expected_after" in capsys.readouterr().err
