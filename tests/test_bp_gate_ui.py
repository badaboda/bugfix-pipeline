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
