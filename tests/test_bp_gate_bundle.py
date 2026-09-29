"""bundle — 작업공간(무시 경로)을 다른 머신으로 옮긴다.

원천 실행(S0): 일회성 클라우드 세션이 끝나면 루브릭 · probe · 카드가 사라졌다. R-SYMPTOM 한 행만 랩탑에서
재생하려 해도 옮길 통로가 없었다.
"""
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bp_fixture import fix_commit, formal_ready, gate, git, ledger, red_commit  # noqa: E402


def _judged_once(tmp_path):
    root, ws = formal_ready(tmp_path / "a")
    gate(root, "freeze", "b1")
    red = red_commit(root)
    gate(root, "baseline", "b1", "--red", "tests/red.sh")
    assert gate(root, "run", "b1") == 1          # CODE — 원문 출력 run_1/ 이 생긴다
    fix_commit(root, red)
    return root, ws


def _names(bundle):
    with tarfile.open(bundle) as t:
        return set(t.getnames())


def test_bundle_keeps_the_frozen_set_and_drops_raw_output(tmp_path):
    root, ws = _judged_once(tmp_path)
    assert gate(root, "bundle", "b1") == 0
    names = _names(root / ".bugfix-pipeline" / "b1-bundle.tar.gz")
    for keep in ("ledger.json", "repro.md", "repro.sh", "root_cause.json", "rubric.json",
                 "control/broken.diff", "verdict_1.json"):
        assert f"b1/{keep}" in names, keep
    assert not any(n.startswith(("b1/run_", "b1/baseline_cache")) for n in names), names
    assert "b1/control_cache.json" not in names


def test_bundle_resumes_on_another_clone(tmp_path):
    root, _ = _judged_once(tmp_path)
    gate(root, "bundle", "b1")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(root), str(other))
    (other / ".bugfix-pipeline").mkdir()
    with tarfile.open(root / ".bugfix-pipeline" / "b1-bundle.tar.gz") as t:
        t.extractall(other / ".bugfix-pipeline", filter="data")
    # 동결 해시 · RED 블롭 · 커밋 감사가 다른 클론에서도 성립한다 — 변조로 읽히지 않는다
    assert gate(other, "run", "b1") == 0
    assert ledger(other, "b1")["history"][-1]["attribution"] == "PASS"


def test_bundle_warns_when_head_is_not_on_any_remote(tmp_path, capsys):
    root, _ = _judged_once(tmp_path)
    assert gate(root, "bundle", "b1") == 0
    assert "원격" in capsys.readouterr().out


def test_bundle_needs_a_workspace(tmp_path):
    root, _ = formal_ready(tmp_path)
    assert gate(root, "bundle", "nope") == 2
