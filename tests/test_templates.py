"""스택 템플릿 — «기준선과 수정 후의 코드가 다른» 대조로 잰다.

루트·사본에 같은 코드를 두고 「이름이 같다」를 보는 것은 사본이 루트 코드를 새어 읽을 때도
똑같이 나온다(최종 리뷰 실측: src 레이아웃 editable 설치, npm 워크스페이스). 그래서 여기서는
기준선이 통과하고 수정 후가 실패하는 두 커밋을 만들고 bp_regress 가 1(새 빨강)을 내는지 본다.
uv·npm 이 없으면 그 통합 테스트는 건너뛴다 — 계약(125) 테스트는 도구 없이 돈다.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import bp_regress  # noqa: E402

TEMPLATES = REPO / "templates"


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True,
    )


def _install_template(root, stack, extra=None):
    dst = root / ".claude" / "bugfix-pipeline"
    dst.mkdir(parents=True)
    for name in ("bp_exec.sh", "bp_side.sh"):
        shutil.copy(TEMPLATES / stack / name, dst / name)
        (dst / name).chmod(0o755)
    data = json.loads((TEMPLATES / stack / "profile.json").read_text())
    data["regress"]["tree_marker"] = extra or "package.json"
    (root / ".claude" / "bugfix-pipeline.json").write_text(json.dumps(data))


def _exec(template_dir, root, tree, *cmd):
    return subprocess.run(
        [str(template_dir / "bp_exec.sh"), str(tree), "--", *cmd],
        cwd=str(root), capture_output=True, text=True,
    )


# ── 계약: 명령을 돌리지 못하면 125 (도구 불필요) ────────────────────────────────


@pytest.mark.parametrize("stack", ["pytest", "vitest"])
def test_missing_command_is_125(tmp_path, stack):
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    r = _exec(TEMPLATES / stack, tmp_path, tmp_path, "no-such-command-bp")
    assert r.returncode == 125, r.stderr


def test_pytest_exec_without_any_venv_is_125(tmp_path):
    r = _exec(TEMPLATES / "pytest", tmp_path, tmp_path, "true")
    assert r.returncode == 125, r.stderr


def test_vitest_exec_refuses_a_workspace_copy(tmp_path):
    root, copy = tmp_path / "root", tmp_path / "copy"
    (root / "node_modules").mkdir(parents=True)
    (root / "package.json").write_text('{"workspaces": ["packages/*"]}')
    copy.mkdir()
    (copy / "package.json").write_text('{"workspaces": ["packages/*"]}')
    r = _exec(TEMPLATES / "vitest", root, copy, "true")
    assert r.returncode == 125 and "워크스페이스" in r.stderr
    assert not (copy / "node_modules").exists()


def test_vitest_not_fully_catches_unhandled_errors(tmp_path):
    # vitest 3 이 처리되지 않은 에러를 낼 때의 머리 줄(최종 리뷰 실측 로그 형태)
    log = tmp_path / "log"
    log.write_text(
        " Test Files  1 passed (1)\n"
        "⎯⎯⎯⎯⎯⎯ Unhandled Errors ⎯⎯⎯⎯⎯⎯\n"
        "Vitest caught 1 unhandled error during the test run.\n"
    )
    pattern = json.loads((TEMPLATES / "vitest" / "profile.json").read_text())["regress"]["not_fully"]
    assert subprocess.run(["grep", "-qE", "-e", pattern, str(log)]).returncode == 0


# ── 통합: 기준선 통과 · 수정 후 실패 → 새 빨강(1) ─────────────────────────────


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 없음")
def test_pytest_template_copy_measures_its_own_code_src_layout_editable(tmp_path):
    root = tmp_path / "py"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    (root / "src" / "pkg" / "__init__.py").write_text('VALUE = "base"\n')
    (root / "tests" / "test_v.py").write_text('import pkg\n\ndef test_value():\n    assert pkg.VALUE == "base"\n')
    (root / ".gitignore").write_text(".venv/\n")
    _install_template(root, "pytest", extra="pyproject.toml")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    copy = tmp_path / "copy"
    _git(root, "worktree", "add", "-q", "--detach", str(copy), "HEAD")
    (root / "src" / "pkg" / "__init__.py").write_text('VALUE = "after"\n')
    _git(root, "commit", "-q", "-am", "after")
    subprocess.run(["uv", "venv", "-q"], cwd=root, check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", ".venv/bin/python", "-e", ".", "pytest"],
                   cwd=root, check=True)
    code = bp_regress.run(copy, root, tmp_path / "out", root=root)
    assert code == 1, (tmp_path / "out" / "base.log").read_text()[-800:]


def _npm_project(root, files):
    (root / "src").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (root / ".gitignore").write_text("node_modules/\n")


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm 없음")
def test_vitest_unhandled_error_after_the_fix_is_not_green(tmp_path):
    root = tmp_path / "vt"
    _npm_project(root, {
        "package.json": json.dumps({"name": "x", "type": "module", "private": True}),
        "vitest.config.js": "export default {}\n",
        "src/a.test.js": "import { test } from 'vitest'\ntest('a', () => {})\n",
    })
    subprocess.run(["npm", "install", "-D", "-s", "vitest@3"], cwd=root, check=True)
    _install_template(root, "vitest")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    copy = tmp_path / "copy"
    _git(root, "worktree", "add", "-q", "--detach", str(copy), "HEAD")
    (root / "src" / "a.test.js").write_text(
        "import { test } from 'vitest'\n"
        "test('a', () => { setTimeout(() => { throw new Error('boom-unhandled') }, 0) })\n"
    )
    _git(root, "commit", "-q", "-am", "after")
    code = bp_regress.run(copy, root, tmp_path / "out", root=root)
    assert code != 0, (tmp_path / "out" / "after.log").read_text()[-800:]
