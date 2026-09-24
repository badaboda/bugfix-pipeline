"""init — 레포 신호로 템플릿을 골라 «검사를 통과하지 못하는» 초안을 쓴다."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_profile  # noqa: E402
from bp_profile import PROFILE_PATH, ProfileError, init, load  # noqa: E402


def test_pyproject_gets_a_pytest_draft_that_check_rejects(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert init(tmp_path) == 0
    data = json.loads((tmp_path / PROFILE_PATH).read_text())
    assert data["regress"]["tree_marker"] == "pyproject.toml"
    with pytest.raises(ProfileError) as e:
        load(tmp_path)
    assert any("_draft" in p for p in e.value.problems)


def test_draft_passes_once_the_draft_key_is_removed(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    init(tmp_path)
    path = tmp_path / PROFILE_PATH
    data = json.loads(path.read_text())
    del data["_draft"]
    path.write_text(json.dumps(data))
    p = load(tmp_path)
    assert p.regress.side_cmd[0].endswith(".claude/bugfix-pipeline/bp_side.sh")


def test_vitest_config_gets_a_vitest_draft(tmp_path):
    (tmp_path / "vitest.config.ts").write_text("export default {}\n")
    assert init(tmp_path) == 0
    assert (tmp_path / ".claude" / "bugfix-pipeline" / "bp_side.sh").read_text().count("vitest") >= 1


def test_existing_profile_is_never_overwritten(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".claude").mkdir()
    (tmp_path / PROFILE_PATH).write_text('{"schema": 2}')
    assert init(tmp_path) == 2
    assert (tmp_path / PROFILE_PATH).read_text() == '{"schema": 2}'


def test_no_signal_writes_nothing(tmp_path, capsys):
    assert init(tmp_path) == 2
    assert not (tmp_path / ".claude").exists()


def test_two_stacks_are_listed_not_guessed(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "vitest.config.ts").write_text("")
    assert init(tmp_path) == 2
    err = capsys.readouterr().err
    assert "pytest" in err and "vitest" in err
    assert not (tmp_path / PROFILE_PATH).exists()


def test_copied_wrappers_are_executable(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    init(tmp_path)
    for name in ("bp_side.sh", "bp_exec.sh"):
        assert (tmp_path / ".claude" / "bugfix-pipeline" / name).stat().st_mode & 0o111
