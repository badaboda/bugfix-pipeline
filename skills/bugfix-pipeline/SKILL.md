---
name: bugfix-pipeline
description: "버그 수정 요청 하나를 원인 규명 → 수정 → 결정론 판정 → 관련 화면 스윕 → PR 까지 잇는 오케스트레이터. 재현을 재서 정식 트랙(통과 기준을 수정 전에 동결하고 코드가 판정)과 가벼운 트랙(AI 가 가볍게 고치고 증명 못 한 것에 표지)으로 가른다. Triggers «fix this bug», «find the root cause and fix», «debug and fix this issue» · 트리거 «버그 고쳐줘», «원인 찾아서 고쳐», «이 버그 수정해줘»."
---

# bugfix-pipeline — 버그 수정 오케스트레이터

너는 **리더**다. 판정하지 않는다 — 판정·상태·cap·변조 검사·커밋 감사는 게이트 스크립트가 **코드로** 한다. 너는 명령을 부르고, 에이전트를 배정하고, 멈춰야 할 곳에서 멈춘다.

## 0. 선행

- **플러그인 루트** `PLUGIN` = 이 스킬의 기준 디렉토리(Base directory)의 두 단계 위. `BP=$PLUGIN/scripts`.
  플러그인 파일은 늘 `$PLUGIN/…` · `$BP/…` 로 부른다 — cwd 는 호스트 레포라 상대 경로면 호스트의 동명 파일을 부른다.
  이하 `bp_gate.py <명령>` 은 호출 루트(작업할 레포의 git 최상위)를 cwd 로 두고 `python3 $BP/bp_gate.py <명령>` 을 뜻한다.
- `python3 $BP/bugfix_verdict.py --selftest` — 진리표가 이 호스트에서 옳게 도는지. 실패면 멈춘다.
- `.gitignore` 에 `.bugfix-pipeline/` 가 있어야 한다(없으면 `init` 이 exit 2 — 사용자에게 추가를 요청).
- 프로파일 `.claude/bugfix-pipeline.json` 은 **선택**이다. 없으면 가벼운 트랙만 돈다. 있으면 `python3 $BP/bp_profile.py check`. 처음이면 `bp_profile.py init` 이 «검사를 통과하지 못하는» 초안을 쓴다 — 사람이 확인해야 쓸 수 있다.
- 한 워크트리에 버그 하나. 작업 가지를 만든 뒤 시작한다.

게이트 종료코드: `0` 성공(`run` 은 PASS) · `1` 판정이 PASS 아님 · `2` 설정 오류·변조·감사 실패(멈추고 보고) · `3` 예상 못 한 예외(판정 아님 — 보고) · `4` cap 도달(`DEFERRED`, 멈춤).

## 1. P0 — 접수 · 트리아지 (두 트랙 공통)

1. **재현 동결** — 사용자가 본 것을 `bp_gate.py init <slug>` 가 만든 `repro.md` 에 적는다: `steps` · `observed`(출력에 그대로 나올 문구) · `where` · `needs_ui`(앱 화면이 필요하면 `yes`) · `url`(프로파일에 `ui` 가 없을 때 사용자 개발 서버). `expected_after` 는 **비운다.**
2. **재현 자동화** — `steps` 를 `repro.sh` 로 옮긴다(**`steps` 가 이미 명령이어도** 감싼다 — 게이트는 `repro.sh` 만 잰다. 없으면 트리아지가 비결정 → 가벼운 트랙): `repro.sh <트리> [<URL>]`, `observed` 를 **출력으로 드러낸다.** 한 번 돌린 출력을 사용자에게 보이고 **「이게 내가 본 것」 확인**을 받는다 — 🛑 하드 스톱. 옮길 수 없으면(외부 결제 · 실기기 · 운영 데이터 전용) 사유를 `repro.md` 에 적는다.
3. `bp_gate.py triage <slug> [--repro-confirmed] [--light]` — 재현 3 회 · 스위트 유무 · 사용자가 「가볍게」를 말했는지로 트랙을 **잰다.** 결정적 + 스위트 + 가볍게 아님 → 정식, 그 밖 → 가벼운. 결과는 `ledger.json`.
4. (선택) `$PLUGIN/hooks/install.sh install` — `RED:` 규칙을 더 일찍 알려 주는 git 훅. 거부되면 경고만 — 집행은 게이트의 커밋 감사다.

재진입: 언제든 `bp_gate.py status <slug>` 로 트랙 · 단계 · 루프 N/3 을 읽는다. 정본은 `ledger.json` 한 파일이다.

## 2. 정식 트랙

| 단계 | 누가 | 무엇 | 다음 |
|---|---|---|---|
| P1 조사 | `bugfix-pipeline:bug-root-cause-investigator` | `root_cause.json` · `rubric.json` 초안 · `control/*.diff` · `investigation.md` | GATE 1 |
| GATE 1 | 🛑 사용자 | 진단 · `fix_scope` · `expected_after` 채우기 · 루브릭 확정. 리더는 사용자가 채운 `expected_after` 문구를 `rubric.json` 의 `R-SYMPTOM.assert` 자리에 옮긴다(조사자는 자리표시만 남긴다 — 그대로 동결하면 매번 FAIL) | `bp_gate.py freeze <slug>` |
| P2 RED | `bugfix-pipeline:bug-red-writer` | 실패 테스트 커밋 · sha · RED 파일 · RED 실행 명령 보고 | `bp_gate.py baseline <slug> --red <파일…>` |
| P3 GREEN | `bugfix-pipeline:bug-green-engineer` (배정에 RED sha · RED 실행 명령) | `fix_scope` 안 최소 수정 · 커밋 본문 `RED: <sha>` | P4 |
| P4 자기확인 | 같은 구현자 | RED 통과 — 보고일 뿐. 회귀는 `run` 의 `R-REGRESS` 가 기준선 사본으로 잰다 | P5 |
| P5 판정 | 게이트 | `bp_gate.py run <slug>` | 아래 표 |
| P5b 스윕 | §4 | 관련 범위 화면 | GATE 2 |
| GATE 2 | 🛑 사용자 | 재현 재생 · 카드 밖 파일 · 루프 N/3 · 원인 교체 이력 · 부채(미룬 것 · 우회) · 관찰(미판정) · P5b 생략 사유 | P6 |

**판정 결과 (`run`)**

| 종료 · 귀속 | 다음 |
|---|---|
| 0 `PASS` | P5b |
| 1 `CODE` | P3 — 같은 `cause_id` 안에서 새 가설. `R-REGRESS` 가 원인이면 `new_red.txt` 를 먼저 사용자에게 — 원인과 무관해 보이면 `SPEC` 으로 GATE 1 |
| 1 `ANCHOR` | P2 — 기준(테스트·루브릭)이 틀렸다. cap 을 쓰지 않는다. RED 를 다시 쓰면(`test(…)` 커밋) `bp_gate.py baseline <slug> --red <파일…>` 로 **재기록**한다 — 기준선 sha 는 그대로, RED 블롭만 새로(P2 에서만 허용). 루브릭이 틀렸으면 GATE 1 → `refreeze` |
| 1 `VOID` · `ENV` | 측정·환경을 고쳐 재측정. 연속 2 회면 `status` 가 이관을 제안 |
| 2 | 변조 · 커밋 감사 실패 · 더러운 트리 — 메시지를 그대로 보고하고 고친다. 우회하지 않는다 |
| 4 | `DEFERRED` — 🛑 멈추고 사용자에게. 트랙을 바꿔 빠져나가지 않는다(게이트가 거부) |

- **기준을 고칠 때** (GATE 1 재진입): 동결 파일을 고치고 `bp_gate.py refreeze <slug> --reason "<사유>"`. `cause_id` 가 바뀌면(원인 교체) 단계가 P2 로 돌아간다 — 새 원인의 RED 를 쓰고 `baseline --red` 로 재기록.
  측정 결함으로 직전 `CODE` 를 돌려받으려면 사용자 승인 후 `bp_gate.py refreeze <slug> --reason "<사유>" --refund-last` — 동결 파일이 하나 이상 **실제로 바뀌어야** 하고, `DEFERRED` 에서 cap 아래로 내려가면 P5 로 돌아온다.
- **정식 → 가벼운 이관** (사용자 승인): 조사 판정 `CANNOT-MEASURE` · `VOID`/`ENV` 연속 2 회 · GATE 1 에서 크기 강등 → `bp_gate.py to-light <slug> --kind cannot-measure|unstable|size --reason "<사유>"`.
- `NOT-A-BUG` 는 사용자가 `fix_scope` 를 승인하면 P2(표현·안내 결함), 아니면 종료.

## 3. 가벼운 트랙

1. `bugfix-pipeline:bug-light-fixer` 배정 — 원인 `파일:라인` · 수정 커밋 · `light_cause.json`. 검증은 하지 않는다.
2. **승급 신호**(`fix_scope` 2 파일 이상 · 공유 파일 · 첫 가설 실패 · 원인 두 갈래)가 보고되면: 트리아지가 결정적 + 스위트였으면 가벼운 수정 커밋을 **`git revert` 로 되돌린 뒤**(트리아지 때 트리와 같아야 한다 — 아니면 게이트가 거부) `bp_gate.py promote <slug> --reason "<신호>"` → 정식 P1. 정식 트랙의 RED 는 수정 전 트리에서 빨개져야 한다. 아니면 승급하지 않고 GATE L 에서 사용자에게 올린다.
3. `bp_gate.py light-verify <slug>` — **코드가** 재현 축(기준선 사본 vs 현재)과 회귀 축을 직접 잰다. 커밋된 깨끗한 트리에서만.
4. `bp_gate.py light-report <slug>` — 기록만 보고 표지를 계산해 `light_report.md`(로컬, 원문 발췌) · `pr_body.md` 를 쓴다. 검증 뒤 커밋이 더 있으면 exit 2 — 다시 `light-verify`.
5. **GATE L** — 🛑 `light_report.md` 를 그대로 보이고 승인을 받는다. 거부되면 가지를 버린다.
6. P6.

**표지** — 증명하지 못한 것의 이름. 에이전트 보고로 지울 수 없다.

| 표지 | 뜻 |
|---|---|
| `결정론 판정 없음` | «수정 전 재현 · 수정 후 사라짐»을 결정적으로 보이지 못했다 |
| `회귀 미검증` | 회귀 축이 없었다(프로파일 `regress` 없음) 또는 측정 무효 |
| `기준선 미재현` | 화면 재현인데 `ui` 가 없어 수정 후만 사용자 URL 로 쟀다 |

## 4. P5b — 관련 범위 스윕 (정식 트랙)

**생략 조건** — GATE 2 에 사유를 적는다: `root_cause.json` 의 `user_facing: false` · 프로파일에 `ui` 없음 · 쓸 수 있는 브라우저 도구 없음.

1. 두 쪽을 백그라운드로 띄운다 — `bp_gate.py serve <slug> --side baseline` (기준선 사본, 레포 밖) · `bp_gate.py serve <slug> --side after` (현재 트리). 각각 stdout 첫 `BP_URL=<url>` 줄이 URL 이다.
   끝나면 **둘 다** SIGTERM 으로 내린다(어떤 종료 경로에서든) — 게이트가 서버 그룹과 사본을 치운다. 래퍼 점검은 `python3 $BP/bp_ui.py check`.
2. `bugfix-pipeline:bug-cta-sweeper` — 두 URL · `routes` ∪ `affected_routes` · 계정 상태 → `sweep.json` · `sweep.md`.
3. `bugfix-pipeline:bug-sweep-gate` — 관련 후보만 확정·기각 → `gate_round<N>.md`.
4. 확정 회귀마다 `bp_gate.py record-sweep <slug> --regression <작업공간 안 근거 파일>` — 진리표가 `CODE` 를 낸다(cap 에 들어간다). exit 4 면 `DEFERRED` — 🛑 남은 후보를 기록하지 말고 멈춘다. 아니면 P3.
5. 비관련 이상은 판정하지 않는다 — GATE 2 에 「관찰(미판정)」.

## 5. P6 — PR

- 정식: `bp_gate.py status <slug> --pr-body` 가 `pr_body.md` 를 쓴다. 가벼운: `light-report` 가 이미 썼다.
- **PR 본문은 `pr_body.md` 만 쓴다.** 명령 출력 원문(토큰 · `.env` 값 · 내부 URL 이 섞일 수 있다)을 붙이지 않는다.
- `gh`(GitHub) 또는 `glab`(GitLab) 이 있고 원격이 그 포지를 가리키면: 경로 지정 커밋 → push → PR/MR. 🛑 push 와 PR 은 사용자 승인 후 — 원격이 사용자의 것이 아니면(남의 OSS) 포크로 보낼지도 사용자가 정한다.
- `pr_body.md` 는 한국어로 나온다 — 다른 언어가 필요한 곳이면 사용자 승인 전에 옮기고, 옮긴 것을 보인다(판정·표지·종료코드의 사실은 바꾸지 않는다).
- 없으면 가지를 push 하고(원격이 있으면) `pr_body.md` 경로를 알린 뒤 **멈춘다** — 포지를 추측하지 않는다.
- 끝나면 `bp_gate.py status <slug> --close done` (버리면 `--close abandoned`). 훅을 설치했으면 `$PLUGIN/hooks/install.sh uninstall`.

## 6. 리더 규율

- **배정 «직후» 감시를 건다** — `sh $BP/watch.sh <workspace> <완료 파일> [정체 분]` 을 백그라운드 감시(Monitor 도구가 있으면 그것)로. 한 줄 출력이 이벤트다: `DONE` · `STALL` · `ALIVE`.
  완료 파일: 조사자 `investigation.md` · 스위퍼 `sweep.md` · 스윕 게이트 `gate_round<N>.md` · 가벼운 수정자 `light_cause.json`. RED 작성자 · GREEN 구현자는 작업공간에 파일을 내지 않는다(커밋만) — 감시 대신 에이전트 완료 알림과 `git log` 로 확인한다.
- `STALL` 이면 깨우기 전에 **다른 채널로 확인**한다(작업공간 파일 · 프로세스). 「조용함」은 「진행 중」이 아니다.
- 팀원이 반박하면 **근거가 주장을 증명하는지** 따진다 — 자기보고는 증거가 아니다.
- 긴 측정 전에 전원·수면 설정을 확인한다.
- 스크린샷은 텍스트 누출 검사 밖이다 — PR 에 붙이지 않는다.
- 에이전트 배정 메시지는 한 모양: `workspace`(작업공간 절대경로) · `tree`(호출 루트) · `cause_id`(정식 트랙) + 단계별 입력.

## 7. Lock-in

- RED 작성자 ≠ GREEN 구현자.
- 채점자는 코드다(`bp_gate.py run` · `light-verify` · `light-report`) — LLM 이 아니다.
- 루브릭 작성자(조사자) ≠ 채점자. `expected_after` 는 사용자가 채운다.
- 귀속은 진리표가 낸다. cap 은 `CODE` 만 센다(3).
- 표본은 전수다. 루프백은 같은 `cause_id` 안에서만 — 원인이 바뀌면 GATE 1 로.
- 같은 우회를 두 번째 쓰면 그건 결함이다 — 보고한다.
- 가벼운 트랙의 검증과 표지는 코드가 낸다 — 에이전트 보고가 아니다.

## 8. 어떤 종료 경로에서든

측정 사본과 게이트가 띄운 서버는 게이트가 치운다. 네가 P5b 에서 띄운 서버는 네가 내린다. 훅을 설치했으면 제거한다. 중단한 버그는 `status --close abandoned` 로 닫아야 다음 버그를 `init` 할 수 있다.

상세: 플러그인의 `docs/gate.md`(명령 · 작업공간 파일 · 캐시) · `docs/profile.md`(프로파일 · 래퍼 계약).
