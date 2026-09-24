# 프로파일 — 호스트 프로젝트 설정

bugfix-pipeline 은 호스트 프로젝트에 대해 추정하지 않는다. 호스트가 `.claude/bugfix-pipeline.json` 과 래퍼
스크립트를 커밋한다. **이 파일은 선택이다** — 없으면 가벼운 트랙만 돈다. 설계 근거:
[`superpowers/specs/2026-09-25-skill-v1-design.md`](superpowers/specs/2026-09-25-skill-v1-design.md) §4 · §10.

## 시작하기

```sh
python3 <플러그인>/scripts/bp_profile.py init    # 레포 신호로 템플릿을 골라 초안을 쓴다
# .claude/bugfix-pipeline.json 과 .claude/bugfix-pipeline/*.sh 를 확인하고 "_draft" 키를 지운다
python3 <플러그인>/scripts/bp_profile.py check   # exit 0 OK · 2 문제 목록
```

`init` 은 신호가 **정확히 하나**일 때만 쓴다(`pyproject.toml` 등 → pytest, `vitest.config.*` → vitest). 신호가
없거나 둘 이상이면 고르지 않고 목록만 보인다. 이미 있는 파일은 덮어쓰지 않는다. 초안에는 `"_draft"` 키가 있어
`check` 가 거부한다 — 사람이 확인하기 전에는 쓸 수 없다.

## 파일

```json
{
  "schema": 2,
  "exec":    { "exec_cmd": [".claude/bugfix-pipeline/bp_exec.sh"] },
  "regress": {
    "side_cmd": [".claude/bugfix-pipeline/bp_side.sh"],
    "ran_fully": "^=+ .*[0-9]+ (passed|failed|errors?)",
    "not_fully": "Interrupted|INTERNALERROR",
    "tree_marker": "pyproject.toml"
  },
  "ui": { "serve_cmd": [".claude/bugfix-pipeline/bp_serve.sh"], "ready_marker": "^BP_URL=", "ready_timeout_s": 120 }
}
```

위 `exec`·`regress` 는 `templates/pytest/` 그대로다(`tree_marker` 는 `init` 이 찾은 신호 파일). `ui` 는 예시다 —
v1 템플릿에는 `serve_cmd` 가 없다.

| 섹션 · 필드 | 필수 | 기준 | 뜻 |
|---|---|---|---|
| `schema` | ✔ | | 정수 `2` |
| `exec.exec_cmd` | 섹션 안에서 ✔ | 호출 루트 | 「트리에서 명령 하나」 래퍼. 섹션이 없으면 내장 기본값 |
| `regress.side_cmd` | 섹션 안에서 ✔ | 호출 루트 | 전체 스위트 래퍼 |
| `regress.ran_fully` | 섹션 안에서 ✔ | | `grep -E` — 로그에 있어야 전수가 돈 것 |
| `regress.not_fully` | | | `grep -E` — 로그에 있으면 전수가 안 돈 것 |
| `regress.tree_marker` | 섹션 안에서 ✔ | 측정 트리 | 각 트리에 있어야 하는 경로 — 빈 마운트·엉뚱한 트리를 막는다 |
| `regress.allowed_roots` | | 절대 (`~` 허용) | 두 트리와 출력이 이 아래여야 한다 (예: 홈만 공유하는 VM) |
| `ui.serve_cmd` | 섹션 안에서 ✔ | 호출 루트 | 그 트리로 앱을 띄우는 래퍼 |
| `ui.ready_marker` | 섹션 안에서 ✔ | | `grep -E` — 준비 신호 줄(`BP_URL=<url>`) |
| `ui.ready_timeout_s` | | | 양의 정수, 기본 120 |

- 명령 배열의 첫 요소에 `/` 가 있으면 호출 루트 기준 파일(실행 권한 필요), 없으면 PATH 명령.
- 호출 루트 = 명령을 부른 곳의 git 최상위.
- 거부하는 것: 모르는 키(섹션 안 포함) · `schema: true` · 빈 줄에도 걸리는 패턴 · 개행이 든 패턴 · 빈
  `allowed_roots` · `_draft`.
- **schema 1 에서 옮기기**: 섹션은 그대로 두고 `"schema": 2` 로 바꾼다.

섹션의 의미:

| 없는 섹션 | 결과 |
|---|---|
| 파일 전체 | 가벼운 트랙만 — 무설정 |
| `exec` | 내장 기본값 `bp_exec_local` — 그 트리 디렉토리에서 명령을 그대로 |
| `regress` | 스위트 없는 프로젝트 — 정식 트랙 불가, 가벼운 트랙은 `회귀 미검증` |
| `ui` | P5b(화면 스윕) 생략 |

## `exec` 계약

`<exec_cmd…> <트리> -- <명령…>` — cwd 는 호출 루트, 명령의 종료코드를 그대로 돌려준다.

- **환경을 조립하지 못하면 exit 125.** 「probe 가 돌지 못했다」(ENV)와 「돌았는데 FAIL」을 가른다.
- 🔴 **사본에는 git 이 추적하지 않는 파일이 없다** — `.venv` · `node_modules` · `.env` · 빌드 산출물. 래퍼가 원본의
  것을 공유하거나 설치한다. 템플릿의 방식:

  ```sh
  # templates/pytest/bp_exec.sh — 트리의 .venv, 없으면 호출 루트의 .venv
  root=$(pwd)
  if [ -d "$tree/.venv" ]; then
    PATH="$tree/.venv/bin:$PATH"; export PATH
  elif [ -d "$root/.venv" ]; then
    PATH="$root/.venv/bin:$PATH"; export PATH
  fi
  ```

  ```sh
  # templates/vitest/bp_exec.sh — 사본에 호출 루트의 node_modules 를 링크(사본은 폐기된다)
  if [ ! -e "$tree/node_modules" ] && [ -d "$root/node_modules" ]; then
    ln -s "$root/node_modules" "$tree/node_modules" || exit 125
  fi
  ```

- 기본값 `bp_exec_local` 은 사본 의존성을 해결하지 않는다. 그런 프로젝트는 `exec` 를 둔다.

## `regress.side_cmd` 계약

`<side_cmd…> <트리 절대경로> <이름 출력 절대경로>` — cwd 는 호출 루트, 두 쪽이 같은 래퍼.

1. 어느 쪽인지 알려 주지 않는다. 쪽마다 다르게 굴 수 없어야 대칭이다.
2. stdout·stderr 가 곧 로그다. `ran_fully`·`not_fully` 가 여기에 걸린다.
3. 이름 출력: 한 줄에 실패 id 하나. `#` 줄·빈 줄 무시, 정렬 불필요. 안 쓰면 측정 무효.
   🔴 **id 는 트리 기준 상대경로여야 한다** — 절대경로면 기준선 사본과 수정 후 트리의 경로가 달라 모든 실패가
   새 빨강이 된다(vitest JSON 리포터는 절대경로를 낸다 — 템플릿이 상대경로로 바꾼다).
4. 종료코드는 판정에 쓰지 않는다.
5. **주어진 트리를 잰다.** 떠 있는 스택에 exec 하면 사본이 아니라 원본을 잰다.

## `ui.serve_cmd` 계약

`<serve_cmd…> <트리>` — 그 트리로 앱을 띄우고 stdout 에 `ready_marker` 에 걸리는 줄 `BP_URL=<url>` 을 한 번
낸다. 플러그인은 `ready_timeout_s` 까지 기다리고, 끝나면 프로세스 그룹에 SIGTERM, 10 초 뒤 SIGKILL.

## 템플릿 (실측한 것만)

| 스택 | 경로 | 실측 (2026-09-25, 루트와 `git worktree` 사본 동일) |
|---|---|---|
| pytest | `templates/pytest/` | 실패1·통과1·fixture 오류1 → 이름 2줄, 요약 줄이 `ran_fully` 에 걸림. 수집 오류 → `not_fully` 로 무효 |
| vitest | `templates/vitest/` | 실패1·파일 오류1 → 이름 2줄(상대경로), `Test Files` 줄이 `ran_fully` 에 걸림. 파일 오류만 있어도 걸림 |
| go | — | 측정 환경이 없어 템플릿 없음 |

pytest id 에 ` - ` 가 들어 있으면 pytest 템플릿의 `sed` 가 잘라 낸다 — 그런 id 를 쓰는 프로젝트는 추출을 바꾼다.

## R-REGRESS 실행

```sh
python3 <플러그인>/scripts/bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리>
```

| exit | 뜻 | 진리표 |
|---|---|---|
| 0 | 새 빨강 0 | `regress=True` |
| 1 | 새 빨강 있음 — `new_red.txt` | `regress=False` |
| 2 | 설정 오류(`regress` 섹션 없음 포함) — 고치고 다시 | `probe_ok=False` |
| 3 | 측정 무효 — 다시 잰다 | `probe_ok=False` |

출력: `META`(쪽별 트리·실행 전후 HEAD·dirty·시각) · `EXIT` · `base.log` · `after.log` · `base_names.txt` ·
`after_names.txt` · `new_red.txt`.

무효(3): 전수 미실행 · `tree_marker` 없음 · 기준선이 수정 후의 조상이 아님(방향 역전) · 측정 중 트리 HEAD 변경 ·
이름 파일 없음.
