# 게이트 — `scripts/bp_gate.py`

파이프라인의 상태와 판정을 **코드가** 집행한다. 행 순서·중단·진리표 인자 매핑·cap·변조 검사·커밋 감사를 LLM 이
산문을 읽고 따르는 대신 이 파일이 한다. 설계:
[`superpowers/specs/2026-09-25-skill-v1-design.md`](superpowers/specs/2026-09-25-skill-v1-design.md) §3 · §5 · §6.

```sh
python3 <플러그인>/scripts/bp_gate.py <명령> <slug> [옵션]     # 호출 루트 = cwd 의 git 최상위
python3 <플러그인>/scripts/bp_gate.py --selftest
```

## 명령

| 명령 | 트랙 · 단계 | 전제 | 하는 일 |
|---|---|---|---|
| `init <slug>` | 공통 P0 | `.bugfix-pipeline/` 가 git 무시 경로 · 진행 중인 다른 slug 없음 | 작업공간 · `ledger.json` · `repro.md` 양식 |
| `triage <slug> [--light] [--repro-confirmed]` | 공통 P0 | 아직 트리아지 전. `repro.sh` 가 있으면 `--repro-confirmed` 필수 | 재현 3 회 · 스위트 유무 · `--light` → 트랙. 이때의 HEAD 가 `base_sha` |
| `freeze <slug>` | 정식 GATE 1 | 정식 트랙 · 동결 전 | `rubric.json`·`root_cause.json`·`repro.md` 검사 → 동결 해시 |
| `refreeze <slug> --reason R [--refund-last]` | 정식 GATE 1 재진입 | 동결 후 | 재동결 · `cause_id` 가 바뀌면 원인 교체 이력 · `--refund-last` 는 직전 `CODE` 환불(사용자 승인) — **동결 파일이 하나 이상 바뀌어야** 하고, `DEFERRED` 에서 cap 아래로 내려가면 단계를 P5 로 되돌린다. 기준선 이후 `cause_id` 가 바뀌면 단계 P2(새 RED) |
| `baseline <slug> --red F…` | 정식 P2 | 정식 트랙 · 동결 후 · 기준선 없음, **또는 단계 P2**(`ANCHOR` · 원인 교체 뒤) | 첫 RED 커밋의 부모 = 기준선 sha · RED 파일 blob 해시. P2 재진입이면 기준선 sha 는 그대로 두고 다시 쓴 RED 의 blob 만 재기록(이력 `rebaseline`) — 그 밖의 재호출은 2 |
| `run <slug>` | 정식 P5 | 정식 · 동결 · 기준선 · cap 미도달 | 아래 |
| `record-sweep <slug> --regression F` | 정식 P5b | 정식 · 동결 · 근거 파일이 작업공간 안 | 진리표에 `regress=False` → `CODE` +1 |
| `promote <slug> --reason R` | 가벼운 → 정식 | 트리아지가 결정적 · 스위트 있음 · `DEFERRED` 아님 · 깨끗한 트리 · **가벼운 수정을 되돌려 트리가 트리아지 때와 같음**(`git revert`) | 승급, 단계 P1 · `base_sha` = 지금 HEAD(되돌린 커밋은 감사 밖) |
| `to-light <slug> --kind K --reason R` | 정식 → 가벼운 | 정식 트랙 · `DEFERRED` 아님(cap 을 트랙 변경으로 빠져나가지 않는다) | `K` = `cannot-measure` · `unstable` · `size` |
| `light-verify <slug>` | 가벼운 | 수정 커밋이 있음 · **작업 트리가 깨끗함** | 재현 축 · 회귀 축을 **직접 실행**해 기록 |
| `light-report <slug>` | 가벼운 | 마지막 검증 이후 커밋 없음 | 표지 계산 → `light_report.md`(로컬) · `pr_body.md` |
| `status <slug> [--close done\|abandoned] [--pr-body]` | 공통 | — | 요약 · 종료 기록 · 정식 PR 본문 |
| `serve <slug> --side baseline\|after` | 정식 P5b | 프로파일 `ui` | 기준선 사본(레포 밖) 또는 현재 트리를 `ui.serve_cmd` 로 띄워 `BP_URL=<url>` 한 줄을 내고 SIGTERM·SIGINT·SIGHUP 까지 머문다 — 끝나면 서버 그룹과 사본을 치운다 |

종료코드: `0` 성공(`run` 은 PASS) · `1` `run`/`record-sweep` 판정이 PASS 아님 · `2` 설정 오류·변조·감사 실패 ·
`3` 예상 못 한 예외(판정이 아니다) · `4` cap 도달(`DEFERRED`).

## `run`

0. **깨끗한 작업 트리** — 커밋 안 된 변경(추적 · 미추적, 무시 경로 제외)이 있으면 2. 게이트는 «커밋된» 트리를 잰다 —
   커밋 안 된 수정은 감사와 변조 검사를 비껴가 PASS 를 만든다.
1. **변조 검사** — 동결 파일(`rubric.json` · `root_cause.json` · `repro.md` · `repro.sh` · patch) sha256 와 RED 파일
   blob 해시. 다르면 2.
2. **커밋 감사** — `기준선..HEAD` 의 `feat`·`fix` 커밋은 **모두** 본문에 `RED: <기준선 이후 다른 커밋 sha>` 가 있어야
   한다. 없으면 2. git 훅이 없어도 이것이 RED 규칙을 집행한다. 트리아지 이후 RED 커밋 «전»에 들어간 `feat`·`fix` 도 2.
3. `R-CONTROL` → `R-CAUSE` → `R-SYMPTOM` → `R-REGRESS`. FAIL 이면 멈추고 뒤 행은 `None`. probe exit 125 ·
   사본·변이 실패 · `bp_regress` 2/3 → `probe_ok=False`(ENV).
4. `verdict()` → `code_count += cap_delta` → `verdict_<n>.json`. `code_count` 가 3 이 되면 그 자리에서 `DEFERRED` · 4.

| 판정 | 다음 단계 |
|---|---|
| `PASS` | P5b |
| `CODE` | P3 (`R-REGRESS` 가 원인이면 `new_red.txt` 를 먼저 사용자에게 — 원인과 무관하면 `SPEC` 으로 GATE 1) |
| `ANCHOR` | P2 재작성 |
| `VOID` · `ENV` | 측정·환경을 고쳐 재측정. 연속 2 회면 `status` 가 `to-light --kind unstable` 을 제안 |

### 사본

`R-CONTROL` 축과 기준선은 **레포 밖**(`mkdtemp(prefix="bp-copy-")`, 프로파일 `regress.allowed_roots` 가 있으면 그 첫
항목 아래)에 `git worktree add --detach` 로 만들고 `finally` 에서 폐기한다. 레포 안이면 루트 쪽 스위트가 사본의
테스트까지 수집한다.

### 캐시

| 캐시 | 키 | 무효 |
|---|---|---|
| `control_cache.json` | HEAD · 동결 집합 전체 해시(patch · `repro.sh` 포함) · 기준선 sha · `exec` 해시(래퍼 또는 `bp_exec_local.py` 내용) · `ui` 해시(설정 + `serve_cmd` 래퍼 내용) | 새 커밋 · 재동결 · 래퍼 변경 |
| `baseline_cache/<sha>/` | 기준선 sha · `regress` 해시(설정 + `side_cmd` 래퍼 내용) | 프로파일 `regress` 나 래퍼 변경. **기준선 쪽이 전수로 돈 실행만** 저장한다 |

## 작업공간 파일

| 파일 | 누가 | 형식 |
|---|---|---|
| `repro.md` | P0 · GATE 1 | 한 줄 `키: 값` — `steps:` · `observed:` · `where:` · `needs_ui:` · `url:` · `expected_after:` |
| `repro.sh` | P0 (재현 자동화) | `repro.sh <트리> [<URL>]` — `observed` 를 출력으로 드러낸다. `needs_ui: yes` 면 두 번째 인자로 그 트리를 서빙하는 앱의 URL |
| `root_cause.json` | 조사자 | `cause_id` · `verdict`(`BUG`/`NOT-A-BUG`/`CANNOT-MEASURE`) · `file` · `line` · `fix_scope` |
| `rubric.json` | 조사자 → GATE 1 | 아래 |
| `control/*.diff` | 조사자 | `git apply` 할 수 있는 patch |
| `light_cause.json` | 가벼운 트랙 수정자 | `file` · `line` · `summary` (PR 본문에 들어간다) |

```json
{
  "cause_id": "value-01",
  "R-CAUSE":   { "probe": ["{exec}", "{tree}", "--", "sh", "check.sh"] },
  "R-SYMPTOM": { "probe": ["{exec}", "{tree}", "--", "sh", "{repro}", "{tree}"],
                 "assert": ["grep", "-q", "good", "{out}"] },
  "R-CONTROL": { "axes": [
      { "name": "수정 되돌림", "mutate": { "checkout": "@baseline" } },
      { "name": "broken 추가", "mutate": { "patch": "control/broken.diff" },
        "alive": ["{exec}", "{tree}", "--", "sh", "other.sh"] } ] }
}
```

- 자리표시자: `{exec}` · `{tree}` · `{out}` · `{repro}` · `{url}`. `{url}` 은 프로파일에 `ui` 가 있을 때만 — 그 행을
  잴 때마다 `bp_ui` 가 **그 행의 트리**(원본 또는 사본)로 앱을 띄우고 내린다.
- `assert` 가 없으면 probe 종료코드 == 0.
- `R-CONTROL` 축은 사본에 변이를 걸고 `R-CAUSE` 를 잰다 — **빨개져야** 통과, `alive` 는 초록이어야 한다.
  `@baseline` 은 «수정 되돌리기»(조사자는 P1 에서 기준선 sha 를 모른다).
- `R-REGRESS` 는 루브릭에 없다 — 게이트가 `bp_regress` 로 고정 실행한다.

## 가벼운 트랙 표지

`light-report` 는 **`ledger.json` 의 `light_verifications[]` 만** 보고 계산한다. 에이전트 보고로 지울 수 없다.

| 표지 | 붙는 조건 |
|---|---|
| `결정론 판정 없음` | 마지막 검증에 «수정 전 재현 · 수정 후 사라짐»이 결정적으로 없음(수정 후 재현의 exit 가 0 도, 수정 전 exit 도 아니면 «죽은» 것으로 본다) · 또는 `to-light --kind cannot-measure\|unstable` 이력. **수정 후만 잰 경우**(`기준선 미재현`)는 수정 후에도 재현됨 · 수정 후 exit ≠ 0 · 트리아지 3 회가 모두 관측되지 않았거나 exit 가 달랐음 중 하나일 때 |
| `회귀 미검증` | 마지막 검증에 회귀 축이 없음(`regress` 섹션 없음) 또는 측정 무효 |
| `기준선 미재현` | 화면 재현(`needs_ui: yes`)인데 프로파일에 `ui` 가 없어 `url:`(사용자 서버)로 **현재 트리만** 쟀다 |

화면 재현의 트리아지: `ui` 가 있으면 `bp_ui` 로 띄워 3 회. `ui` 가 없으면 사용자 URL 로 재지만 **결정적으로 치지
않는다**(기준선 사본을 잴 수 없어 정식 트랙의 `R-SYMPTOM` 이 성립하지 않는다).

## PR 본문 위생

`pr_body.md` 는 판정 · 종료코드 · 실패 이름 · 표지 · 변경 파일 목록만 담는다. **명령 출력 원문은 읽지 않는다** —
토큰 · `.env` 값 · 내부 URL 이 섞일 수 있다. 원문 발췌는 작업공간(무시 경로)의 `light_report.md` 에만.
