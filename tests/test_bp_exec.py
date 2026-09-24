"""exec 계약 — 기본값(bp_exec_local)과 프로파일 exec_cmd 가 같은 모양의 argv 를 낸다."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
import bp_profile  # noqa: E402


def _run(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def test_default_exec_runs_the_command_inside_the_tree(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    tree = tmp_path / "tree"
    tree.mkdir()
    argv = bp_profile.exec_argv(bp_profile.load(root), tree, ["pwd"])
    r = _run(argv, root)
    assert r.returncode == 0 and Path(r.stdout.strip()).resolve() == tree.resolve()


def test_default_exec_passes_the_exit_code_through(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), root, ["sh", "-c", "exit 7"])
    assert _run(argv, root).returncode == 7


def test_default_exec_missing_tree_is_125(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), tmp_path / "nope", ["true"])
    assert _run(argv, root).returncode == 125


def test_default_exec_missing_command_is_125(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    argv = bp_profile.exec_argv(bp_profile.load(root), root, ["no-such-command-bp"])
    assert _run(argv, root).returncode == 125


def test_profile_exec_cmd_gets_tree_and_separator(tmp_path):
    root = bp_fixture.make_root(tmp_path, {"exec.exec_cmd": ["bin/side.sh", "--flag"]})
    p = bp_profile.load(root)
    assert bp_profile.exec_argv(p, root, ["pytest", "-q"]) == [
        str(root / "bin" / "side.sh"), "--flag", str(root), "--", "pytest", "-q",
    ]
