"""셸 스크립트 — regress.sh · watch.sh. 이 파일 전에는 pytest 에서 부르는 곳이 없었다(호출자 0)."""
import os
import re
import selectors
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGRESS_SH = REPO / "scripts" / "regress.sh"
WATCH_SH = REPO / "scripts" / "watch.sh"


def _sh(*args, **kw):
    return subprocess.run(["sh", *map(str, args)], capture_output=True, text=True, **kw)


def test_regress_selftest_passes():
    r = _sh(REGRESS_SH, "selftest")
    assert r.returncode == 0, r.stderr
    assert "selftest OK" in r.stdout


def _declared_codes():
    line = next(l for l in REGRESS_SH.read_text(encoding="utf-8").splitlines() if l.startswith("# 종료코드"))
    return {int(c) for c in re.findall(r"(\d+) =", line)}


def test_regress_every_exit_code_it_can_return_is_declared():
    # 원천 실측: 선언되지 않은 exit 2 로 끝나 호출자가 「무슨 뜻인지」를 몰랐다
    seen = {_sh(REGRESS_SH, "diff", "a", "b").returncode, _sh(REGRESS_SH, "bogus").returncode}
    assert seen == {2}
    assert seen <= _declared_codes(), f"선언 {_declared_codes()} · 실제 {seen}"


class _Watch:
    """watch.sh 를 1초 간격으로 띄우고 stdout 줄을 기한 안에 읽는다."""

    def __init__(self, ws, done_file, mins="10"):
        env = {**os.environ, "BP_WATCH_INTERVAL": "1"}
        self.p = subprocess.Popen(["sh", str(WATCH_SH), str(ws), done_file, mins],
                                  stdout=subprocess.PIPE, text=True, env=env)
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.p.stdout, selectors.EVENT_READ)

    def line(self, timeout=10):
        if not self.sel.select(timeout):
            raise AssertionError("watch.sh 가 기한 안에 아무것도 내지 않았다")
        return self.p.stdout.readline().rstrip("\n")

    def close(self):
        self.p.kill()
        self.p.wait()


def test_watch_reports_each_new_progress_line(tmp_path):
    # 원천 실측: P1~P3 가 조용히 돌아 사용자가 «왜 오래 걸려»를 여러 번 물었다 — 리더는 mtime 으로 추정했다
    w = _Watch(tmp_path, "-")
    try:
        (tmp_path / "progress.log").write_text("12:01 P1 재현 확인 · 남은 예상 10분\n")
        assert w.line() == "PROGRESS 12:01 P1 재현 확인 · 남은 예상 10분"
        with open(tmp_path / "progress.log", "a") as f:
            f.write("12:06 P1 경계 관측 · 남은 예상 5분\n")
        assert w.line() == "PROGRESS 12:06 P1 경계 관측 · 남은 예상 5분"
    finally:
        w.close()


def test_watch_done_still_ends_the_watch(tmp_path):
    (tmp_path / "investigation.md").write_text("x")
    w = _Watch(tmp_path, "investigation.md")
    try:
        assert w.line() == "DONE investigation.md"
        assert w.p.wait(timeout=5) == 0
    finally:
        w.close()


def test_watch_stall_names_the_last_progress(tmp_path):
    log = tmp_path / "progress.log"
    log.write_text("11:00 P3 수정 · 남은 예상 3분\n")
    old = time.time() - 600
    os.utime(log, (old, old))
    w = _Watch(tmp_path, "-", mins="1")
    try:
        assert w.line().startswith("PROGRESS 11:00")
        stall = w.line()
        assert stall.startswith("STALL") and "11:00 P3 수정" in stall
    finally:
        w.close()
