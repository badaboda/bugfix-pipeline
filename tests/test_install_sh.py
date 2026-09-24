"""hooks/install.sh — core.hooksPath 레포에서 작업 트리에 파일을 흘리지 않는다 (스펙 §8 실측)."""
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "hooks" / "install.sh"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _repo(path, hooks_path=None, existing_hook=False):
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "fix/a")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    if hooks_path:
        _git(path, "config", "core.hooksPath", hooks_path)
        (path / hooks_path).mkdir()
        if existing_hook:
            hook = path / hooks_path / "commit-msg"
            hook.write_text("#!/bin/sh\nexit 0\n")
            hook.chmod(0o755)
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def _install(cwd):
    return subprocess.run(["sh", str(INSTALL), "install"], cwd=cwd, capture_output=True, text=True)


def test_plain_repo_installs_into_git_hooks(tmp_path):
    repo = _repo(tmp_path / "r")
    assert _install(repo).returncode == 0
    assert (repo / ".git" / "hooks" / "commit-msg").is_file()


def test_hooks_path_inside_the_worktree_is_refused_without_writing(tmp_path):
    repo = _repo(tmp_path / "r", hooks_path=".husky")
    r = _install(repo)
    assert r.returncode == 1 and "작업 트리 안" in r.stderr
    assert not (repo / ".husky" / "commit-msg").exists()
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_existing_hook_is_still_not_overwritten(tmp_path):
    repo = _repo(tmp_path / "r", hooks_path=".husky", existing_hook=True)
    r = _install(repo)
    assert r.returncode == 1
    assert (repo / ".husky" / "commit-msg").read_text() == "#!/bin/sh\nexit 0\n"


def test_linked_worktree_still_installs(tmp_path):
    repo = _repo(tmp_path / "r")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "fix/b", str(wt))
    assert _install(wt).returncode == 0


def test_install_via_symlinked_path_is_not_refused(tmp_path):
    repo = _repo(tmp_path / "real" / "r")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    assert _install(link / "r").returncode == 0
