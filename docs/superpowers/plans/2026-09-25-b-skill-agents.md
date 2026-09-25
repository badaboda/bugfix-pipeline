# 계획 B — `SKILL.md` · 에이전트 6종 · 계약 린트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설치하면 실제로 호출되는 파이프라인 — `skills/bugfix-pipeline/SKILL.md` 가 트리아지 · 두 트랙을 `bp_gate.py` 명령으로 몰고, 번들 에이전트 6종이 한 모양의 배정 계약으로 일한다. 문서가 코드와 어긋나면 계약 린트가 빨개진다.

**Architecture:** 판정 규칙은 이미 `bp_gate.py` 에 있다(계획 A). 이 계획은 «누가 언제 어떤 명령을 부르고 어디서 멈추나»만 문서로 쓴다 — 코드로 간 규칙은 한 줄 요약 + 명령. 문서의 파일명 · 명령 · 표지 · 에이전트 이름은 `tests/test_contracts.py` 가 `bp_gate` 상수와 대조한다(① 집행 코드 자리).

**Tech Stack:** Markdown(frontmatter) · Python 3.9 표준 라이브러리 + pytest(린트는 개발용)

**Spec:** `docs/superpowers/specs/2026-09-25-skill-v1-design.md` §3 · §7 · §9 · §12 · §13(계약 린트)

## Global Constraints

- 공개 레포 — 원천 프로젝트 내부(컨테이너 이름 · 포트 · 슬롯 · 사내 경로) 금지. 커밋 전 스캔.
- 이식 가능 — Docker · 특정 테스트 러너 · 특정 브라우저 스킬을 가정하지 않는다. 측정은 `exec_cmd`(`{exec}`)로만.
- 본문 한국어 · `description` 트리거는 영어·한국어 둘 다(§12).
- 에이전트 frontmatter: `name`(= 파일 이름) · `description` · `model`.
- 절대경로 · 한 번에 한 명령 · 경로 지정 커밋 · TDD(린트 먼저 빨강) · 양성 대조.

## 설계 세부 (이 계획의 Ruling)

| 항목 | 결정 | 이유 |
|---|---|---|
| 스크립트 위치 | SKILL.md 가 «이 스킬의 기준 디렉토리(Base directory)»의 두 단계 위를 플러그인 루트로 쓴다 — `BP=<루트>/scripts` | 스킬 로드 시 기준 디렉토리가 주어지는 것을 이 세션에서 관측했다. 환경 변수 치환은 확인하지 않았다 |
| 에이전트 호출 | `subagent_type: bugfix-pipeline:<이름>` | 플러그인 에이전트는 `plugin:agent` 로 네임스페이스된다(CLAUDE.md 레이아웃 근거) |
| 모델 | 판단형(조사자 · RED · GREEN · 스윕 게이트 · 가벼운 수정자) `opus`, 스위퍼 `sonnet` | 스위퍼는 기계적 대조, 나머지는 판단 |
| 린트 범위 | 명령 · 작업공간 파일명 · 표지 · 에이전트 이름 · 트리거 두 언어 · 원천 결합어 금지 · 배정 계약 키 | 스펙 §13 + 「하드코딩 발견 시 프로파일로」를 코드로 |
| 린트 허용 파일명 | `bp_gate` 상수 + 에이전트 전용 산출물(`investigation.md` · `sweep.json` · `sweep.md` · `gate_round<N>.md` · `control/*.diff` · `verdict_<n>.json` · `.claude/bugfix-pipeline.json`)을 테스트에 명시 | 목록 밖 이름(예: `rubric.yaml`)은 stale 문서다 |

## Review Focus

1. **문서가 없는 명령을 부른다** — 린트가 `bp_gate.py <cmd>` 를 `COMMANDS` 와 대조 (Task 1 `test_docs_only_call_real_gate_commands`)
2. **SKILL.md 가 어떤 명령을 빠뜨린다** — 12종 전부 등장 (Task 1 `test_skill_covers_every_gate_command`)
3. **원천 결합이 새어 든다**(슬롯 · `docker exec` · `webapp-testing` · `rubric.yaml`) (Task 1 `test_no_source_project_coupling`)
4. **린트가 아무것도 안 읽는다**(0 이 답이 아니다) — 문서 수 · 명령 등장 수 하한 (Task 1 `test_lint_reads_something`)
5. **에이전트가 «검증했다»로 표지를 지운다** — 가벼운 수정자 문서가 `light-verify` 를 부르지 않고 «검증은 코드» 규칙을 담는다 (Task 2 `test_light_fixer_leaves_verification_to_code`)

---

### Task 1: 계약 린트 — `tests/test_contracts.py` (빨강 먼저)

**Files:** Create `tests/test_contracts.py`

**Interfaces:**
- Consumes: `bp_gate.COMMANDS` · 파일 상수(`LEDGER` … `PR_BODY`) · `LABEL_*`
- Produces: 테스트 모듈 상수 `AGENTS`(6 이름) · `AGENT_OUTPUTS` — Task 2·3 의 문서가 이것을 만족해야 한다

- [ ] **Step 1: 테스트 작성**

```python
"""계약 린트 — SKILL.md · 에이전트 문서가 bp_gate 코드와 어긋나면 빨개진다(스펙 §13)."""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import bp_gate  # noqa: E402

SKILL = REPO / "skills" / "bugfix-pipeline" / "SKILL.md"
AGENTS = ("bug-root-cause-investigator", "bug-red-writer", "bug-green-engineer",
          "bug-cta-sweeper", "bug-sweep-gate", "bug-light-fixer")
FORMAL_AGENTS = AGENTS[:5]
GATE_FILES = {bp_gate.LEDGER, bp_gate.REPRO_MD, bp_gate.REPRO_SH, bp_gate.ROOT_CAUSE, bp_gate.RUBRIC,
              bp_gate.LIGHT_CAUSE, bp_gate.LIGHT_REPORT, bp_gate.PR_BODY}
AGENT_OUTPUTS = {"investigation.md", "sweep.json", "sweep.md", "gate_round<N>.md", "control/*.diff",
                 "verdict_<n>.json", ".claude/bugfix-pipeline.json", "SKILL.md"}
LABELS = (bp_gate.LABEL_NO_DETERMINISM, bp_gate.LABEL_NO_REGRESS, bp_gate.LABEL_NO_BASELINE_REPRO)
COUPLING = re.compile(r"슬롯|\bslot\b|docker exec|webapp-testing|nginx|rubric\.yaml|\bqueue\b", re.I)
_FILE_TOKEN = re.compile(r"`([^`\s]+\.(?:json|md|sh|diff))`")
_GATE_CALL = re.compile(r"bp_gate\.py\s+([a-z][a-z-]*)")


def _doc(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name}: frontmatter 가 없다"
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, text


def _all_docs():
    return [SKILL] + [REPO / "agents" / f"{a}.md" for a in AGENTS]


def test_every_agent_exists_with_matching_frontmatter():
    found = sorted(p.stem for p in (REPO / "agents").glob("*.md"))
    assert found == sorted(AGENTS)
    for a in AGENTS:
        meta, _ = _doc(REPO / "agents" / f"{a}.md")
        assert meta.get("name") == a
        assert meta.get("model") in ("opus", "sonnet", "haiku", "inherit")
        assert meta.get("description")


def test_skill_frontmatter_names_the_plugin():
    meta, _ = _doc(SKILL)
    assert meta.get("name") == "bugfix-pipeline" and meta.get("description")


@pytest.mark.parametrize("path", _all_docs(), ids=lambda p: p.stem)
def test_description_triggers_are_bilingual(path):
    desc = _doc(path)[0]["description"]
    assert re.search(r"[가-힣]{2,}", desc), "한국어 트리거가 없다"
    assert re.search(r"\b[a-z]+ [a-z]+\b", desc), "영어 트리거(두 단어 이상)가 없다"


def test_docs_only_call_real_gate_commands():
    for path in _all_docs():
        for cmd in _GATE_CALL.findall(path.read_text(encoding="utf-8")):
            assert cmd in bp_gate.COMMANDS, f"{path.name}: 없는 게이트 명령 {cmd}"


def test_skill_covers_every_gate_command():
    called = set(_GATE_CALL.findall(SKILL.read_text(encoding="utf-8")))
    assert set(bp_gate.COMMANDS) - called == set()


def test_docs_name_only_known_workspace_files():
    allowed = GATE_FILES | AGENT_OUTPUTS
    for path in _all_docs():
        for name in _FILE_TOKEN.findall(path.read_text(encoding="utf-8")):
            base = name.split("/")[-1] if not name.startswith(("control/", ".claude/")) else name
            assert base in allowed, f"{path.name}: 모르는 파일명 {name}"


def test_skill_names_every_label_and_gate_file():
    text = SKILL.read_text(encoding="utf-8")
    for s in (*LABELS, bp_gate.LEDGER, bp_gate.REPRO_MD, bp_gate.REPRO_SH, bp_gate.PR_BODY, bp_gate.LIGHT_REPORT):
        assert s in text, f"SKILL.md 에 {s} 가 없다"


def test_skill_dispatches_every_agent_by_namespaced_name():
    text = SKILL.read_text(encoding="utf-8")
    for a in AGENTS:
        assert f"bugfix-pipeline:{a}" in text


def test_agents_share_one_assignment_contract():
    for a in AGENTS:
        text = (REPO / "agents" / f"{a}.md").read_text(encoding="utf-8")
        for key in ("workspace", "tree") + (("cause_id",) if a in FORMAL_AGENTS else ()):
            assert f"`{key}`" in text, f"{a}: 배정 계약 키 {key} 가 없다"


def test_producers_name_their_outputs():
    need = {"bug-root-cause-investigator": (bp_gate.ROOT_CAUSE, bp_gate.RUBRIC, "investigation.md"),
            "bug-light-fixer": (bp_gate.LIGHT_CAUSE,),
            "bug-cta-sweeper": ("sweep.json", "sweep.md"),
            "bug-sweep-gate": ("gate_round<N>.md",)}
    for a, files in need.items():
        text = (REPO / "agents" / f"{a}.md").read_text(encoding="utf-8")
        for f in files:
            assert f"`{f}`" in text, f"{a}: 산출물 {f} 가 없다"


def test_no_source_project_coupling():
    for path in _all_docs():
        hit = COUPLING.search(path.read_text(encoding="utf-8"))
        assert not hit, f"{path.name}: 원천 결합어 {hit.group(0)!r}"


def test_lint_reads_something():
    # 0 은 질문이다 — 정규식이 아무것도 못 잡으면 위 검사들이 공허하게 초록이 된다
    skill = SKILL.read_text(encoding="utf-8")
    assert len(_GATE_CALL.findall(skill)) >= len(bp_gate.COMMANDS)
    assert len(_FILE_TOKEN.findall(skill)) >= 5
```

- [ ] **Step 2: 빨강 확인**

Run: `uvx --with pytest pytest /Users/marcus.k/Sandbox/bugfix-pipeline/tests/test_contracts.py -q -p no:cacheprovider --rootdir /Users/marcus.k/Sandbox/bugfix-pipeline -o pythonpath=/Users/marcus.k/Sandbox/bugfix-pipeline`
Expected: FAIL — `SKILL.md` 없음(FileNotFoundError) · 에이전트 5개 없음 · 조사자 문서의 `rubric.yaml`·슬롯이 결합어로 걸림.

(커밋은 Task 3 끝에서 문서와 함께 — 빨강인 채로 main 에 가지 않게.)

### Task 2: 에이전트 6종

**Files:** Modify `agents/bug-root-cause-investigator.md` · Create `agents/bug-red-writer.md` · `agents/bug-green-engineer.md` · `agents/bug-cta-sweeper.md` · `agents/bug-sweep-gate.md` · `agents/bug-light-fixer.md` · Test `tests/test_contracts.py`(추가 1개)

**Interfaces:**
- Consumes: Task 1 의 `AGENTS` · `AGENT_OUTPUTS` · 배정 계약 키
- Produces: 에이전트 이름 6개(SKILL.md 가 `bugfix-pipeline:<이름>` 으로 부른다)

모든 에이전트 공통 뼈대(스펙 §7):

```
---
name: <이름>
description: "<한 줄 역할>. Triggers «<영어 트리거>», «<영어 트리거>» · 트리거 «<한국어>», «<한국어>». 제약=<금지 요약>."
model: <opus|sonnet>
---
# <이름> — <역할>
## 배정 계약 — `workspace`(작업공간 절대경로) · `tree`(호출 루트) · `cause_id` (가벼운 수정자는 `cause_id` 없음). 없으면 묻는다. queue·slot 없음.
## 받는 것 / 내는 것 (작업공간 직하 고정 이름)
## 측정 — `{exec}` 계약으로만: `<exec_cmd…> <트리> -- <명령…>`, 125 = 환경 실패
## 금지
## 보고 형식
```

- [ ] **Step 1: 가벼운 수정자 규칙 테스트 추가** (`tests/test_contracts.py` 끝):

```python
def test_light_fixer_leaves_verification_to_code():
    text = (REPO / "agents" / "bug-light-fixer.md").read_text(encoding="utf-8")
    assert "light-verify" in text                      # 검증은 누가 하는지 명시
    assert not _GATE_CALL.search(text)                 # 그러나 스스로 게이트를 부르지 않는다 — 리더 몫
    assert "승급" in text and "가설 하나" in text
```

- [ ] **Step 2: 빨강 확인** — 위 명령, Expected: 새 테스트 FAIL(파일 없음).

- [ ] **Step 3: 조사자 탈-프로젝트화** — `bug-root-cause-investigator.md`:
  - 배정 계약을 `workspace` · `tree` · `cause_id` + `repro.md` 로. `slot`·`worktree`·nginx/PG 제거.
  - 관측 수단에서 `docker exec`·컨테이너 로그 제거 → «`{exec}` 로 부르는 명령 · HTTP 호출 · 작업공간 안 스크립트».
  - `rubric.yaml` 절 전체를 스펙 §5 의 `rubric.json` 으로(`R-CAUSE`·`R-SYMPTOM` 의 `probe`·`assert`, `R-CONTROL.axes[]` 의 `name`·`mutate`(`patch`: `control/*.diff` 또는 `checkout`: `@baseline`)·`alive`, 자리표시자 `{exec}`·`{tree}`·`{out}`·`{repro}`·`{url}`). `R-REGRESS` 는 루브릭에 쓰지 않는다(게이트 고정 실행).
  - `root_cause.json` 에 `affected_routes`(P5b 대상) 추가.
  - 「브라우저 실측은 `webapp-testing`」 → 「브라우저 실측 도구가 있으면 그것으로, 없으면 못 잰 것에 적는다」.
  - 판정 3종 · 채우지 않는 칸(`expected_after`) · 측정 규율은 유지.
- [ ] **Step 4: `bug-red-writer.md`** — 받는 것: 동결 `root_cause.json` · `rubric.json`. 불변식을 앵커한 실패 테스트를 쓰고 `{exec}` 로 **빨강을 직접 확인**(빨강이 안 나오면 앵커부터 의심) → `test(<scope>): …` 커밋 → sha 와 RED 파일 경로를 보고(리더가 `bp_gate.py baseline` 에 쓴다 — 에이전트는 게이트를 부르지 않는다). 모호하면 `SPEC` 으로 멈춘다. 금지: production 수정 · 값 이름 앵커.
- [ ] **Step 5: `bug-green-engineer.md`** — 받는 것: 위 + RED sha. `fix_scope` 안 최소 구현 · 루프당 가설 하나 · 테스트 수정 0 · 커밋 본문 `RED: <sha>`(게이트가 감사한다 — 없으면 `run` 이 exit 2) · P4 자기 확인(RED 통과 + 전체 스위트는 `bp_regress.py run` 으로) — 자기 확인은 보고일 뿐 판정은 `run`. 커밋 안 된 변경을 남기지 않는다(`run` 이 거부).
- [ ] **Step 6: `bug-cta-sweeper.md`** — 받는 것: 기준선·수정 후 URL 두 개 · `routes` ∪ `affected_routes` · 계정 상태. 첫 단계에서 쓸 수 있는 브라우저 도구 확인 — 없으면 `sweep.md` 에 생략 사유만 쓰고 끝. 관련 CTA = 두 쪽 DOM 부분 트리 차이 또는 페이지 로드 응답 차이(스펙 §9). 관련 CTA 만 양쪽에서 누르고 비교, 비가역·외부 전송 CTA 는 렌더값 대조만. 비관련은 수정 후 로드 스모크만. 산출물 `sweep.json`(후보 목록: 페이지 · CTA · 차이 근거 · 결과) · `sweep.md`. 금지: 코드 수정 · 비가역 CTA.
- [ ] **Step 7: `bug-sweep-gate.md`** — 받는 것: `sweep.json` 의 관련 후보. 후보마다 확정·기각을 근거(두 쪽 관측)와 함께 `gate_round<N>.md` 에. 확정 회귀는 근거 파일 경로를 보고(리더가 `record-sweep --regression`). 비관련 이상은 판정하지 않고 「관찰(미판정)」으로만. 금지: 코드 수정.
- [ ] **Step 8: `bug-light-fixer.md`** — 받는 것: `repro.md` · `repro.sh`(있으면) · 트랙 기록. 원인 `파일:라인` · 루프당 가설 하나 · 가능하면 실패 테스트 먼저 · 작업 가지에 수정 커밋 · `light_cause.json`(`file`·`line`·`summary`). 승급 신호(`fix_scope` 2 파일 이상 · 공유 파일 · 첫 가설 실패 · 원인 두 갈래)가 보이면 **멈추고 보고**. 검증은 하지 않는다 — 리더가 `light-verify` 로 코드가 잰다. «검증했다»는 표지 근거가 아니다. GATE L 전 PR 금지.
- [ ] **Step 9: 초록 확인** — Task 1 명령에서 `SKILL.md` 관련 테스트만 FAIL 로 남는지 확인. Expected: 에이전트 관련 테스트 전부 PASS, `SKILL` 테스트 FAIL.

### Task 3: `skills/bugfix-pipeline/SKILL.md` · 문서 갱신 · 커밋

**Files:** Create `skills/bugfix-pipeline/SKILL.md` · Modify `README.md` · `CLAUDE.md`

- [ ] **Step 1: SKILL.md** — frontmatter `name: bugfix-pipeline`, `description` 에 영어(«fix this bug», «find the root cause and fix») · 한국어(«버그 고쳐줘», «원인 찾아서 고쳐») 트리거. 본문 순서:
  1. 선행 — 플러그인 루트 = 기준 디렉토리의 두 단계 위, `BP=<루트>/scripts`. `python3 $BP/bugfix_verdict.py --selftest` · `.gitignore` 에 `.bugfix-pipeline/` · 프로파일(선택, `bp_profile.py check`).
  2. P0 — `repro.md` 동결(`needs_ui:`·`url:` 포함) → `bp_gate.py init` → `repro.sh` 자동화 + 사용자 확인(하드 스톱) → `bp_gate.py triage [--light] [--repro-confirmed]`.
  3. 정식 트랙 P1–P6 — 단계마다 에이전트(`bugfix-pipeline:<이름>`) · 명령(`freeze` · `baseline` · `run` · `refreeze` · `record-sweep` · `status --pr-body`) · 종료코드별 다음 단계(0/1/2/3/4) · 멈춤(GATE 1 · GATE 2 · `DEFERRED`). 이관 `to-light`.
  4. 가벼운 트랙 — `bugfix-pipeline:bug-light-fixer` → `light-verify` → `light-report` → GATE L → P6. 승급 `promote`. 표지 셋의 뜻.
  5. P5b — 생략 조건과 사유 · 스위퍼 · 스윕 게이트 · `record-sweep`.
  6. P6 — `gh`/`glab` 감지, 없으면 `pr_body.md` 까지 멈춤. PR 본문은 `pr_body.md` 만. `status --close`.
  7. 리더 규율 — 배정 «직후» `watch.sh <workspace> <완료 파일>` 을 Monitor 로 · `STALL` 이면 다른 채널로 확인 · 팀원 반박은 근거가 주장을 증명하는지 · 긴 측정 전 전원 확인 · 스크린샷은 텍스트 누출 검사 밖.
  8. Lock-in (스펙 §12 목록 그대로).
  9. 어떤 종료 경로에서든 — 사본·서버 정리(게이트가 한다) · 훅을 설치했으면 `hooks/install.sh uninstall`.
- [ ] **Step 2: 초록 확인** — Task 1 명령. Expected: 전부 PASS.
- [ ] **Step 3: 양성 대조** — 각 한 번 사보타주 → 빨강 → 복원:
  - `SKILL.md` 에서 `bp_gate.py light-report` 를 전부 지운다 → `test_skill_covers_every_gate_command` 빨강
  - 에이전트 하나 description 에서 영어 트리거 제거 → 해당 파라미터 빨강
  - 조사자에 `rubric.yaml` 한 줄 → `test_docs_name_only_known_workspace_files` · `test_no_source_project_coupling` 빨강
  - `bp_gate.py frobnicate` 한 줄 → `test_docs_only_call_real_gate_commands` 빨강
- [ ] **Step 4: 문서** — README 「현재 상태」 표: SKILL.md ✅ · 에이전트 6종 ✅(조사자 탈-프로젝트화) · 계약 린트 행; 「설치」 절의 «파이프라인 자체는 호출할 수 없다» 문장을 고친다. CLAUDE.md 레이아웃에 `tests/test_contracts.py`(계약 린트).
- [ ] **Step 5: 전체 스위트 · selftest · 스캔 → 커밋**

```bash
git -C /Users/marcus.k/Sandbox/bugfix-pipeline add tests/test_contracts.py skills/bugfix-pipeline/SKILL.md agents/bug-red-writer.md agents/bug-green-engineer.md agents/bug-cta-sweeper.md agents/bug-sweep-gate.md agents/bug-light-fixer.md
git -C /Users/marcus.k/Sandbox/bugfix-pipeline commit -m "feat(skill): SKILL.md · 에이전트 6종 · 계약 린트" -- tests/test_contracts.py skills agents README.md CLAUDE.md
```

- [ ] **Step 6: 적재 확인** — `claude --plugin-dir /Users/marcus.k/Sandbox/bugfix-pipeline -p` 세션 `init` 의 에이전트·스킬 목록에 6종과 `bugfix-pipeline:bugfix-pipeline` 이 보이는지(가능하면). 못 재면 README 에 «미확인»으로.
