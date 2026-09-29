"""셸 스크립트 — regress.sh · watch.sh. 이 파일 전에는 pytest 에서 부르는 곳이 없었다(호출자 0)."""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGRESS_SH = REPO / "scripts" / "regress.sh"


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
