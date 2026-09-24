"""R-REGRESS 실행부. 표본은 bp_regress --selftest 와 «다른» 쪽·이름을 쓴다."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
from bp_regress import run  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bp_regress.py"


def _meta(out):
    return dict(line.split("=", 1) for line in (out / "META").read_text().splitlines())


def test_same_failures_on_both_sides_is_green(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x", "m::y"], ["m::y", "m::x"])
    assert run(base, root, tmp_path / "out", root=root) == 0
    assert (tmp_path / "out" / "EXIT").read_text() == "0\n"


def test_new_failure_is_red_and_named(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x"], ["m::x", "m::z"])
    assert run(base, root, tmp_path / "out", root=root) == 1
    assert (tmp_path / "out" / "new_red.txt").read_text() == "m::z\n"


def test_only_fixed_failures_is_green(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x", "m::z"], ["m::z"])
    assert run(base, root, tmp_path / "out", root=root) == 0


def test_swapped_trees_are_void(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x"], ["m::x"])
    assert run(root, base, tmp_path / "out", root=root) == 3


def test_missing_marker_in_the_after_tree_is_void(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    (root / "tests" / "marker").unlink()
    assert run(base, root, tmp_path / "out", root=base) == 3


def test_not_fully_pattern_in_a_log_is_void(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    bp_fixture.set_mode(base, "partial")
    assert run(base, root, tmp_path / "out", root=root) == 3


def test_wrapper_that_writes_no_names_is_void(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    bp_fixture.set_mode(base, "nonames")
    assert run(base, root, tmp_path / "out", root=root) == 3


def test_commit_during_measurement_is_void(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    bp_fixture.set_mode(root, "commit")
    assert run(base, root, tmp_path / "out", root=root) == 3


def test_non_git_tree_is_a_config_error(tmp_path):
    root, _ = bp_fixture.make_host(tmp_path, [], [])
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run(plain, root, tmp_path / "out", root=root) == 2


def test_tree_outside_allowed_roots_is_a_config_error(tmp_path):
    root, base = bp_fixture.make_host(
        tmp_path, [], [], {"regress.allowed_roots": ["/nonexistent-bp-root"]}
    )
    assert run(base, root, tmp_path / "out", root=root) == 2


def test_invalid_profile_is_a_config_error(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    bp_fixture.write_profile(root, {"regress.ran_fully": None})
    assert run(base, root, tmp_path / "out", root=root) == 2


def test_wrapper_receives_only_the_tree_and_the_names_path(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    out = (tmp_path / "out").resolve()  # run() 이 realpath 로 푼다 — 비교도 같은 기준으로
    run(base, root, out, root=root)
    for side, tree in (("base", base), ("after", root)):
        first = (out / f"{side}.log").read_text().splitlines()[0]
        assert first == f"argv: 2|{tree}|{out / f'{side}_names.txt'}"


def test_meta_records_heads_times_and_dirt(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    out = tmp_path / "out"
    run(base, root, out, root=root)
    meta = _meta(out)
    assert meta["base_head_before"] == bp_fixture.git(base, "rev-parse", "HEAD")
    assert meta["after_head_after"] == bp_fixture.git(root, "rev-parse", "HEAD")
    assert meta["base_dirty"] == "0"
    assert {"side_cmd", "base_start", "base_end", "after_start", "after_end"} <= set(meta)


def test_cli_resolves_the_invocation_root_from_cwd(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x"], ["m::x"])
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "run", str(base), str(root), str(tmp_path / "out")],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ── Review Focus ─────────────────────────────────────────────────────────────


def test_stale_names_from_a_previous_run_are_not_reused(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, ["m::x"], ["m::x"])
    out = tmp_path / "out"
    assert run(base, root, out, root=root) == 0
    bp_fixture.set_mode(root, "nonames")
    assert run(base, root, out, root=root) == 3


def test_early_stop_overwrites_a_stale_exit_file(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    out = tmp_path / "out"
    assert run(base, root, out, root=root) == 0
    bp_fixture.write_profile(root, {"schema": 2})
    assert run(base, root, out, root=root) == 2
    assert (out / "EXIT").read_text() == "2\n"


def test_caller_env_not_fully_does_not_leak_into_judgement(tmp_path, monkeypatch):
    root, base = bp_fixture.make_host(tmp_path, [], [], {"regress.not_fully": None})
    monkeypatch.setenv("BP_NOT_FULLY", "DONE")
    assert run(base, root, tmp_path / "out", root=root) == 0


def test_allowed_root_given_through_a_symlink_still_contains_the_trees(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    root, base = bp_fixture.make_host(real, [], [], {"regress.allowed_roots": [str(link)]})
    assert run(base, root, real / "out", root=root) == 0


def test_same_head_with_uncommitted_fix_is_measured_and_marked_dirty(tmp_path):
    root, _ = bp_fixture.make_host(tmp_path, ["m::x"], ["m::x"])
    same = tmp_path / "same"
    bp_fixture.git(root, "worktree", "add", "-q", "--detach", str(same), "HEAD")
    bp_fixture.set_failures(root, ["m::x", "m::w"])
    out = tmp_path / "out"
    assert run(same, root, out, root=root) == 1
    assert _meta(out)["after_dirty"] == "1"


# ── 최종 리뷰 수정 ───────────────────────────────────────────────────────────


def test_not_fully_pattern_starting_with_a_dash_still_voids(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [], {"regress.not_fully": "-*PARTIAL"})
    bp_fixture.set_mode(root, "partial")
    assert run(base, root, tmp_path / "out", root=root) == 3


def test_wrapper_that_cannot_execute_is_a_config_error_not_red(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    (root / "bin" / "side.sh").write_text("echo 샤뱅 없음\n")  # 실행 권한은 있지만 exec 불가
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "run", str(base), str(root), str(out)],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 2, r.stderr
    assert (out / "EXIT").read_text() == "2\n"


def test_out_that_is_a_regular_file_is_a_config_error(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    out = tmp_path / "out"
    out.write_text("")
    assert run(base, root, out, root=root) == 2


def test_unexpected_exception_is_void_not_red(tmp_path):
    root, base = bp_fixture.make_host(tmp_path, [], [])
    profile = root / ".claude" / "bugfix-pipeline.json"
    profile.chmod(0o000)  # load() 의 read_text 가 PermissionError — 아무 분기도 예상하지 않은 예외
    out = tmp_path / "out"
    out.mkdir()
    try:
        assert run(base, root, out, root=root) == 3
        assert (out / "EXIT").read_text() == "3\n"
    finally:
        profile.chmod(0o644)
