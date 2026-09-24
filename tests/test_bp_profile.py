"""프로파일 v1 로더·검사기. 표본은 bp_profile --selftest 와 «다른» 값을 쓴다 —
같은 표본이면 selftest 의 사각을 그대로 물려받는다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
import bp_profile  # noqa: E402
from bp_profile import PROFILE_PATH, ProfileError, load  # noqa: E402


def _problems(root):
    with pytest.raises(ProfileError) as e:
        load(root)
    return e.value.problems


def _one(root, needle):
    problems = _problems(root)
    assert any(needle in p for p in problems), problems


def test_valid_profile_resolves_side_cmd_against_the_invocation_root(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    p = load(root)
    assert p.root == root
    assert p.side_cmd == (str(root / "bin" / "side.sh"),)
    assert p.ran_fully == "^DONE "
    assert p.not_fully == "PARTIAL"
    assert p.tree_marker == "tests/marker"
    assert p.allowed_roots == ()


def test_missing_profile_file_is_named(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    (root / PROFILE_PATH).unlink()
    _one(root, "프로파일이 없다")


def test_invalid_json_is_rejected(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    (root / PROFILE_PATH).write_text("{", encoding="utf-8")
    _one(root, "JSON")


def test_every_problem_is_reported_not_only_the_first(tmp_path):
    root = bp_fixture.make_root(
        tmp_path, {"schema": 2, "regress.ran_fully": None, "regress.typo": 1}
    )
    assert len(_problems(root)) == 3


def test_boolean_schema_is_not_schema_one(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"schema": True}), "schema")


def test_typo_in_an_optional_key_is_rejected_not_ignored(tmp_path):
    root = bp_fixture.make_root(
        tmp_path, {"regress.not_fully": None, "regress.not_fuly": "PARTIAL"}
    )
    _one(root, "모르는 키: regress.not_fuly")


def test_side_cmd_without_exec_bit_is_rejected(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    (root / "bin" / "side.sh").chmod(0o644)
    _one(root, "실행 권한")


def test_side_cmd_bare_name_is_looked_up_on_path(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"regress.side_cmd": ["sh", "bin/side.sh"]})
    assert load(root).side_cmd == ("sh", "bin/side.sh")


def test_side_cmd_bare_name_missing_from_path_is_rejected(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"regress.side_cmd": ["no-such-command-bp"]})
    _one(root, "PATH")


def test_pattern_that_grep_cannot_parse_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.ran_fully": "["}), "grep -E")


def test_pattern_matching_an_empty_line_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.ran_fully": ".*"}), "빈 줄")


def test_pattern_with_a_newline_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.not_fully": "PARTIAL\nDIED"}), "개행")


def test_tree_marker_escaping_the_tree_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.tree_marker": "../outside"}), "상대 경로")


def test_tree_marker_missing_in_root_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.tree_marker": "tests/nope"}), "호출 루트에 없다")


def test_allowed_roots_tilde_is_expanded(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"regress.allowed_roots": ["~"]})
    assert load(root).allowed_roots == (Path.home().resolve(),)


def test_allowed_roots_empty_list_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.allowed_roots": []}), "비어")


def test_allowed_roots_relative_path_is_rejected(tmp_path):
    _one(bp_fixture.make_root(tmp_path, {"regress.allowed_roots": ["rel/dir"]}), "절대 경로")


def test_check_cli_exit_codes(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    assert bp_profile.main(["check", str(root)]) == 0
    bp_fixture.write_profile(root, {"schema": 2})
    assert bp_profile.main(["check", str(root)]) == 2
