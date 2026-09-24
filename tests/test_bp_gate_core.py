"""bp_gate — 원장 · init · status."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
from bp_fixture import gate, ledger, make_gate_host  # noqa: E402

WS = ".bugfix-pipeline"


def test_init_creates_workspace_ledger_and_repro_template(tmp_path):
    root = make_gate_host(tmp_path)
    assert gate(root, "init", "b1") == 0
    led = ledger(root, "b1")
    assert (led["slug"], led["phase"], led["track"], led["code_count"]) == ("b1", "P0", None, 0)
    text = (root / WS / "b1" / "repro.md").read_text()
    assert "observed:" in text and "expected_after:" in text


def test_init_refuses_a_workspace_git_would_track(tmp_path, capsys):
    root = make_gate_host(tmp_path)
    (root / ".gitignore").write_text("mode\n")
    assert gate(root, "init", "b1") == 2
    assert ".gitignore" in capsys.readouterr().err
    assert not (root / WS / "b1").exists()


def test_init_refuses_a_second_active_bug(tmp_path, capsys):
    root = make_gate_host(tmp_path)
    gate(root, "init", "b1")
    assert gate(root, "init", "b2") == 2
    assert "b1" in capsys.readouterr().err


def test_init_allows_a_new_bug_after_close(tmp_path):
    root = make_gate_host(tmp_path)
    gate(root, "init", "b1")
    assert gate(root, "status", "b1", "--close", "done") == 0
    assert gate(root, "init", "b2") == 0


def test_init_rejects_a_bad_slug(tmp_path):
    assert gate(make_gate_host(tmp_path), "init", "Bad/Slug") == 2


def test_init_twice_is_refused(tmp_path):
    root = make_gate_host(tmp_path)
    gate(root, "init", "b1")
    assert gate(root, "init", "b1") == 2


def test_status_reports_track_phase_and_loop(tmp_path, capsys):
    root = make_gate_host(tmp_path)
    gate(root, "init", "b1")
    capsys.readouterr()
    assert gate(root, "status", "b1") == 0
    out = capsys.readouterr().out
    assert "phase=P0" in out and "loop=0/3" in out


def test_unknown_slug_is_a_config_error(tmp_path):
    assert gate(make_gate_host(tmp_path), "status", "nope") == 2
