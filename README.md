# bugfix-pipeline

버그 수정 요청 하나를 **원인 규명 → 수정 → 검증 → QA → CTA 전수 스윕 → PR** 까지 잇는 Claude Code 플러그인.

핵심 성질은 **통과 기준을 수정이 존재하기 전에 동결해 결정론적으로 판정한다**는 것이다. 판정은 LLM 이 아니라 `assert` 의 종료코드이고, 귀속(무엇을 고쳐야 하는가)은 진리표가 낸다.

## 왜 결정론인가

버그 수정 하네스가 실패하는 전형적 방식은 **원인을 안 고치고 다른 방향으로 새는 것**이다. 게이트가 FAIL 을 내면 구현자가 새 가설로 갈아타고, 세 번쯤 돌면 원래 원인은 손도 안 댄 채 다른 것을 고치고 있다.

이 파이프라인은 그것을 세 곳에서 막는다.

| 장치 | 무엇을 막나 |
|---|---|
| **입구 동결 재현** — 조사 «전»에 사용자가 본 것을 동결하고 맨 끝에 재생 | RED 는 초록인데 증상이 남은 상태 = 엉뚱한 것을 고쳤다 |
| **귀속 진리표** — 어느 행이 FAIL 했는지로 라우팅이 기계적으로 갈린다 | 나쁜 기준(ANCHOR)을 구현 실패(CODE)로 오분류해 예산을 태우는 것 |
| **`RED: <sha>` commit-msg 훅** — git 이 항상 부른다 | 테스트 없는 수정이 들어가는 것 |

## 루브릭 — 필수 4행

각 행은 실행 가능해야 한다: `probe`(관측을 뽑는 명령) · `extract`(원문 → 값, 양쪽에 같은 것 하나) · `assert`(값 → exit 0/1, **이것이 판정**) · `mutate`(`R-CONTROL` 전용, 고의로 깨는 방법).

| id | 묻는 것 | 없으면 |
|---|---|---|
| `R-CAUSE` | 원인의 **불변식**이 성립하나 | 수정이 원칙적인지 모른다 |
| `R-SYMPTOM` | 입구 동결 재현 → 확정된 기대값 | 엉뚱한 걸 고쳐도 초록 |
| `R-REGRESS` | 실패 **이름 집합** 차집합 0 | 옆을 깨고 초록 |
| `R-CONTROL` | **고의로 깨면 빨개지나** | 초록이 거짓일 수 있다 |

## 귀속 진리표

| `R-CONTROL` | `R-CAUSE` | `R-SYMPTOM` | `R-REGRESS` | 귀속 | cap |
|---|---|---|---|---|---|
| **FAIL** | — | — | — | `VOID` (측정이 대상을 안 본다) | 안 셈 |
| PASS | FAIL | — | — | `CODE` (구현이 덜 됐다) | **+1** |
| PASS | PASS | **FAIL** | — | `ANCHOR` (**기준이 틀렸다**) | 안 셈 |
| PASS | PASS | PASS | FAIL | `CODE` (회귀) | **+1** |
| PASS | PASS | PASS | PASS | `PASS` | — |
| `probe` 실행 실패 | — | — | — | `ENV` | 안 셈 |

**cap 은 `CODE` 만 센다.** 그렇지 않으면 나쁜 기준이 예산을 태우고 원인은 끝까지 안 고쳐진다.

## 설치처에서 진리표를 검증하는 법

이 파이프라인의 결정론 전체가 진리표 위에 서 있다. 그래서 **설치된 프로젝트에서** 그것이 옳게 도는지 증명할 수 있어야 한다 — 의존 0, pytest 불필요:

```sh
python3 scripts/bugfix_verdict.py --selftest
```

진리표 8행 전수 + `ValueError` 경로 4개를 검사한다. P0 가 이것을 선행 조건으로 부른다.

> 왜 pytest 가 아닌가: 이 파일은 임의의 호스트 프로젝트에 설치된다. pytest 가 있다고 가정할 수 없다 — 실측에서 개발 랩탑 호스트 python3 에 없었다. 레포의 `tests/` pytest 스위트는 «개발용»이고 `--selftest` 는 «설치처용»이다.

## `RED: <sha>` 훅

```sh
hooks/install.sh install     # 설치
hooks/install.sh verify      # 🔴 실제로 불리는지 증명
hooks/install.sh uninstall   # 제거 (작업 가지 한정이므로 끝나면 반드시)
```

`verify` 는 선행 조건 2축(훅이 **있는가** · **실행 가능한가**)과 세 축(RED 없는 `fix` 거부 / RED 있는 `fix` 통과 / `docs` 무간섭)을 흔든다.

> 🔴 `git hook run <hook>` 은 훅이 **없을 때도 exit 1** 이다(`error: cannot find a hook named …`). 종료코드만 보면 「훅이 거부했다」와 「훅이 없다」가 같은 얼굴이라 거짓 초록이 난다 — 실측으로 확인했고, 그래서 `verify` 가 선행 조건과 표지 문구로 둘을 가른다.

## 현재 상태 (v0.1.0 — 스캐폴드)

> 🔴 **아래 표는 2026-09-22 스캐폴드 시점이다.** 그 뒤 원천 프로젝트에서 실전을 돌려 이식본이 이미 낡았다(훅 가지 한정 누락 등). 격차 목록은 메인테이너 로컬 전용 인수인계 문서(`docs/private/`, gitignore — 원천 프로젝트가 비공개라 공개하지 않는다)에 있다.

| 구성물 | 상태 |
|---|---|
| `scripts/bugfix_verdict.py` (+ `--selftest`) | ✅ 이식 완료 · 호스트 실행 확인 · 양방향 양성 대조 확인 |
| `tests/test_bugfix_verdict.py` | ✅ 이식 (pytest, 개발용) |
| `hooks/commit-msg` · `hooks/install.sh` | ✅ 이식 완료 · 실제 `git commit` 차단 실측 |
| `agents/bug-root-cause-investigator.md` | ⚠️ 이식했으나 **아직 탈-프로젝트화 안 됨** |
| `skills/bugfix-pipeline/SKILL.md` | ❌ **미이식** — 원본이 특정 리포에 결합돼 있어 프로파일 기반으로 재작성 필요 |
| 범용 에이전트 6개 (RED · GREEN×2 · 게이트 · 스위퍼 · 스윕게이트) | ❌ **미작성** |
| 프로파일(자동 감지 + 캐싱) | ❌ **미작성** |

## 남은 설계 결정

- 프로파일 스키마 — 특히 경로의 **기준 루트**(워크트리·모노레포에서 상대 경로가 어디 기준인지 모호해진다)
- 범용 에이전트 6개를 어느 기존 규율에서 추릴지
## 설치

```sh
# 개발 중 — 설치 없이 한 세션만
claude --plugin-dir /path/to/bugfix-pipeline

# 로컬 디렉토리를 마켓플레이스로
claude plugin marketplace add /path/to/bugfix-pipeline
claude plugin install bugfix-pipeline@bugfix-pipeline-marketplace
```

두 경로 모두 2026-09-24(Claude Code 2.1.281)에 세션 `init` 의 에이전트 목록으로 적재를 확인했다. 🔴 `skills/bugfix-pipeline/SKILL.md` 가 아직 없으므로 설치해도 **파이프라인 자체는 호출할 수 없다** — 지금 적재되는 것은 조사자 에이전트 하나다.

## 플러그인 레이아웃 근거

설치된 플러그인에서 확인한 규약(추측 아님):

- `agents/` 루트 — `code-simplifier/1.0.0/agents/` · `feature-dev/*/agents/`
- 에이전트는 `plugin:agent` 로 네임스페이스되므로 **호스트 프로젝트 에이전트와 이름이 겹쳐도 충돌하지 않는다**
- 에이전트 frontmatter: `name` · `description` · `model`
- `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`(`plugins[].source: "./"`) 으로 단일 레포가 마켓플레이스와 플러그인을 겸할 수 있다
