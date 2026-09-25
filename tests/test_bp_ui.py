"""bp_ui — 주어진 트리로 앱을 띄우고 URL 을 얻는다."""
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bp_fixture  # noqa: E402
import bp_profile  # noqa: E402
import bp_ui  # noqa: E402


def _profile(tmp_path, **ui):
    overrides = dict(bp_fixture.UI_OVERRIDES)
    overrides.update({f"ui.{k}": v for k, v in ui.items()})
    root = bp_fixture.make_root(tmp_path, overrides)
    return root, bp_profile.load(root)


def _script(root, name, text):
    p = root / "bin" / name
    p.write_text(text)
    p.chmod(0o755)
    return f"bin/{name}"


def test_serves_the_given_tree(tmp_path):
    root, profile = _profile(tmp_path)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "value.txt").write_text("from-tree\n")
    with bp_ui.serve(profile, tree, tmp_path / "serve.log") as url:
        assert urllib.request.urlopen(url + "/value.txt", timeout=5).read() == b"from-tree\n"


def test_server_is_stopped_after_the_block(tmp_path):
    root, profile = _profile(tmp_path)
    with bp_ui.serve(profile, root, tmp_path / "serve.log") as url:
        pass
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=2)


def test_ready_timeout_is_an_error_and_kills_the_process(tmp_path):
    root, _ = _profile(tmp_path)
    cmd = _script(root, "silent.sh", "#!/bin/sh\nsleep 30\n")
    bp_fixture.write_profile(root, {**bp_fixture.UI_OVERRIDES, "ui.serve_cmd": [cmd], "ui.ready_timeout_s": 1})
    start = time.monotonic()
    with pytest.raises(bp_ui.UiError, match="오지 않았다"):
        with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log"):
            pass
    assert time.monotonic() - start < 10


def test_server_exiting_before_ready_fails_fast(tmp_path):
    root, _ = _profile(tmp_path)
    cmd = _script(root, "dies.sh", "#!/bin/sh\necho boom\nexit 3\n")
    bp_fixture.write_profile(root, {**bp_fixture.UI_OVERRIDES, "ui.serve_cmd": [cmd], "ui.ready_timeout_s": 60})
    start = time.monotonic()
    with pytest.raises(bp_ui.UiError, match="끝났다"):
        with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log"):
            pass
    assert time.monotonic() - start < 10
    assert "boom" in (tmp_path / "serve.log").read_text()


def test_ready_line_without_url_is_an_error(tmp_path):
    root, _ = _profile(tmp_path)
    cmd = _script(root, "noready.sh", "#!/bin/sh\necho READY\nsleep 30\n")
    bp_fixture.write_profile(root, {"ui.serve_cmd": [cmd], "ui.ready_marker": "^READY"})
    with pytest.raises(bp_ui.UiError, match="BP_URL="):
        with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log"):
            pass


def test_no_ui_section_is_an_error(tmp_path):
    root = bp_fixture.make_root(tmp_path)
    with pytest.raises(bp_ui.UiError):
        with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log"):
            pass


def test_check_cli(tmp_path, capsys):
    root, _ = _profile(tmp_path)
    assert bp_ui.main(["check", str(root), "--root", str(root)]) == 0
    assert "ui OK" in capsys.readouterr().out


def test_child_processes_of_the_server_are_stopped(tmp_path):
    # sh 가 python 을 «자식»으로 띄운다(exec 없음) — 그룹을 내려야 포트가 닫힌다
    root, _ = _profile(tmp_path)
    cmd = _script(root, "wrapped.sh", bp_fixture.SERVE_SH.replace("exec python3", "python3"))
    bp_fixture.write_profile(root, {**bp_fixture.UI_OVERRIDES, "ui.serve_cmd": [cmd]})
    with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log") as url:
        pass
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=2)


def test_server_left_by_an_exiting_wrapper_is_stopped(tmp_path):
    # 래퍼가 서버를 백그라운드로 두고 먼저 끝난다(exit 0) — 리더가 죽어도 그룹은 남는다(A3 리뷰 실측)
    root, _ = _profile(tmp_path)
    cmd = _script(root, "daemon.sh", bp_fixture.SERVE_SH.replace("exec python3", "python3")
                  .replace('"$1"\n', '"$1" &\nexit 0\n'))
    bp_fixture.write_profile(root, {**bp_fixture.UI_OVERRIDES, "ui.serve_cmd": [cmd]})
    with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log") as url:
        assert urllib.request.urlopen(url, timeout=5)
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=2)


def test_wrapper_failing_while_a_child_holds_stdout_fails_fast(tmp_path):
    # 자식이 stdout 을 쥐고 있으면 EOF 가 오지 않는다 — 리더의 비정상 종료로 즉시 실패하고 자식도 내린다
    import os
    root, _ = _profile(tmp_path)
    pidfile = tmp_path / "child.pid"
    cmd = _script(root, "fails.sh", f"#!/bin/sh\nsleep 30 &\necho $! > {pidfile}\necho boom\nexit 3\n")
    bp_fixture.write_profile(root, {**bp_fixture.UI_OVERRIDES, "ui.serve_cmd": [cmd], "ui.ready_timeout_s": 60})
    start = time.monotonic()
    with pytest.raises(bp_ui.UiError, match="끝났다"):
        with bp_ui.serve(bp_profile.load(root), root, tmp_path / "serve.log"):
            pass
    assert time.monotonic() - start < 10
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
