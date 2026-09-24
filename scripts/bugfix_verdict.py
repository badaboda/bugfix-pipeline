"""bugfix-pipeline 의 귀속 진리표 — 결정론 판정.

루브릭 4행의 ``assert`` 종료코드를 받아 귀속과 cap 증분을 낸다. 이 매핑을
산문으로 두면 LLM 이 읽고 적용하므로 같은 증거에서 다른 결론이 나온다.
그래서 코드가 소유한다.

설계: docs/superpowers/specs/2026-09-22-bugfix-pipeline-design.md §5
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Attribution(str, Enum):
    """판정 귀속. ``SPEC`` · ``DEBT`` 는 사람이 게이트에서 가르므로 여기 없다."""

    PASS = "PASS"
    VOID = "VOID"
    CODE = "CODE"
    ANCHOR = "ANCHOR"
    ENV = "ENV"


@dataclass(frozen=True)
class Verdict:
    attribution: Attribution
    cap_delta: int
    reason: str


def _require(name: str, value: bool | None) -> bool:
    if value is None:
        raise ValueError(
            f"{name} 이 평가되지 않았다 — 이 판정에 필요한 행이다. "
            "「측정 안 했다」를 FAIL 로 읽지 않는다."
        )
    return value


def verdict(
    *,
    probe_ok: bool,
    control: bool | None,
    cause: bool | None,
    symptom: bool | None,
    regress: bool | None,
) -> Verdict:
    """루브릭 4행의 결과 → 귀속 + cap 증분.

    각 인자: ``True`` = assert exit 0(PASS), ``False`` = exit≠0(FAIL),
    ``None`` = 평가되지 않음. 결정에 필요한 행이 ``None`` 이면 ``ValueError``.

    cap 은 ``CODE`` 만 센다. ``ANCHOR`` · ``ENV`` · ``VOID`` 는 구현 실패가
    아니므로 예산을 태우면 나쁜 기준이 원인을 끝까지 안 고치게 만든다.
    """
    if not probe_ok:
        return Verdict(Attribution.ENV, 0, "probe 실행 실패 — 스택·데이터·계정 상태")

    if not _require("R-CONTROL", control):
        return Verdict(
            Attribution.VOID, 0, "양성 대조가 빨개지지 않았다 — 측정이 대상을 안 본다"
        )

    if not _require("R-CAUSE", cause):
        return Verdict(Attribution.CODE, 1, "기준은 옳고 구현이 덜 됐다")

    if not _require("R-SYMPTOM", symptom):
        return Verdict(
            Attribution.ANCHOR,
            0,
            "코드는 기준을 넘었는데 문제가 남았다 — 기준이 틀렸다",
        )

    if not _require("R-REGRESS", regress):
        return Verdict(Attribution.CODE, 1, "옆을 깼다")

    return Verdict(Attribution.PASS, 0, "4행 전부 통과")


# ── 의존 0 자체검사 ──────────────────────────────────────────────────────────
#
# 🔴 왜 pytest 가 아니라 이것이 필요한가 (실측 2026-09-22):
# 이 파일은 «임의의 호스트 프로젝트»에 설치된다. 그 프로젝트에 pytest 가
# 있다고 가정할 수 없다 — 실제로 이 랩탑 호스트 python3 에 없었다.
# 그런데 이 파이프라인의 결정론 전체가 이 진리표 위에 서 있으므로,
# «그 프로젝트에서» 진리표가 옳게 도는지 증명할 길이 있어야 한다.
#
#   python3 scripts/bugfix_verdict.py --selftest
#
# P0 가 이것을 선행 조건으로 부른다. 부르지 않으면 이 검사는 ①이 아니라 ③이다.
# 플러그인 레포의 pytest 스위트(tests/)는 개발용이고, 이것은 «설치처»용이다.

_CASES = [
    # (probe_ok, control, cause, symptom, regress) -> (attribution, cap_delta)
    ((False, None, None, None, None), ("ENV", 0)),
    ((False, True, True, True, True), ("ENV", 0)),
    ((True, False, None, None, None), ("VOID", 0)),
    ((True, False, False, False, False), ("VOID", 0)),
    ((True, True, False, None, None), ("CODE", 1)),
    ((True, True, True, False, None), ("ANCHOR", 0)),
    ((True, True, True, True, False), ("CODE", 1)),
    ((True, True, True, True, True), ("PASS", 0)),
]

_MUST_RAISE = [
    (True, None, True, True, True),
    (True, True, None, True, True),
    (True, True, True, None, True),
    (True, True, True, True, None),
]


def _selftest() -> int:
    """진리표 전수 + ValueError 경로를 검사한다. 0 = 통과, 1 = 실패."""
    failures = []

    for args, (want_attr, want_cap) in _CASES:
        probe_ok, control, cause, symptom, regress = args
        got = verdict(
            probe_ok=probe_ok,
            control=control,
            cause=cause,
            symptom=symptom,
            regress=regress,
        )
        if got.attribution.value != want_attr or got.cap_delta != want_cap:
            failures.append(
                f"{args} -> {got.attribution.value}/{got.cap_delta} "
                f"(기대 {want_attr}/{want_cap})"
            )
        if not got.reason:
            failures.append(f"{args} -> reason 이 비었다")

    for args in _MUST_RAISE:
        probe_ok, control, cause, symptom, regress = args
        try:
            verdict(
                probe_ok=probe_ok,
                control=control,
                cause=cause,
                symptom=symptom,
                regress=regress,
            )
        except ValueError:
            continue
        failures.append(f"{args} -> ValueError 가 안 났다 (「안 쟀다」를 FAIL 로 읽었다)")

    # cap 불변식: 1 은 CODE 에만 붙는다.
    for args, (want_attr, want_cap) in _CASES:
        if want_cap == 1 and want_attr != "CODE":
            failures.append(f"cap 불변식 위반: {want_attr} 에 cap 1")

    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"selftest OK — {len(_CASES)}개 진리표 행 + {len(_MUST_RAISE)}개 ValueError 경로")
    return 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print("사용법: python3 bugfix_verdict.py --selftest", file=sys.stderr)
    sys.exit(2)
