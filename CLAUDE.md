# bugfix-pipeline — 작업 지침

Claude Code 플러그인 레포다. 버그 수정 요청을 원인 규명 → 수정 → 검증 → QA → CTA 전수 스윕 → PR 까지 잇는 오케스트레이터를 «다른 프로젝트에 이식 가능한» 형태로 만든다.

설계 배경과 현재 상태는 `README.md` 를 먼저 읽는다. 특히 「현재 상태」 표 — 무엇이 실측으로 확인됐고 무엇이 미완인지가 거기 있다.

## 이 레포의 성격 — 「이식 가능」이 모든 결정을 지배한다

이 코드는 **어떤 프로젝트에 설치될지 모른다.** 그래서 다음을 가정하지 않는다.

| 가정하지 않는 것 | 왜 |
|---|---|
| Docker 가 있다 | 없는 프로젝트가 있다. 진리표는 의존 0 순수 함수이므로 호스트 `python3` 로 돈다 |
| pytest 가 있다 | **실측: 개발 랩탑 호스트 python3 에 없었다.** 그래서 `--selftest` 가 별도로 있다 |
| 특정 테스트 러너·디렉토리 구조 | 프로파일이 감지하고, 못 재면 「모른다」로 남긴다 — 추정하지 않는다 |
| 특정 에이전트가 존재한다 | 플러그인이 자기 에이전트를 `agents/` 에 번들한다 |
| 경로의 기준 루트가 자명하다 | 워크트리·모노레포에서 모호해진다. 프로파일에 base 를 명시한다 |

**하드코딩을 발견하면 프로파일로 뺀다.** 원본(원천 프로젝트의 in-repo 스킬)에는 컨테이너 이름·포트·`docs/cycles/INDEX.md` 같은 결합이 남아 있다 — 그대로 옮기면 안 된다.

## 검증 규율 — 이 레포가 스스로 지켜야 하는 것

이 파이프라인이 남에게 요구하는 규율을 자기에게 먼저 적용한다.

- **0 과 초록은 답이 아니라 질문이다.** 검사가 통과하면 «고장난 상태에서 빨개지는지»를 확인한다. 실측 선례: `--selftest` 는 `cap_delta` 사보타주로, `hooks/install.sh verify` 는 훅 제거·실행권한 제거 두 축으로 대조했다.
- **양성 대조에도 축이 있다.** 검사가 두 조건에 걸리면 두 축을 다 흔든다. 한 축만 흔들면 나머지가 통과 쪽에 고정돼 대조가 초록인 채로 결함이 산다.
- **「있다」가 「불린다」가 아니다.** 훅·스크립트를 만들었으면 **호출자를 센다.** 0 이면 그건 집행이 아니라 주석이다. 실측 선례: `git hook run` 은 시뮬레이션이고, 실제 `git commit` 으로 차단을 확인해야 한다.
- **종료코드 하나로 두 상태를 구분하려 하지 않는다.** 실측: `git hook run <h>` 은 훅이 «없을 때도» exit 1 이다. 「거부」와 「부재」가 같은 얼굴이면 선행 조건이나 표지 문구로 가른다.
- **앵커는 값 이름이 아니라 불변식으로 건다.** "`cycle_year` 가 2027" ✗ → "화면이 자기가 보여 주는 사이클을 명시한다" ○. 이름을 박으면 대상이 진화할 때 앵커가 stale 해진다.
- **자기보고는 증거가 아니다.** 판단을 뒤집을 때는 `파일:라인` + 실제 조회 결과를 함께 낸다.

## 셸·Git

- Bash 는 **절대경로 + 한 번에 한 명령.** `cd` 로 디렉토리 상태를 오염시키지 않는다.
- 커밋은 `git commit -m "…" -- <경로>` 로 대상 경로만. **`git add -A` 금지.** 새 파일은 `git add <경로>` 선행. 커밋 후 `git show --stat` 으로 되읽어 확인한다.
- Conventional Commits: `<type>(<scope>): <description>`.
- `git push` 와 PR 은 사용자 승인 후에만.

## 플러그인 레이아웃 (설치본에서 확인한 규약 — 추측 아님)

```
.claude-plugin/plugin.json       name·description·version·keywords
.claude-plugin/marketplace.json  단일 레포 겸용 (plugins[].source: "./")
agents/<name>.md                 frontmatter: name·description·model
skills/bugfix-pipeline/SKILL.md
hooks/                           commit-msg · install.sh (git 훅 — Claude Code 이벤트 훅과 다르다)
scripts/                         bugfix_verdict.py (+ --selftest)
tests/                           pytest — «개발용». 설치처 검증은 --selftest 다
```

에이전트는 `plugin:agent` 로 네임스페이스되므로 **호스트 프로젝트의 동명 에이전트와 충돌하지 않는다.**

## 알려진 미확인

- (해소 · 2026-09-24, Claude Code 2.1.281) 설치 경로 세 가지가 **모두 된다** — 판정은 모델 답이 아니라 `--output-format stream-json --verbose` 의 `init` 메시지 `agents` 배열로 했다.
  - `claude --plugin-dir <레포>` — 설치 없이 그 세션만. `init.plugins[].source` 가 `bugfix-pipeline@inline`. 대조: 플래그 없는 세션엔 `bugfix-pipeline:*` 에이전트 0.
  - `claude plugin marketplace add <레포 절대경로>` → `install bugfix-pipeline@bugfix-pipeline-marketplace`. 설치본 `path` 가 캐시 사본이 아니라 **레포 디렉토리 자체**였다(편집이 즉시 반영되는지는 안 쟀다).
  - `claude plugin validate <레포>` 가 매니페스트를 검사한다(깨진 `plugin.json` 에 exit 1 확인). 현재 경고 1: `author` 없음.
  - GitHub: `claude plugin marketplace add badaboda/bugfix-pipeline` → 같은 `install`. 설치본 `path` 는 **캐시 사본**(`~/.claude/plugins/cache/bugfix-pipeline-marketplace/bugfix-pipeline/<version>`) — 푸시만으로는 안 바뀌고 `plugin update` 가 필요하다(갱신 동작은 안 쟀다).
  - 🔴 로컬 마켓플레이스와 GitHub 마켓플레이스는 **이름이 같다**(`bugfix-pipeline-marketplace`) — 시험 후 `marketplace remove` 로 치운다.
- `hooks/` 에 git 훅이 있어도 적재 오류·경고는 없었다(위 `init` 기준). 이벤트 훅 자리(`hooks/hooks.json`)와 겹치는지는 그 파일이 생길 때 다시 본다.

## 이 레포의 자체 검사를 돌리는 법

```sh
python3 scripts/bugfix_verdict.py --selftest   # 의존 0 — 설치처에서도 이것을 쓴다
hooks/install.sh verify                        # 훅이 실제로 불리는지 (설치 후)

# 개발용 pytest — 호스트에 pytest 가 없고, 레포 루트가 import 경로에 없어서 두 옵션이 다 필요하다
uvx --with pytest pytest tests -q -p no:cacheprovider -o pythonpath=.
```
