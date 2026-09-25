"""bugfix-pipeline 화면 서버 — 프로파일 ui.serve_cmd 로 «주어진 트리»의 앱을 띄우고 URL 을 얻는다.

  python3 scripts/bp_ui.py check [트리] [--root 호출 루트]   # 띄워 보고 URL 을 찍고 내린다
  python3 scripts/bp_ui.py --selftest

계약: <serve_cmd…> <트리> — cwd 는 호출 루트. 듣기 시작한 뒤 stdout 에 ready_marker 에 걸리는 줄
BP_URL=<url> 을 한 번 낸다. 끝나면 프로세스 «그룹»에 SIGTERM, 10 초 뒤 SIGKILL.
설계: docs/superpowers/specs/2026-09-25-skill-v1-design.md §4
"""
from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bp_profile  # noqa: E402

URL_PREFIX = "BP_URL="
STOP_GRACE_S = 10


class UiError(Exception):
    pass


def _matches(pattern, line) -> bool:
    # 프로파일 검사와 같은 엔진(grep -E) — 파이썬 re 와 문법이 다르다
    r = subprocess.run(["grep", "-qE", "-e", pattern], input=line.encode(errors="replace"), capture_output=True)
    return r.returncode == 0


def _group_alive(pgid) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop(proc):
    """리더가 이미 끝났어도 그룹은 남을 수 있다(서버를 백그라운드로 둔 래퍼) — 그룹이 빌 때까지 내린다."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        proc.wait()
        return
    deadline = time.monotonic() + STOP_GRACE_S
    while time.monotonic() < deadline:
        proc.poll()
        if not _group_alive(proc.pid):
            break
        time.sleep(0.05)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def _wait_ready(lines, ui, proc):
    deadline = time.monotonic() + ui.ready_timeout_s
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise UiError(f"준비 신호가 {ui.ready_timeout_s}초 안에 오지 않았다")
        try:
            line = lines.get(timeout=min(left, 0.2))
        except queue.Empty:
            # 자식이 stdout 을 쥐면 EOF 가 안 온다 — 리더의 비정상 종료로 가른다(exit 0 은 백그라운드로 둔 래퍼)
            if proc.poll() not in (None, 0):
                raise UiError(f"serve_cmd 가 준비 전에 끝났다 (exit {proc.returncode})")
            continue
        if line is None:
            raise UiError(f"serve_cmd 가 준비 전에 끝났다 (exit {proc.wait()})")
        text = line.rstrip("\n")
        if _matches(ui.ready_marker, text):
            if URL_PREFIX not in text or not text.split(URL_PREFIX, 1)[1].strip():
                raise UiError(f"준비 줄에 {URL_PREFIX}<url> 이 없다: {text!r}")
            return text.split(URL_PREFIX, 1)[1].strip()


@contextmanager
def serve(profile, tree, log_path):
    """그 트리로 앱을 띄우고 URL 을 준다. 블록을 나오면(예외 포함) 프로세스 그룹을 내린다."""
    if profile.ui is None:
        raise UiError("프로파일에 ui 섹션이 없다 — 화면을 띄울 수 없다")
    ui = profile.ui
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [*ui.serve_cmd, str(tree)], cwd=str(profile.root), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True, text=True, errors="replace",
        )
    except OSError as e:
        log.close()
        raise UiError(f"serve_cmd 를 실행할 수 없다: {e}")
    lines = queue.Queue()

    def pump():
        for line in proc.stdout:
            log.write(line)
            log.flush()
            lines.put(line)
        lines.put(None)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        yield _wait_ready(lines, ui, proc)
    finally:
        _stop(proc)
        t.join(timeout=5)
        log.close()


def _check(tree, root) -> int:
    try:
        root = Path(root) if root else bp_profile.toplevel(Path.cwd())
        profile = bp_profile.load(root)
        with tempfile.TemporaryDirectory() as tmp:
            with serve(profile, Path(tree or root).resolve(), Path(tmp) / "serve.log") as url:
                print(f"ui OK — {url}")
    except (bp_profile.ProfileError, UiError) as e:
        print(f"ui FAIL: {e}", file=sys.stderr)
        return 2
    return 0


def _selftest() -> int:
    import urllib.request
    import bp_fixture
    failures = []
    url = None
    with tempfile.TemporaryDirectory() as tmp:
        root = bp_fixture.make_root(tmp, bp_fixture.UI_OVERRIDES)
        (root / "value.txt").write_text("ok\n")
        profile = bp_profile.load(root)
        try:
            with serve(profile, root, Path(tmp) / "serve.log") as url:
                if urllib.request.urlopen(url + "/value.txt", timeout=5).read() != b"ok\n":
                    failures.append("트리의 파일을 서빙하지 않는다")
        except UiError as e:
            failures.append(f"띄우지 못했다: {e}")
        if url:
            try:
                urllib.request.urlopen(url, timeout=2)
                failures.append("블록을 나온 뒤에도 서버가 살아 있다")
            except OSError:
                pass
    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("selftest OK — 트리 서빙 · 종료 후 포트 닫힘")
    return 0


def main(argv) -> int:
    if argv == ["--selftest"]:
        return _selftest()
    p = argparse.ArgumentParser(prog="bp_ui.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check")
    s.add_argument("tree", nargs="?")
    s.add_argument("--root")
    try:
        a = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    return _check(a.tree, a.root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
