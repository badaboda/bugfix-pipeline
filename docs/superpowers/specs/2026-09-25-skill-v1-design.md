# SKILL v1 — 이식 가능한 버그 수정 파이프라인 설계

- 날짜: 2026-09-25
- 상태: 설계 승인됨 (구현 전) · 범용성 검토 반영(8건)
- 선행: [프로파일 v1](2026-09-24-profile-v1-design.md) (이 스펙이 schema 2 로 확장한다)

## 1. 목적

버그 수정 요청 하나를 받아 **AI 가 고치고 PR 까지** 잇는 오케스트레이터를, 어떤 호스트 프로젝트에도 설치될 수
있는 형태로 만든다. 버그의 성격에 따라 두 트랙으로 간다.

- **정식 트랙** — 원인 규명 → RED → GREEN → 판정 → 관련 범위 화면 스윕 → PR. **통과 기준을 수정 전에 동결하고,
  판정은 LLM 이 아니라 종료코드와 진리표가 낸다.**
- **가벼운 트랙** — 결정론 판정이 성립하지 않거나 비용이 맞지 않는 버그. 에이전트 하나 · 게이트 하나로 고치되,
  **증명하지 못한 것에 이름을 붙여** PR 에 남긴다.

원천(특정 프로젝트의 in-repo 스킬)에서 바뀌는 것:

| 원천 | v1 |
|---|---|
| 판정 절차(행 순서·중단·인자 매핑·cap)를 산문으로 규정하고 게이트 에이전트가 전사 | **`bp_gate.py` 가 집행** — 게이트 에이전트 없음 |
| 사본 측정 환경을 조리법 산문으로 | 프로파일 `exec_cmd` 래퍼 |
| 슬롯(포트 이름)을 리더가 배정 | `serve_cmd` 래퍼가 «주어진 트리»로 화면을 띄움 |
| P5b 전수 스윕 | **관련 범위** — 기준선·수정 후의 관측 차이로 선정 |
| `RED: <sha>` 를 git 훅이 강제 | **`bp_gate` 가 커밋 이력으로 검사** — 훅은 선택 |
| 경량·중량(둘 다 무거움) | **트리아지 → 정식 · 가벼운** |
| `rubric.yaml` | `rubric.json` (호스트 python 3.9 표준 라이브러리에 YAML 파서 없음) |
| 재진입 정본 = 프로젝트 문서 한 줄 | `ledger.json` |
| 에이전트 7종(빌려 씀, 계약 두 모양) | 6종(번들, 계약 한 모양) |

## 2. 결정 요약

| 결정 | 선택 | 근거 |
|---|---|---|
| P5b | 관련 범위로 포함 | 전수 스윕은 실측상 소음(회귀 0 · 인과 없는 결함 9 확정에 라운드 추가) |
| 화면 띄우기 | `serve_cmd` 래퍼, 없으면 P5b 생략(사유 명시) | 이름만 준 슬롯은 남의 스택을 채점한다 |
| probe 환경 | `exec_cmd` 래퍼 | 사본 측정 조립을 매 버그마다 손으로 하면 가짜 빨강이 난다 |
| 판정 집행 | 코드(`bp_gate.py`) | 「①(집행 코드)에 넣을 수 있는가를 먼저 묻는다」 |
| 트랙 | 재서 가르는 트리아지 → 정식 · 가벼운 | 결정론 판정이 안 서는 버그·작은 버그를 멈추게 두지 않는다 |
| `RED:` 규칙 | 커밋 이력 감사 | 기존 훅과 충돌(실측) — §8 |
| 기준선 | sha 로 캐시 | 기준선 결과는 루프 사이에 변하지 않는다 |
| 온보딩 | 무설정 가벼운 트랙 + 스택별 템플릿 + 초안 생성(검사를 통과하지 못하는 초안) | 추정하지 않되 첫 진입 비용을 낮춘다 |
| 재현 | P0 에서 `repro.sh` 로 자동화 + 사용자 확인 | 화면 버그가 정식 트랙에 들어올 수 있게 |
| 가벼운 트랙 검증 | 코드가 실행(`light-verify`), 표지는 기록에서만 계산 | 자기보고는 증거가 아니다 |
| P6 포지 | `gh`/`glab` 감지, 없으면 PR 본문 파일까지 | 포지를 추측하지 않는다 |
| 중량 경로(worktree + team mode) | 없음 | 원천에서도 한 번도 돌지 않았다 — 알려진 공백 |

## 3. 트리아지와 흐름

### 3.1 P0 — 접수·트리아지

1. **재현 동결** — `repro.md`(`steps` · `observed` · `where` · `expected_after` 는 비움). 두 트랙 공통.
2. `bp_gate init <slug>` — 작업공간 생성(§6). **프로파일이 없어도 된다**(§4 — 가벼운 트랙은 무설정으로 돈다).
3. **재현 자동화** — 사람이 쓴 `steps` 가 명령이 아니면(「X 를 누르면 Y 가 보인다」) 리더가 `repro.sh` 로
   옮긴다(curl · 브라우저 자동화 · CLI 호출). `repro.sh` 는 `observed` 를 **출력으로 드러내야** 한다.
   리더는 한 번 돌린 출력을 사용자에게 보이고 **「이게 내가 본 것」 확인**을 받는다 — 확인 전에는 트리아지에
   쓰지 않는다. 옮기지 못하면(외부 결제 · 실기기 · 운영 데이터 전용 등) 사유를 `repro.md` 에 적고 넘어간다.
   사용자에게 보이는 버그 대부분이 화면 버그이므로, 이 단계가 없으면 정식 트랙이 거의 쓰이지 않는다.

   **`repro.sh` 계약** — 작업공간(`.bugfix-pipeline/<slug>/repro.sh`, 무시 경로)에 산다. 사본에는 무시된 파일이
   없으므로 **트리 안에서 찾지 않고 절대경로로 부른다**(자리표시자 `{repro}`).
   - 호출: `repro.sh <트리 절대경로> [<URL>]`. 재현이 앱 화면을 요구하면 두 번째 인자로 URL 을 받는다.
   - URL 은 `bp_ui.py serve` 가 **그 트리로** 띄운 앱의 것이다 — 사용자 개발 서버는 작업 트리만 서빙하므로
     기준선 사본을 잴 수 없다.
   - `ui` 가 없는데 화면이 필요한 재현이면: 현재 트리는 사용자가 준 URL 로 잴 수 있지만 **기준선 사본은 잴 수
     없다.** 이때 「수정 전 재현」은 P0 의 확인 기록으로 대신하고 `기준선 미재현` 표지를 남긴다. 트리아지는 이
     재현을 «결정적»으로 치지 않는다(정식 트랙의 `R-SYMPTOM` 사본 측정이 불가능하므로).
4. `bp_gate triage <slug>` — **재서** 트랙을 가른다.

   | 신호 | 재는 법 |
   |---|---|
   | 결정적 재현 | 확인된 `repro.sh`(또는 명령인 `steps`)를 `exec_cmd` 로 **3회**. 세 번의 종료코드가 같고 `observed` 가 매번 출력에 나오면 결정적. 명령이 없으면 비결정 |
   | 스위트 | 프로파일에 `regress` 가 있는가 |
   | 크기 | 사용자가 「가볍게」를 명시 |

   3 회는 표본이다 — 간헐적 버그가 우연히 3 회 재현될 수 있다. 그 경우는 정식 트랙 판정에서 `VOID`/`ENV` 로
   드러나고 §3.2 의 이관 경로를 탄다.

   | 결과 | 트랙 |
   |---|---|
   | 결정적 + 스위트 있음 + 가볍게 아님 | 정식 |
   | 그 밖 | 가벼운 |

   조사 후 크기가 드러나는 경우는 트리아지가 아니라 **P1 이후**에 다룬다 — 정식 트랙에서 조사 결과가
   「`fix_scope` 1 파일 · 공유 파일 아님」이면 GATE 1 에서 사용자가 가벼운 트랙으로 **내리는 것을 허용**한다
   (`bp_gate to-light`, 사용자 승인 필수). 가벼운 → 정식 승급은 §3.3.

### 3.2 정식 트랙

```
P1 조사    조사자 → root_cause.json · rubric.json 초안 · control/*.diff · investigation.md
GATE 1     사용자: 진단 · fix_scope · expected_after · 루브릭 확정 → bp_gate freeze
P2 RED     RED 작성자 → 실패 테스트 커밋 → bp_gate baseline --red <파일…>
P3 GREEN   GREEN 구현자 — 루프당 가설 하나 · 테스트 수정 0 · fix_scope 안
P4 자기확인 구현자 — RED 통과 + bp_regress
P5 판정    bp_gate run → 귀속 · cap · 라우팅
P5b 스윕   user_facing 이고 ui 가 있고 브라우저 도구가 있을 때만
GATE 2     사용자: 재현 재생 · 카드 밖 파일 · 루프 N/3 · 원인 교체 이력 · 부채 · 관찰(미판정) · P5b 생략 사유
P6 PR      경로 지정 커밋 · push · PR (포지 CLI 가 없으면 가지 + PR 본문 파일까지)
```

**정식 → 가벼운 이관** (`bp_gate to-light <slug> --reason`, 사용자 승인 필수) — 결정론 판정이 서지 않는 것이
드러난 경우의 출구다. 조건: P1 판정 `CANNOT-MEASURE` · 같은 `cause_id` 에서 `VOID`/`ENV` 가 **연속 2 회**
(간헐적 버그가 트리아지 3 회를 통과한 경우) · GATE 1 의 크기 강등. 이관 사유는 `결정론 판정 없음` 표지의 근거로
`ledger.json` 에 남고, 이관 전의 `code_count` 는 이력에 보존된다.

판정별 GATE 1 이후 경로(원천 그대로):

| 판정 | 이후 |
|---|---|
| `BUG` | P2 |
| `NOT-A-BUG` | 사용자가 `fix_scope` 를 승인하면 P2(표현·안내 결함), 아니면 종료 |
| `CANNOT-MEASURE` | 정지하지 않고 **가벼운 트랙으로 이관**(아래) — 결정론 판정이 안 서는 버그다. 무엇을 못 쟀는지가 `결정론 판정 없음` 표지의 근거가 된다 |

### 3.3 가벼운 트랙

에이전트 하나(`bug-light-fixer`), 사용자 게이트 하나(`GATE L`).

1. 재현 동결은 P0 에서 끝났다.
2. 조사와 수정을 한 번에. 원인은 `파일:라인` 까지, **루프당 가설 하나**. 가능하면 실패 테스트를 먼저 쓴다.
3. **검증은 에이전트가 아니라 코드가 돌린다** — `bp_gate light-verify <slug>`. 에이전트의 「검증했다」는 증거가
   아니다. 두 축을 **독립적으로** 잰다.

   | 축 | 조건 | `light-verify` 가 하는 일 | 못 하면 표지 |
   |---|---|---|---|
   | 재현 | 확인된 `repro.sh` 가 있고 결정적 | 기준선 사본과 현재 트리에서 각각 실행 — 수정 전 재현 · 수정 후 사라짐 | — |
   | 재현 | 화면 재현인데 `ui` 없음 | 현재 트리만(사용자 URL) — 수정 후 사라짐 | `기준선 미재현` |
   | 재현 | 비결정 · 명령 없음 | 현재 트리에서 N 회(기본 5) 실행해 재현 횟수를 기록(명령이 있을 때) | `결정론 판정 없음` |
   | 회귀 | 프로파일 `regress` 있음 | `bp_regress` 1 회(기준선 캐시) | 새 빨강이 있으면 GATE L 에 그대로 올린다 |
   | 회귀 | `regress` 없음 | — | `회귀 미검증` |

   결과는 `ledger.json` 의 `light_verifications[]` 에 명령 · 종료코드 · 출력 파일로 남는다.
4. `bp_gate light-report <slug>` 는 **`light_verifications[]` 만 보고** 표지를 계산하고, 원인 · diff · 검증 결과 ·
   표지를 `light_report.md` 와 PR 본문 초안(`pr_body.md`)으로 쓴다. 🔴 **PR 본문에는 명령 출력 원문을 넣지 않는다**
   — 판정 · 종료코드 · 실패 이름 목록 · 표지만. 출력에는 토큰 · `.env` 값 · 내부 URL 이 섞일 수 있다(원천
   실측: 스크린샷에 구독 토큰). 원문은 작업공간(무시 경로)에만 남고, `light_report.md`(로컬 전용)만 원문 발췌를 담는다. 한 번도 돌지 않은 축은 자동으로 표지가 된다 — 에이전트
   보고로 표지를 지울 수 없다. 마지막 `light-verify` 이후 커밋이 더 있으면 exit 2(검증이 낡았다).
5. **GATE L** — `light_report.md` 를 그대로 보이고 승인을 받는다. 승인 전에는 PR 을 만들지 않는다.
   (`light-verify` 는 커밋된 트리를 재므로 수정 커밋은 작업 가지에 먼저 있다. 승인이 거부되면 가지를 버린다.)
6. P6 과 같다. PR 본문은 `light-report` 의 초안을 쓴다 — 트랙과 표지가 들어 있다.

**승급 래칫(한 방향)** — 다음 중 하나가 보이면 정식 트랙 P1 로 올린다(`bp_gate promote <slug> --reason`).
`fix_scope` 2 파일 이상 · 공유 파일 · 첫 가설 실패 · 원인 두 갈래. 단 트리아지가 «비결정»·«스위트 없음»으로
가벼운 트랙에 보낸 버그는 정식 트랙의 전제가 없으므로 승급하지 않고 **GATE L 에서 사용자에게 올린다**.

### 3.4 공통

- 작업은 현재 워크트리의 작업 가지 하나에서. 사본은 `git worktree add --detach` 로 만들고 측정 후 **폐기**.
- 작업공간 `.bugfix-pipeline/<slug>/` — `init` 이 `git check-ignore` 로 무시 경로인지 확인, 아니면 exit 2.
- 재진입 정본: `ledger.json` 한 파일(트랙 포함). 머신 로컬 — 다른 머신에서는 P0 부터.
- 하드 스톱: 재현 확인(P0, `repro.sh` 를 만든 경우) · GATE 1 · GATE 2 · GATE L · 데이터 비가역 작업 · 배포 ·
  cap 도달(`DEFERRED`).
- P6 포지: `gh`(GitHub) 또는 `glab`(GitLab) 이 있고 원격이 그 포지를 가리키면 PR/MR 을 만든다. 아니면 가지를
  push 하고(원격이 있으면) PR 본문을 `pr_body.md` 로 남긴 뒤 **멈춰서 알린다** — 포지를 추측하지 않는다.
- **어떤 종료 경로에서든** 사본·서버 정리, 훅을 설치했다면 uninstall.
- **PR 본문 위생(두 트랙 공통)** — PR·MR 본문은 `bp_gate` 가 만드는 `pr_body.md` 만 쓰고, 그 생성기는 명령 출력
  파일의 내용을 읽지 않는다(테스트로 고정 — §13). 정식 트랙의 GATE 2 요약도 같은 규칙.
- **한 워크트리에 버그 하나.** `init` 은 같은 워크트리에 진행 중인(`P6` 이전) 다른 slug 가 있으면 exit 2. 동시 처리는
  중량 경로의 몫이다(범위 밖).

## 4. 프로파일 schema 2

```json
{
  "schema": 2,
  "exec":    { "exec_cmd": ["scripts/bp_exec.sh"] },
  "regress": { "side_cmd": ["…"], "ran_fully": "…", "not_fully": "…", "tree_marker": "…", "allowed_roots": ["~"] },
  "ui":      { "serve_cmd": ["scripts/bp_serve.sh"], "ready_marker": "^BP_URL=", "ready_timeout_s": 120 }
}
```

- **프로파일 파일 자체가 선택이다.** 없으면 `{"schema": 2}` 와 같다 — 가벼운 트랙은 무설정으로 돈다.
  정식 트랙은 `regress` 가 있어야 트리아지를 통과한다.
- `exec` (선택) — `<exec_cmd…> <트리> -- <명령…>`. cwd 는 호출 루트, 명령의 종료코드를 그대로 돌려준다.
  **없으면 내장 기본값**: 그 트리 디렉토리에서 명령을 그대로 실행한다(`bp_exec_local`). 사본에 추적 안 되는
  의존성이 필요한 프로젝트는 기본값으로는 사본 측정이 빨개진다 — 트리아지는 기본값일 때 이 사실을 경고하고,
  정식 트랙에서 그 때문에 `VOID`/`ENV` 가 연속되면 이관 경로(§3.2)를 탄다.
  - **환경 조립에 실패하면 exit 125** — 「probe 가 돌지 못했다」(ENV)와 「돌았는데 FAIL」을 종료코드로 가른다.
  - 🔴 **사본에는 git 이 추적하지 않는 파일이 없다** — `node_modules` · `.venv` · `.env` · 빌드 산출물.
    래퍼가 원본의 것을 공유(심볼릭 링크 · 볼륨 마운트)하거나 설치한다. 이것은 래퍼의 책임이고,
    `docs/profile.md` 가 공유 패턴 예시를 둔다. 원천에서 이 조립(venv 볼륨)이 빠지면 «내 회귀처럼 보이는» 빨강이 났다.
  - `exec_cmd[0]` 해소 규칙은 `side_cmd` 와 같다.
- `regress` (**선택으로 바뀜**) — 없으면 스위트 없는 프로젝트다. 트리아지가 가벼운 트랙으로 보내고 `회귀 미검증`.
  있을 때의 계약은 schema 1 과 같다(`side_cmd` 도 사본 의존성 규칙을 따른다).
- `ui` (선택) — `<serve_cmd…> <트리>`. 그 트리로 앱을 띄우고 stdout 에 `ready_marker` 에 걸리는 줄
  `BP_URL=<url>` 을 한 번 낸다. `ready_timeout_s`(기본 120)까지 기다리고, 끝나면 프로세스 그룹에 SIGTERM,
  10 초 뒤 SIGKILL. `ready_marker` 는 `ran_fully` 와 같은 패턴 검사를 받는다.
- schema 1 은 거부하고 이전 방법을 안내한다. 모르는 키 거부는 새 섹션에도 적용된다.

## 5. `rubric.json` (정식 트랙)

```json
{
  "cause_id": "label-01",
  "R-CAUSE":   { "probe": ["{exec}", "{tree}", "--", "pytest", "tests/test_label.py::test_shows_year", "-q"] },
  "R-SYMPTOM": { "probe": ["{exec}", "{tree}", "--", "sh", "{repro}", "{tree}", "{url}"],
                 "assert": ["grep", "-q", "기대 문구", "{out}"] },
  "R-CONTROL": { "axes": [
      { "name": "라벨 제거", "mutate": { "patch": "control/label.diff" },
        "alive": ["{exec}", "{tree}", "--", "pytest", "tests/test_label.py::test_other", "-q"] } ] }
}
```

- 자리표시자: `{exec}` → `exec_cmd` argv 로 펼침 · `{tree}` → 측정 트리 절대경로 · `{out}` → 그 행 probe 의
  stdout+stderr 파일 · `{repro}` → 작업공간 `repro.sh` 절대경로 · `{url}` → 그 행을 재는 동안 `bp_ui.py serve` 가
  **그 트리로** 띄운 앱의 URL(`{url}` 이 있는 행은 `bp_gate` 가 측정 전후로 서버를 띄우고 내린다 — `ui` 가 없으면
  `freeze` 가 거부). 그 밖의 `{…}` 는 `freeze` 가 거부한다.
- `assert` 가 없으면 probe 종료코드 == 0 이 assert 다. 원천의 `extract` 는 `assert` 명령 하나로 합친다.
- `R-CONTROL.axes[]` — 축마다 사본에 `mutate` 적용 → `R-CAUSE` 의 probe·assert 실행 → **assert 가 빨개져야**
  그 축 통과. `alive`(선택)는 변이 후에도 **초록이어야** 한다. `mutate` 는
  `{"patch": "<작업공간 상대 경로>"}` 또는 `{"checkout": "<sha>"}`. 축 하나라도 통과 못 하면 `control=False`.
- **`R-REGRESS` 는 루브릭에 없다.** `bp_gate` 가 `bp_regress run <기준선 사본> <호출 루트>` 로 고정 실행한다.
- 동결 대상: `rubric.json` · 참조 patch 파일 · `root_cause.json` · `repro.md`. sha256 을 `ledger.json` 에 기록하고
  `run` 이 매번 대조한다.

## 6. `scripts/bp_gate.py`

상태는 `.bugfix-pipeline/<slug>/ledger.json` 한 파일.

| 명령 | 트랙·단계 | 하는 일 | 실패 |
|---|---|---|---|
| `init <slug>` | 공통 P0 | 작업공간 · 무시 경로 확인 · 프로파일 검사(없으면 기본값) · `ledger.json` 뼈대 · `repro.md` 양식 | 2 |
| `triage <slug> [--light]` | 공통 P0 | §3.1 — 재현 3회 · 스위트 유무 · `--light` → 트랙 기록. 이때의 HEAD 를 `base_sha` 로 기록(가벼운 트랙의 기준선) | 2 |
| `freeze <slug>` | 정식 GATE 1 | `rubric.json` 형식 · `root_cause.json` 판정 `BUG`/`NOT-A-BUG` · `expected_after` 채워짐 → 동결 | 2 |
| `baseline <slug> --red <파일…>` | 정식 P2 | 첫 RED 커밋의 부모를 기준선 sha 로 · RED 테스트 파일 blob 해시 | 2 |
| `run <slug>` | 정식 P5 | 아래 | 아래 |
| `refreeze <slug> --reason <…> [--refund-last]` | 정식 GATE 1 재진입 | 재동결 · 사유 이력. `cause_id` 변경 = 원인 교체 이력. `--refund-last` 는 직전 `CODE` 환불(측정 결함 `SPEC` — 사용자 승인 필수) | 2 |
| `record-sweep <slug> --regression <근거>` | 정식 P5b | 확정 회귀를 진리표에 `regress=False` 로 → `CODE` +1 | 2 |
| `promote <slug> --reason <…>` | 가벼운 → 정식 | 승급 기록, 단계 P1 로 | 2 |
| `to-light <slug> --reason <…>` | 정식 → 가벼운 | §3.2 이관 — 사유를 표지 근거로 기록 · `code_count` 이력 보존 | 2 |
| `light-verify <slug>` | 가벼운 | §3.3 — 재현 축 · 회귀 축을 **직접 실행**해 `light_verifications[]` 에 기록 | 2 |
| `light-report <slug>` | 가벼운 | `light_verifications[]` 만으로 표지 계산 → `light_report.md` + PR 본문 초안. 검증 이후 커밋이 있으면 exit 2 | 2 |
| `status <slug>` | 공통 | 트랙 · 단계 · 루프 N/3 · 원인 교체 이력 · 카드 밖 파일(`기준선..HEAD` 변경 − `fix_scope`) · 판정 이력 · 표지 | — |

### 6.1 `run`

1. 변조 검사 — 동결 해시 · RED 파일 해시 · `cause_id`. 불일치 → exit 2.
2. **커밋 감사** — `기준선..HEAD` 의 `feat`·`fix` 커밋 본문에 `RED: <기준선 이후 커밋 sha>` 가 있는지.
   없으면 exit 2. 원천의 `commit-msg` 훅이 하던 일을 **훅 없이** 한다.
3. cap 이 이미 찼으면 exit 4.
4. `R-CONTROL`(축마다 사본 → 변이 → 측정 → 폐기) → `R-CAUSE` → `R-SYMPTOM` → `R-REGRESS` 순서.
   FAIL 이면 멈추고 뒤 행은 `None`. probe exit 125 · 사본·변이 실패 · `bp_regress` 2/3 → `probe_ok=False`.
5. **기준선 캐시** — `R-REGRESS` 의 기준선 쪽 결과(이름 파일 · 로그 · META)를 `baseline_cache/<기준선 sha>/`
   에 두고 다음 루프에서 재사용한다. 캐시는 **프로파일 `regress` 섹션의 해시**가 같을 때만 유효하다(래퍼·패턴이
   바뀌면 분모가 바뀐다). `bp_regress` 에 «기준선 결과 디렉토리를 받는» 입력을 더한다.
   **`R-CONTROL` 캐시** — 결과를 `(HEAD, rubric 동결 해시, 프로파일 exec 해시)` 로 저장하고 같은 키면 재사용한다.
   GREEN 루프가 HEAD 를 바꾸면 다시 잰다. 무거운 프로젝트에서 판정마다 사본 조립을 반복하지 않는다.
6. `verdict()` → `code_count += cap_delta` → 이력 → `verdict_<n>.json`(행별 명령 · 종료코드 · 출력 파일).
7. 사본은 `finally` 에서 폐기 + `git worktree prune`.

| exit | 뜻 | 다음 |
|---|---|---|
| 0 | `PASS` | P5b |
| 1 | `CODE` · `ANCHOR` · `VOID` · `ENV` (`verdict_<n>.json`) | `CODE` → P3 · `ANCHOR` → P2 재작성 · `VOID`/`ENV` → 측정·환경 고쳐 재측정 |
| 2 | 설정 오류 · 변조 · 커밋 감사 실패 | 정지 · 보고 |
| 4 | cap 도달 → `DEFERRED` | 정지 |

`R-REGRESS` 가 낸 `CODE` 는 P3 로 보내기 전에 `new_red.txt` 를 사용자에게 보인다 — 원인과 무관해 보이면 `SPEC`
으로 GATE 1 재진입. 무관 판단은 코드가 하지 않는다.

코드가 판정할 수 없는 상태는 모두 exit 2 또는 `probe_ok=False` 로 가고, **PASS 가 되지 않는다.**

## 7. 에이전트 6종

공통 배정 계약 — **한 모양**: `workspace`(`.bugfix-pipeline/<slug>/` 절대경로) · `tree`(호출 루트) · `cause_id`.
산출물은 `workspace` 직하 고정 이름. `queue`·slot 없음. 측정은 `exec_cmd` 로만.

| 에이전트 | 트랙 | 받는 것 | 내는 것 | 금지 |
|---|---|---|---|---|
| `bug-root-cause-investigator` | 정식 | `repro.md` | `root_cause.json`(+ `affected_routes`) · `rubric.json` · `control/*.diff` · `investigation.md` | production·테스트 수정 · `expected_after` 채우기 |
| `bug-red-writer` | 정식 | 동결 `root_cause.json` · `rubric.json` | 불변식을 앵커한 실패 테스트 — `exec_cmd` 로 빨강 확인 후 `test(…)` 커밋, sha 보고 | production 수정. 모호하면 `SPEC` |
| `bug-green-engineer` | 정식 | 위 + RED sha | `fix_scope` 안 최소 구현, 커밋 본문 `RED: <sha>` · P4 자기 확인 | 테스트 수정 · 루프당 가설 둘 이상 · `fix_scope` 밖 변경 |
| `bug-cta-sweeper` | 정식 | 기준선·수정 후 URL · `routes` · `accounts` | `sweep.json` · `sweep.md` | 코드 수정 · 비가역 CTA 누르기 |
| `bug-sweep-gate` | 정식 | `sweep.json` 의 관련 후보 | `gate_round<N>.md` — 후보별 확정·기각 | 코드 수정 · 비관련 후보 판정 |
| `bug-light-fixer` | 가벼운 | `repro.md` · `repro.sh`(있으면) · 트랙 기록 | 원인 `파일:라인` · 작업 가지에 수정 커밋(+ 가능하면 실패 테스트) · 승급 신호 보고. 검증은 하지 않는다 — `light-verify` 몫 | 루프당 가설 둘 이상 · 승급 신호를 숨기고 계속 · «검증했다»를 표지 근거로 보고 · GATE L 전 PR |

`root_cause.json` 의 `file`/`line`/`symbol` 은 판정에 따라 뜻이 다르다(`BUG` 원인 위치 · `NOT-A-BUG` 정합 확인
자리 · `CANNOT-MEASURE` `null`) — 원천 규칙 유지.

## 8. `RED:` 규칙과 git 훅

실측(2026-09-25, `core.hooksPath=.husky` 임시 레포):

| 상황 | `hooks/install.sh install` |
|---|---|
| `.husky/commit-msg` 가 이미 있음 | rc=1 거부 — P0 가 막힌다 |
| `core.hooksPath` 는 있고 `commit-msg` 없음 | 설치되지만 **작업 트리 안** `.husky/commit-msg` 에 생긴다 — `git status` 에 `?? .husky/` |

그래서:

- `RED:` 규칙의 **집행은 `bp_gate run` 의 커밋 감사**(§6.1-2)다. 훅이 없어도 PASS 가 나지 않는다.
- 훅은 «더 일찍 알려 주는» 선택 장치로 내린다. `install` 이 거부되면 P0 는 **멈추지 않고** 경고만 남긴다.
- `install.sh` 는 `--git-path hooks` 가 작업 트리 안(추적 경로)을 가리키면 설치를 거부하도록 바꾼다 —
  사용자 레포에 파일을 흘리지 않는다.

## 9. P5b — 관련 범위 스윕 (정식 트랙)

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

## 10. 온보딩

- **스택별 템플릿** — `templates/<스택>/` 에 `bp_side.sh` · `bp_exec.sh` · (가능하면) `bp_serve.sh` ·
  프로파일 조각. v1 대상: pytest · vitest/jest · go test. **실제로 돌려 본 템플릿만** 넣는다 — 스택마다
  «실패 1 · 통과 1 · 오류 1» 트리에서 이름 추출과 `ran_fully` 를 실측하고, 사본 의존성 공유 패턴을 포함한다.
- **`python3 scripts/bp_profile.py init [root]`** — 레포에서 보이는 신호(`pyproject.toml` · `package.json` ·
  `go.mod` …)로 템플릿을 골라 **초안** `.claude/bugfix-pipeline.json` 과 래퍼를 쓴다. 초안에는
  `"_draft": "확인 후 이 키를 지운다"` 가 들어 있어 **모르는 키 규칙으로 `check` 를 통과하지 못한다** — 사람이
  확인하기 전에는 쓸 수 없다. 이미 파일이 있으면 덮어쓰지 않는다. 신호가 없거나 둘 이상이면 고르지 않고 목록을 보인다.

## 11. 지원 범위

| 구분 | v1 |
|---|---|
| OS | macOS · Linux. Windows 는 WSL 에서만 — `sh`·`grep`·`comm`·`git` 이 필요하다 |
| 런타임 | `git` · `python3` ≥ 3.9 (표준 라이브러리만) |
| 정식 트랙 | 명령으로(또는 `repro.sh` 로 옮겨) 결정적 재현 + 자동 테스트 스위트 + 프로파일 `regress` |
| 가벼운 트랙 | 그 밖 전부 — **무설정으로 돈다**(프로파일 없음). 표지로 한계를 남긴다 |
| P5b | 웹(DOM) 앱. 모바일·데스크톱 네이티브 UI 는 생략(사유 명시) |
| 훅 | 선택. 기존 훅 매니저(husky 등)와 공존 — 설치 거부 시 경고만 |

## 12. `SKILL.md`

- 트리아지 · 두 트랙 · 단계마다 정확한 명령과 멈춤 조건. 코드로 간 규칙은 한 줄 요약 + 명령만.
- 언어: 본문은 한국어. **`description` 의 트리거는 영어·한국어 둘 다**(예: "fix this bug", "find the root cause
  and fix", "버그 고쳐줘", "원인 찾아서 고쳐"). 에이전트 6종의 `description` 도 같다. 계약 린트가 트리거 두 언어의
  존재를 검사한다.
- 리더 규율: 배정 «직후» `watch.sh` 감시 · `STALL` 이면 깨우기 전에 다른 채널로 확인 · 팀원 반박은 근거가 주장을
  증명하는지 따짐 · 긴 측정 전 전원(수면) 확인 · 스크린샷은 텍스트 누출 검사 밖이다.
- Lock-in: RED ≠ GREEN · 채점자는 코드 · 루브릭 작성자 ≠ 채점자 · 귀속은 진리표 · 표본은 전수 · 루프백은 같은
  `cause_id` 안에서만 · cap 은 `CODE` 만 · 같은 우회를 두 번째 쓰면 결함 · 가벼운 트랙의 검증과 표지는 코드(`light-verify` · `light-report`)가 낸다 — 에이전트 보고가 아니다.
- 테스트 시나리오: 정상 · `NOT-A-BUG` · 드리프트(`ANCHOR`) · 측정 무효(`VOID`) · cap 도달 · 원인 교체 ·
  P5b 생략 · 가벼운 트랙(표지 셋 각각) · 승급 · `CANNOT-MEASURE` → 가벼운 트랙.

## 13. 테스트

| 대상 | 방법 |
|---|---|
| `bp_gate.py` | 픽스처 확장(가짜 `exec_cmd` + 125 모드 · sh 명령 루브릭 · patch 로 `R-CONTROL`). 명령 12종 pytest + `--selftest`. 사보타주 대조(행 순서 · 변조 검사 · 125 매핑 · 커밋 감사 · 캐시 무효화 · 표지 계산 등) |
| 트리아지 | 결정적 · 비결정(3회 중 다름) · 명령 없음 · 스위트 없음 · `--light` · 프로파일 없음(기본값) |
| 가벼운 트랙 | `light-verify` 두 축 독립 · 돌지 않은 축은 표지 · 검증 이후 커밋 → `light-report` exit 2 · 에이전트 보고로 표지가 사라지지 않음 |
| 이관 | `CANNOT-MEASURE` · `VOID`/`ENV` 연속 2 회 · GATE 1 크기 강등 — 각 `to-light` 기록 |
| 무설정 | 프로파일 없는 레포에서 `init` → `triage` → 가벼운 트랙 끝까지 |
| 기준선 캐시 | 같은 sha 재사용 · `regress` 해시 변경 시 무효 · 캐시 손상 시 재측정 |
| `R-CONTROL` 캐시 | 같은 키 재사용 · HEAD 변경 시 재측정 |
| `repro.sh` | `{repro}` 절대경로 호출이 사본에서 동작 · `{url}` 행의 서버 기동·정리 · `ui` 없는 화면 재현 → `기준선 미재현` |
| PR 본문 위생 | 출력 파일에 심은 표지 문자열(가짜 토큰)이 `pr_body.md` 에 나오지 않는다 |
| 한 워크트리 한 버그 | 진행 중 slug 가 있으면 `init` exit 2 |
| `bp_ui.py serve` | 가짜 서버로 준비 대기 · 타임아웃 · 프로세스 그룹 종료 |
| 프로파일 schema 2 | 기존 테스트 이관 + `exec`·`ui` 거부 경로 · `regress` 없음 허용 |
| `bp_profile.py init` | 스택 신호별 초안 · 초안이 `check` 에 거부됨 · 기존 파일 보존 · 신호 0/2+ |
| 템플릿 | 스택마다 «실패·통과·오류» 트리 실측 (계획 A 의 수동 검증 단계) |
| `install.sh` | `core.hooksPath` 두 경우(§8) 회귀 테스트 |
| 계약 린트 `tests/test_contracts.py` | `SKILL.md` · 에이전트 문서의 산출물 파일명·명령이 `bp_gate.py` 상수와 일치하는지 · `description` 트리거가 영어·한국어 둘 다 있는지 |
| P6 포지 | `gh`/`glab` 있음·없음 · 원격 없음 → `pr_body.md` 까지 |
| 종단 | 원천이 아닌 다른 프로젝트에서 실제 버그 — 두 트랙 각 하나 |

## 14. 구현 분할

스펙 하나, 계획 셋:

- **계획 A (코드)** — 프로파일 schema 2(파일·`exec` 선택, `bp_exec_local` 기본값) · `bp_profile.py init` · 템플릿 ·
  `bp_gate.py` 명령 12종(트리아지 · 커밋 감사 · 기준선 캐시 · 이관 · `light-verify`/`light-report` 포함) ·
  `bp_regress` 캐시 입력 · `bp_ui.py` · `install.sh` 수정. 크기상 A1(프로파일·온보딩) / A2(`bp_gate`) / A3(`bp_ui`)
  로 나눠 써도 된다
- **계획 B (문서)** — `SKILL.md` · 에이전트 6종 · 계약 린트. A 의 상수를 인용하므로 A 다음
- **계획 C (종단)** — 다른 프로젝트에서 실제 버그, 트랙별 하나

## 15. 범위 밖 · 알려진 공백

- 중량 경로(worktree + team mode)
- 비결정 버그의 **결정론** 판정(반복 측정의 임계 — 「N 번 중 몇 번이면 빨강인가」는 별도 설계). v1 은 가벼운 트랙 + 표지
- Windows 네이티브 · 네이티브 UI 스윕
- 버그별 표적 보강(결함의 기존 테스트가 `side_cmd` 수집 루트 밖에 있을 때) — 루브릭의 몫
- 전수 CTA 스윕 — 별도 「메뉴 점검」 모드 후보
- `bp_regress` 리뷰에서 미룬 Minor 6건
