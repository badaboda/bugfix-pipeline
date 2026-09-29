"""R-REGRESS 의 flag_matrix — 플래그를 켠 조건에서만 보이는 회귀.

원천 실행(S0): 라우터가 플래그 켬에서만 마운트돼, 플래그 조건 쌍을 구현자가 P3 에서 뒤늦게 재량으로 더했다.
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import RUBRIC_OK, fix_commit, formal_ready, gate, git, ledger, red_commit  # noqa: E402

# 가짜 러너 — FLAG_X=1 이면 failures_flag.txt 의 이름도 실패로 낸다
SIDE_WITH_FLAG = """#!/bin/sh
tree=$1; names=$2
cp "$tree/failures.txt" "$names"
if [ "$FLAG_X" = 1 ] && [ -f "$tree/failures_flag.txt" ]; then cat "$tree/failures_flag.txt" >> "$names"; fi
echo "DONE $(wc -l < "$names" | tr -d ' ') failed"
"""
MATRIX = [{"FLAG_X": "0"}, {"FLAG_X": "1"}]


def _rubric(matrix):
    r = copy.deepcopy(RUBRIC_OK)
    if matrix is not None:
        r["flag_matrix"] = matrix
    return r


def _fixed_with_flag_only_regression(tmp_path, matrix):
    root, ws = formal_ready(tmp_path, rubric=_rubric(matrix))
    (root / "bin" / "side.sh").write_text(SIDE_WITH_FLAG)
    git(root, "commit", "-q", "-am", "chore: 러너가 FLAG_X 를 본다")
    assert gate(root, "freeze", "b1") == 0
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    fix_commit(root, red)
    (root / "failures_flag.txt").write_text("t::flag_only\n")
    git(root, "add", "failures_flag.txt")
    git(root, "commit", "-q", "-m", "chore: 플래그 경로")
    return root, ws


def test_without_matrix_the_flag_only_regression_is_invisible(tmp_path, monkeypatch):
    # 대조 — 매트릭스가 없으면 PASS 다. 이것이 막으려는 사각이다
    monkeypatch.delenv("FLAG_X", raising=False)
    root, _ = _fixed_with_flag_only_regression(tmp_path, None)
    assert gate(root, "run", "b1") == 0


def test_matrix_catches_the_flag_only_regression(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FLAG_X", raising=False)
    root, ws = _fixed_with_flag_only_regression(tmp_path, MATRIX)
    assert gate(root, "run", "b1") == 1
    assert ledger(root, "b1")["history"][-1]["attribution"] == "CODE"
    assert (ws / "run_1" / "regress_1" / "new_red.txt").read_text().split() == ["t::flag_only"]
    assert "regress_1" in capsys.readouterr().out


def test_each_condition_caches_its_own_baseline(tmp_path, monkeypatch):
    monkeypatch.delenv("FLAG_X", raising=False)
    root, ws = _fixed_with_flag_only_regression(tmp_path, MATRIX)
    gate(root, "run", "b1")
    base = ledger(root, "b1")["baseline_sha"]
    assert len([p for p in (ws / "baseline_cache" / base).iterdir() if p.is_dir()]) == 2


@pytest.mark.parametrize("matrix, needle", [
    ([], "flag_matrix 는 조건 객체의 비어 있지 않은 배열"),
    ({"FLAG_X": "1"}, "flag_matrix 는 조건 객체의 비어 있지 않은 배열"),
    ([{"flag-x": "1"}], "flag-x"),
    ([{"FLAG_X": 1}], "FLAG_X"),
    ([{"FLAG_X": "1"}, {"FLAG_X": "1"}], "겹친다"),
])
def test_freeze_rejects_bad_matrix(tmp_path, capsys, matrix, needle):
    root, _ = formal_ready(tmp_path, rubric=_rubric(matrix))
    assert gate(root, "freeze", "b1") == 2
    assert needle in capsys.readouterr().err
