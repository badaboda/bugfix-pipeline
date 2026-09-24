# SKILL v1 — 이식 가능한 버그 수정 파이프라인 설계

- 날짜: 2026-09-25
- 상태: 설계 승인됨 (구현 전)
- 선행: [프로파일 v1](2026-09-24-profile-v1-design.md) (이 스펙이 schema 2 로 확장한다)

## 1. 목적

버그 수정 요청 하나를 **원인 규명 → RED → GREEN → 판정 → 관련 범위 화면 스윕 → PR** 로 잇는 오케스트레이터를,
어떤 호스트 프로젝트에도 설치될 수 있는 형태로 만든다. 핵심 성질은 원천과 같다 — **통과 기준을 수정이 존재하기 전에
동결하고, 판정은 LLM 이 아니라 종료코드와 진리표가 낸다.**

원천(특정 프로젝트의 in-repo 스킬)에서 바뀌는 것:

| 원천 | v1 |
|---|---|
| 판정 절차(행 순서·중단·인자 매핑·cap)를 산문으로 규정하고 게이트 에이전트가 전사 | **`bp_gate.py` 가 집행** — 게이트 에이전트 없음 |
| 사본 측정 환경을 조리법 산문으로 | 프로파일 `exec_cmd` 래퍼 |
| 슬롯(포트 이름)을 리더가 배정 | `serve_cmd` 래퍼가 «주어진 트리»로 화면을 띄움 |
| P5b 전수 스윕 | **관련 범위** — 기준선·수정 후의 관측 차이로 선정 |
| `rubric.yaml` | `rubric.json` (호스트 python 3.9 표준 라이브러리에 YAML 파서 없음) |
| 재진입 정본 = 프로젝트 문서 한 줄 | `ledger.json` |
| 에이전트 7종(빌려 씀, 계약 두 모양) | 5종(번들, 계약 한 모양) |

## 2. 결정 요약

| 결정 | 선택 | 근거 |
|---|---|---|
| P5b | 관련 범위로 포함 | 전수 스윕은 실측상 소음(회귀 0 · 인과 없는 결함 9 확정에 라운드 추가) |
| 화면 띄우기 | `serve_cmd` 래퍼, 없으면 P5b 생략(사유 명시) | 이름만 준 슬롯은 남의 스택을 채점한다 |
| probe 환경 | `exec_cmd` 래퍼 | 사본 측정 조립을 매 버그마다 손으로 하면 가짜 빨강이 난다 |
| 판정 집행 | 코드(`bp_gate.py`) | 「①(집행 코드)에 넣을 수 있는가를 먼저 묻는다」 |
| 규모 | 경량 경로만 | 중량 경로(worktree + team mode)는 원천에서도 한 번도 돌지 않았다 — 알려진 공백 |

## 3. 단계

```
P0 접수    재현 동결 · bp_gate init · 훅 install + verify
P1 조사    조사자 → root_cause.json · rubric.json 초안 · control/*.diff · investigation.md
GATE 1     사용자: 진단 · fix_scope · expected_after · 루브릭 확정 → bp_gate freeze
P2 RED     RED 작성자 → 실패 테스트 커밋 → bp_gate baseline --red <파일…>
P3 GREEN   GREEN 구현자 — 루프당 가설 하나 · 테스트 수정 0 · fix_scope 안
P4 자기확인 구현자 — RED 통과 + bp_regress
P5 판정    bp_gate run → 귀속 · cap · 라우팅
P5b 스윕   user_facing 이고 ui 가 있고 브라우저 도구가 있을 때만
GATE 2     사용자: 재현 재생 · 카드 밖 파일 · 루프 N/3 · 원인 교체 이력 · 부채 · 관찰(미판정) · P5b 생략 사유
P6 PR      경로 지정 커밋 · push · PR · 훅 uninstall
```

- 작업은 현재 워크트리의 작업 가지 하나에서 한다. 사본은 `git worktree add --detach` 로 만들고 측정 후 **폐기**한다(원복이 아니다).
- 작업공간: 호스트의 `.bugfix-pipeline/<slug>/`. `bp_gate init` 이 `git check-ignore` 로 **무시되는 경로인지 실제로 확인**하고, 아니면 exit 2.
- 재진입 정본: `.bugfix-pipeline/<slug>/ledger.json` 한 파일. 머신 로컬이다 — 다른 머신에서는 P1 부터 다시 돈다.
- 하드 스톱: GATE 1 · GATE 2 · 데이터 비가역 작업 · 배포 · cap 도달(`DEFERRED`) · `CANNOT-MEASURE`.
- **어떤 종료 경로에서든** 훅 `uninstall` 과 사본·서버 정리.

판정별 GATE 1 이후 경로(원천 그대로):

| 판정 | 이후 |
|---|---|
| `BUG` | P2 |
| `NOT-A-BUG` | 사용자가 `fix_scope` 를 승인하면 P2(표현·안내 결함을 고친다), 아니면 종료 |
| `CANNOT-MEASURE` | 정지 — 무엇을 못 쟀는지 올린다. 재개는 P1 재진입 |

## 4. 프로파일 schema 2

```json
{
  "schema": 2,
  "regress": { "side_cmd": ["…"], "ran_fully": "…", "not_fully": "…", "tree_marker": "…", "allowed_roots": ["~"] },
  "exec":    { "exec_cmd": ["scripts/bp_exec.sh"] },
  "ui":      { "serve_cmd": ["scripts/bp_serve.sh"], "ready_marker": "^BP_URL=", "ready_timeout_s": 120 }
}
```

- `regress` — schema 1 과 같다.
- `exec` (필수) — `<exec_cmd…> <트리> -- <명령…>`. cwd 는 호출 루트, 명령의 종료코드를 그대로 돌려준다.
  **환경 조립에 실패하면 exit 125** — 「probe 가 돌지 못했다」(ENV)와 「돌았는데 FAIL」을 종료코드로 가른다.
  `exec_cmd[0]` 해소 규칙은 `side_cmd` 와 같다.
- `ui` (선택) — `<serve_cmd…> <트리>`. 그 트리로 앱을 띄우고 stdout 에 `ready_marker` 에 걸리는 줄
  `BP_URL=<url>` 을 한 번 낸다. 플러그인은 `ready_timeout_s`(기본 120)까지 기다리고, 끝나면 프로세스 그룹에
  SIGTERM, 10 초 뒤 SIGKILL. `ready_marker` 는 `ran_fully` 와 같은 패턴 검사를 받는다.
- schema 1 은 거부하고 이전 방법을 안내한다(배포 직후라 사용자 없음 — 이중 지원 부담을 지지 않는다).
- 모르는 키 거부는 새 섹션에도 적용된다.

## 5. `rubric.json`

```json
{
  "cause_id": "label-01",
  "R-CAUSE":   { "probe": ["{exec}", "{tree}", "--", "pytest", "tests/test_label.py::test_shows_year", "-q"] },
  "R-SYMPTOM": { "probe": ["{exec}", "{tree}", "--", "sh", "repro.sh"],
                 "assert": ["grep", "-q", "기대 문구", "{out}"] },
  "R-CONTROL": { "axes": [
      { "name": "라벨 제거", "mutate": { "patch": "control/label.diff" },
        "alive": ["{exec}", "{tree}", "--", "pytest", "tests/test_label.py::test_other", "-q"] } ] }
}
```

- 자리표시자: `{exec}` → `exec_cmd` argv 로 펼침 · `{tree}` → 측정 트리 절대경로 · `{out}` → 그 행 probe 의
  stdout+stderr 파일. 그 밖의 `{…}` 는 `freeze` 가 거부한다.
- `assert` 가 없으면 probe 종료코드 == 0 이 assert 다. 원천의 `extract` 는 `assert` 명령 하나로 합친다.
- `R-CONTROL.axes[]` — 축마다 사본에 `mutate` 적용 → `R-CAUSE` 의 probe·assert 실행 → **assert 가 빨개져야**
  그 축 통과. `alive`(선택)는 변이 후에도 **초록이어야** 한다(계측기 생존). `mutate` 는
  `{"patch": "<작업공간 상대 경로>"}` 또는 `{"checkout": "<sha>"}`. 축 하나라도 통과 못 하면 `control=False`.
- **`R-REGRESS` 는 루브릭에 없다.** `bp_gate` 가 `bp_regress run <기준선 사본> <호출 루트>` 로 고정 실행한다.
- 동결 대상: `rubric.json` · 그것이 참조하는 patch 파일 · `root_cause.json` · `repro.md`. sha256 을
  `ledger.json` 에 기록하고 `run` 이 매번 대조한다.

## 6. `scripts/bp_gate.py`

상태는 `.bugfix-pipeline/<slug>/ledger.json` 한 파일.

| 명령 | 단계 | 하는 일 | 실패 |
|---|---|---|---|
| `init <slug>` | P0 | 작업공간 생성 · 무시 경로 확인 · 프로파일 schema 2 검사 · `ledger.json` 뼈대 · `repro.md` 양식 | 2 |
| `freeze <slug>` | GATE 1 | `rubric.json` 형식(행·자리표시자·patch 존재) · `root_cause.json` 판정이 `BUG`/`NOT-A-BUG` · `expected_after` 채워짐 → 동결 해시·`cause_id` 기록 | 2 |
| `baseline <slug> --red <파일…>` | P2 | 첫 RED 커밋의 부모를 기준선 sha 로 · RED 테스트 파일 blob 해시 기록 | 2 |
| `run <slug>` | P5 | 아래 | 아래 |
| `refreeze <slug> --reason <…> [--refund-last]` | GATE 1 재진입 | 재동결 · 사유를 이력에. `cause_id` 가 바뀌면 원인 교체 이력. `--refund-last` 는 직전 `CODE` 를 cap 에서 되돌림(측정 결함 `SPEC` — 사용자 승인 필수) | 2 |
| `record-sweep <slug> --regression <근거 파일>` | P5b | 확정 회귀를 진리표에 `regress=False` 로 넣어 `CODE` +1 | 2 |
| `status <slug>` | 재진입·GATE 2 | 단계 · 루프 N/3 · 원인 교체 이력 · 카드 밖 파일(`기준선..HEAD` 변경 − `fix_scope`) · 판정 이력 | — |

`run`:

1. 변조 검사 — 동결 해시 · RED 파일 해시 · `cause_id` 대조. 불일치 → exit 2.
2. cap 이 이미 찼으면 exit 4.
3. `R-CONTROL`(축마다 사본 → 변이 → 측정 → 폐기) → `R-CAUSE` → `R-SYMPTOM` → `R-REGRESS` 순서.
   FAIL 이면 멈추고 뒤 행은 `None`. probe exit 125 · 사본·변이 실패 · `bp_regress` 2/3 → `probe_ok=False` 로 멈춤.
4. `verdict()` → `code_count += cap_delta` → 이력 추가 → `verdict_<n>.json`(행별 명령·종료코드·출력 파일).
5. 사본은 `finally` 에서 폐기 + `git worktree prune`.

| exit | 뜻 | 다음 |
|---|---|---|
| 0 | `PASS` | P5b |
| 1 | `CODE` · `ANCHOR` · `VOID` · `ENV` (`verdict_<n>.json`) | `CODE` → P3 · `ANCHOR` → P2 재작성 · `VOID`/`ENV` → 측정·환경 고쳐 재측정 |
| 2 | 설정 오류 · 변조 | 정지 · 보고 |
| 4 | cap 도달 → `DEFERRED` | 정지 |

`R-REGRESS` 가 낸 `CODE` 는 P3 로 보내기 전에 `new_red.txt` 를 사용자에게 보인다 — 원인과 무관해 보이면 `SPEC`
으로 GATE 1 재진입. 무관 판단은 코드가 하지 않는다.

코드가 판정할 수 없는 상태는 모두 exit 2 또는 `probe_ok=False` 로 가고, **PASS 가 되지 않는다.**

## 7. 에이전트 5종

공통 배정 계약 — **한 모양**: `workspace`(`.bugfix-pipeline/<slug>/` 절대경로) · `tree`(호출 루트) · `cause_id`.
산출물은 `workspace` 직하 고정 이름. `queue`·slot 없음. 측정은 `exec_cmd` 로만.

| 에이전트 | 받는 것 | 내는 것 | 금지 |
|---|---|---|---|
| `bug-root-cause-investigator` | `repro.md` | `root_cause.json`(+ `affected_routes`) · `rubric.json` · `control/*.diff` · `investigation.md` | production·테스트 수정 · `expected_after` 채우기 |
| `bug-red-writer` | 동결 `root_cause.json` · `rubric.json` | 불변식을 앵커한 실패 테스트 — `exec_cmd` 로 빨강 확인 후 `test(…)` 커밋, sha 보고 | production 수정. 모호하면 `SPEC` |
| `bug-green-engineer` | 위 + RED sha | `fix_scope` 안 최소 구현, 커밋 본문 `RED: <sha>` · P4 자기 확인 | 테스트 수정 · 루프당 가설 둘 이상 · `fix_scope` 밖 변경 |
| `bug-cta-sweeper` | 기준선·수정 후 URL · `routes` · `accounts` | `sweep.json` · `sweep.md` | 코드 수정 · 비가역 CTA 누르기 |
| `bug-sweep-gate` | `sweep.json` 의 관련 후보 | `gate_round<N>.md` — 후보별 확정·기각 | 코드 수정 · 비관련 후보 판정 |

`root_cause.json` 의 `file`/`line`/`symbol` 은 판정에 따라 뜻이 다르다(`BUG` 원인 위치 · `NOT-A-BUG` 정합 확인
자리 · `CANNOT-MEASURE` `null`) — 원천 규칙 유지.

## 8. P5b — 관련 범위 스윕

「관련」은 LLM 재량이 아니라 **기준선과 수정 후의 관측 차이**다.

1. 리더가 `bp_ui.py serve` 로 기준선 사본과 수정 후를 둘 다 띄운다 — 두 URL. 끝나면 둘 다 내린다.
2. 대상 페이지 = `routes ∪ affected_routes`, 계정 상태별.
3. **관련 CTA** = 두 쪽에서 렌더된 DOM 부분 트리가 다른 CTA, 또는 페이지 로드 요청의 응답이 다른 페이지의 CTA.
4. 관련 CTA 만 양쪽에서 누르고 결과(요청·응답 상태·에러·이동)를 비교한다. 비가역·외부 전송 CTA 는 누르지 않고
   렌더된 값을 대조한다.
5. 비관련 CTA 는 누르지 않는다. 수정 후 쪽에서 페이지마다 로드 스모크(앱 4xx/5xx 0 · pageerror 0).
6. 스윕 게이트는 관련 후보만 판정한다. 비관련 이상은 GATE 2 에 「관찰(미판정)」으로만.
7. 확정 회귀 → `bp_gate record-sweep --regression` — 진리표가 `CODE` +1 을 낸다. P5b 는 cap 을 직접 세지 않는다.

생략 조건(GATE 2 에 사유 명시): `user_facing: false` · `ui` 없음 · 쓸 수 있는 브라우저 도구 없음(스위퍼가 첫
단계에서 확인).

## 9. `SKILL.md`

- 단계마다 정확한 명령과 멈춤 조건. 코드로 간 규칙은 한 줄 요약 + 명령만.
- 리더 규율: 배정 «직후» `watch.sh` 감시 · `STALL` 이면 깨우기 전에 다른 채널로 확인 · 팀원 반박은 근거가 주장을
  증명하는지 따짐 · 긴 측정 전 전원(수면) 확인 · 스크린샷은 텍스트 누출 검사 밖이다.
- Lock-in: RED ≠ GREEN · 채점자는 코드 · 루브릭 작성자 ≠ 채점자 · 귀속은 진리표 · 표본은 전수 · 루프백은 같은
  `cause_id` 안에서만 · cap 은 `CODE` 만 · 같은 우회를 두 번째 쓰면 결함.
- 테스트 시나리오: 정상 · `NOT-A-BUG` · 드리프트(`ANCHOR`) · 측정 무효(`VOID`) · cap 도달 · 원인 교체 · P5b 생략.

## 10. 테스트

| 대상 | 방법 |
|---|---|
| `bp_gate.py` | 픽스처 확장(가짜 `exec_cmd` + 125 모드, sh 명령 루브릭, patch 로 `R-CONTROL`). 명령 7종 pytest + `--selftest`. 사보타주 대조(행 순서 · 변조 검사 · 125 매핑 등) |
| `bp_ui.py serve` | 가짜 서버로 준비 대기 · 타임아웃 · 프로세스 그룹 종료 |
| 프로파일 schema 2 | 기존 테스트 이관 + `exec`·`ui` 거부 경로 |
| 계약 린트 `tests/test_contracts.py` | `SKILL.md` · 에이전트 문서에 적힌 산출물 파일명·명령이 `bp_gate.py` 상수와 일치하는지. 산문이 코드와 어긋나면 빨개진다 |
| 종단 | 원천이 아닌 다른 프로젝트에서 실제 버그 하나 |

## 11. 구현 분할

스펙 하나, 계획 셋:

- **계획 A (코드)** — 프로파일 schema 2 · `bp_gate.py` · `bp_ui.py`
- **계획 B (문서)** — `SKILL.md` · 에이전트 5종 · 계약 린트. A 의 상수를 인용하므로 A 다음
- **계획 C (종단)** — 다른 프로젝트에서 실제 버그 하나

## 12. 범위 밖 · 알려진 공백

- 중량 경로(worktree + team mode)
- 프로파일 초안 자동 생성
- 버그별 표적 보강(결함의 기존 테스트가 `side_cmd` 수집 루트 밖에 있을 때) — 루브릭의 몫
- 전수 CTA 스윕 — 별도 「메뉴 점검」 모드 후보
- `bp_regress` 리뷰에서 미룬 Minor 6건
