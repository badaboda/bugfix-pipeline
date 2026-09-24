"""bugfix-pipeline 귀속 진리표 — spec §5 의 여섯 줄을 전수로 고정한다.

앵커는 개별 값이 아니라 불변식이다: 「어느 행이 FAIL 했는가」만으로 귀속과
cap 증분이 결정되고, 그 매핑에 LLM 판단이 끼어들 자리가 없다.
"""
import pytest

from scripts.bugfix_verdict import Attribution, verdict


def test_all_pass_is_pass_and_does_not_burn_cap():
    v = verdict(probe_ok=True, control=True, cause=True, symptom=True, regress=True)
    assert v.attribution is Attribution.PASS
    assert v.cap_delta == 0


def test_control_fail_voids_the_whole_verdict():
    # 양성 대조가 빨개지지 않으면 나머지 판정은 PASS 든 FAIL 이든 믿을 수 없다.
    v = verdict(probe_ok=True, control=False, cause=None, symptom=None, regress=None)
    assert v.attribution is Attribution.VOID
    assert v.cap_delta == 0


def test_control_fail_outranks_a_failing_cause():
    # 순서가 중요하다: 측정이 무효인데 CODE 로 세면 예산을 태운다.
    v = verdict(probe_ok=True, control=False, cause=False, symptom=False, regress=False)
    assert v.attribution is Attribution.VOID
    assert v.cap_delta == 0


def test_cause_fail_is_code_and_burns_cap():
    v = verdict(probe_ok=True, control=True, cause=False, symptom=None, regress=None)
    assert v.attribution is Attribution.CODE
    assert v.cap_delta == 1


def test_cause_pass_but_symptom_fail_is_anchor_and_does_not_burn_cap():
    # 드리프트 탐지기: 코드는 기준을 넘었는데 사용자 문제가 남았다 = 기준이 틀렸다.
    v = verdict(probe_ok=True, control=True, cause=True, symptom=False, regress=None)
    assert v.attribution is Attribution.ANCHOR
    assert v.cap_delta == 0


def test_regress_fail_is_code_and_burns_cap():
    v = verdict(probe_ok=True, control=True, cause=True, symptom=True, regress=False)
    assert v.attribution is Attribution.CODE
    assert v.cap_delta == 1


def test_probe_failure_is_env_and_outranks_everything():
    v = verdict(probe_ok=False, control=None, cause=None, symptom=None, regress=None)
    assert v.attribution is Attribution.ENV
    assert v.cap_delta == 0


def test_probe_failure_outranks_a_passing_control():
    v = verdict(probe_ok=False, control=True, cause=True, symptom=True, regress=True)
    assert v.attribution is Attribution.ENV


@pytest.mark.parametrize(
    "kwargs",
    [
        {"probe_ok": True, "control": None, "cause": True, "symptom": True, "regress": True},
        {"probe_ok": True, "control": True, "cause": None, "symptom": True, "regress": True},
        {"probe_ok": True, "control": True, "cause": True, "symptom": None, "regress": True},
        {"probe_ok": True, "control": True, "cause": True, "symptom": True, "regress": None},
    ],
)
def test_unevaluated_row_needed_for_the_decision_raises(kwargs):
    # 「측정 안 했다」를 「FAIL」로 읽으면 0 과 초록을 혼동하는 것과 같은 병이다.
    with pytest.raises(ValueError):
        verdict(**kwargs)


def test_reason_is_present_for_every_outcome():
    for kwargs in (
        {"probe_ok": False, "control": None, "cause": None, "symptom": None, "regress": None},
        {"probe_ok": True, "control": False, "cause": None, "symptom": None, "regress": None},
        {"probe_ok": True, "control": True, "cause": False, "symptom": None, "regress": None},
        {"probe_ok": True, "control": True, "cause": True, "symptom": False, "regress": None},
        {"probe_ok": True, "control": True, "cause": True, "symptom": True, "regress": False},
        {"probe_ok": True, "control": True, "cause": True, "symptom": True, "regress": True},
    ):
        assert verdict(**kwargs).reason


@pytest.mark.parametrize("probe_ok", [True, False])
@pytest.mark.parametrize("control", [True, False, None])
@pytest.mark.parametrize("cause", [True, False, None])
@pytest.mark.parametrize("symptom", [True, False, None])
@pytest.mark.parametrize("regress", [True, False, None])
def test_cap_is_one_only_for_code_across_the_whole_input_space(
    probe_ok, control, cause, symptom, regress
):
    """cap 불변식을 입력 공간 «전수»로 고정한다 — 사례 열거가 아니다.

    「cap 은 CODE 만 센다」가 이 진리표의 가장 load-bearing 한 계약이고,
    6줄 밖의 조합이 새면 나쁜 기준이 예산을 태운다. ValueError 경로는
    판정을 내지 않으므로 불변식 대상이 아니다.
    """
    try:
        v = verdict(
            probe_ok=probe_ok, control=control, cause=cause,
            symptom=symptom, regress=regress,
        )
    except ValueError:
        return
    assert v.cap_delta == (1 if v.attribution is Attribution.CODE else 0)
    assert v.cap_delta in (0, 1)
    assert v.reason
