# 프로파일 v1 — R-REGRESS 실행부 설계

- 날짜: 2026-09-24
- 상태: 설계 승인됨 (구현 전)
- 범위: `R-REGRESS` 실행부가 실제로 부르는 값만. 다른 소비자는 생길 때 `schema` 를 올려 추가한다.

## 1. 목적

`R-REGRESS` 는 기준선 트리와 수정 후 트리에서 전체 테스트를 돌리고, 실패 이름 집합의 차집합을 판정한다. 판정부(`scripts/regress.sh diff`)는 이미 있다. 이 스펙은 **두 쪽을 실행하는 부분**과, 그 부분이 호스트 프로젝트에서 받아야 하는 값(프로파일)을 정한다.

실전에서 확인된 실패 모양:

- 두 실행을 따로 시작하면 그 사이가 이음매가 된다. 실측: 두 실행 사이에 6시간 43분이 비었다.
- 두 쪽이 다른 조건으로 돌면(한쪽은 일회성 컨테이너, 한쪽은 떠 있는 스택에 exec) 기존 불안정 테스트가 «새 빨강» 처럼 보인다.
- 요약 전에 죽은 실행의 빈 이름 목록이 「새 빨강 0」으로 읽힌다.
- 없는 경로를 bind 하면 빈 디렉토리가 생겨 러너 부재가 빨강처럼 보인다.
- 사람이 두 결과 파일의 방향을 뒤바꿔 읽고 재실행을 지시했다.

## 2. 결정 요약

| 결정 | 선택 | 이유 |
|---|---|---|
| v1 범위 | R-REGRESS 만 | 부르는 코드가 없는 필드는 주석과 같다 |
| 값의 출처 | 사람이 쓴 파일 + 검사기 | 감지가 틀리면 분모가 조용히 틀린다. 값이 모든 실행에서 같고 리뷰된다 |
| 실행 모델 | 호스트 래퍼 계약 (`side_cmd`) | Docker 를 가정하지 않는다. 양쪽이 같은 래퍼라 대칭이 구조상 보장된다 |
| 형식 | JSON | 호스트 python3 가 3.9 라 `tomllib` 없음, YAML 은 표준 밖 |

## 3. 파일 위치와 기준 루트

- 위치: 호스트 레포의 `.claude/bugfix-pipeline.json`. 커밋 대상이다.
  `.bugfix-pipeline/` 은 작업 산출물(무시 대상) 이름이라 쓰지 않는다.
- **호출 루트**: `bp_regress.py run` 을 부른 곳의 `git rev-parse --show-toplevel`.
- 필드마다 기준을 명시한다.

| 기준 | 필드 | 이유 |
|---|---|---|
| 호출 루트 | 프로파일 파일, `side_cmd` | 두 쪽에 **같은 래퍼 하나**를 쓴다. 쪽마다 자기 트리의 래퍼를 쓰면 다른 래퍼로 잴 수 있다 |
| 측정 트리 | `tree_marker` | 각 트리에 러너가 실제로 있는지를 그 트리에서 묻는다 |
| 절대 경로 | `allowed_roots` | `~` 만 펼친다. 상대 경로는 거부 |

모노레포는 git 최상위에 프로파일 하나를 두고 `tree_marker` 를 그 기준 상대 경로로 적는다. 워크트리에서는 그 워크트리 최상위가 호출 루트다.

## 4. 스키마

```json
{
  "schema": 1,
  "regress": {
    "side_cmd": ["scripts/bp_side.sh"],
    "ran_fully": "^=+ .*[0-9]+ (passed|failed)",
    "not_fully": "INTERRUPTED|collection error",
    "tree_marker": "tests/conftest.py",
    "allowed_roots": ["~"]
  }
}
```

| 필드 | 필수 | 뜻 |
|---|---|---|
| `schema` | ✔ | 정수 `1`. 다른 값은 거부 |
| `regress.side_cmd` | ✔ | 비어 있지 않은 문자열 배열(argv). 첫 요소에 `/` 가 있으면 호출 루트 기준 파일, 없으면 PATH 명령 |
| `regress.ran_fully` | ✔ | `grep -E` 패턴. 로그에 **있어야** 전수가 돈 것이다 |
| `regress.not_fully` | | `grep -E` 패턴. 로그에 **있으면** 전수가 안 돈 것이다 |
| `regress.tree_marker` | ✔ | 측정 트리 기준 상대 경로. 없으면 그 쪽 측정 무효 |
| `regress.allowed_roots` | | 절대 경로 배열. 두 트리와 출력 디렉토리가 이 가운데 하나 아래여야 한다. 없으면 제약 없음 |

**모르는 키는 거부한다** (최상위·`regress` 둘 다). 선택 필드의 오타가 조용히 무시되면 그 검사가 꺼진 채 초록이 난다.

## 5. `side_cmd` 계약

호출: `<side_cmd…> <트리 절대경로> <이름 출력 절대경로>`

1. 작업 디렉토리는 두 쪽 모두 호출 루트다.
2. **어느 쪽인지 알리지 않는다.** base/after 표지를 넘기면 래퍼가 쪽마다 다르게 행동할 수 있다.
3. 래퍼의 stdout·stderr 는 플러그인이 `<출력>/<쪽>.log` 로 받는다. `ran_fully`·`not_fully` 는 이 로그에 적용한다.
4. 이름 파일: 한 줄에 실패 테스트 id 하나. `#` 로 시작하는 줄과 빈 줄은 무시하고, 정렬은 필요 없다. 파일이 없으면 측정 무효.
5. 래퍼의 종료코드는 판정에 쓰지 않는다. 실패가 있으면 1 을 내는 러너가 정상이다.
6. 래퍼는 **주어진 트리를 잰다.** 떠 있는 스택에 exec 하면 사본이 아니라 원본을 잰다. 플러그인은 이것을 완전히 검증할 수 없다 — 아래 `META` 로 사후 추적만 가능하게 한다.

래퍼가 맡는 것: 테스트 명령과 수집 루트, 실행 환경 조립(컨테이너·마운트·볼륨), 환경 변수 규칙, 러너 출력에서 실패 이름을 뽑는 규칙. 두 쪽이 같은 래퍼라 이 모든 것이 대칭이다.

## 6. `bp_regress.py run` 흐름

`python3 scripts/bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리>`

| 순서 | 할 일 | 실패 시 |
|---|---|---|
| 1 | 프로파일 로드·검사 (§7) | exit 2 |
| 2 | 두 트리 존재·git 트리 여부. 두 트리와 출력이 `allowed_roots` 아래인지 (realpath 기준) | exit 2 |
| 3 | 두 트리에 `tree_marker` 존재 | exit 3 |
| 4 | 방향: `git merge-base --is-ancestor <base_head> <after_head>` | exit 3 |
| 5 | 기준선 실행 → 곧바로 수정 후 실행. 순차, 사이 대기 없음 | — |
| 6 | 각 쪽 실행 전후 HEAD 가 같은지 (측정 중 커밋 감지) | exit 3 |
| 7 | `BP_RAN_FULLY`·`BP_NOT_FULLY` 를 넣어 `regress.sh diff` 호출. 결과를 `<출력>/EXIT` 에 쓰고 그대로 종료 | 0/1/3 |

두 HEAD 가 같은 것은 허용한다(수정이 아직 커밋 안 된 워크트리). 이때 `after_dirty=1` 이 남는다.

`<출력>/META` (한 줄에 `키=값`):

```
side_cmd=…
base_tree=…  base_head_before=…  base_head_after=…  base_dirty=0|1  base_start=…  base_end=…
after_tree=… after_head_before=… after_head_after=… after_dirty=0|1 after_start=… after_end=…
```

출력 디렉토리 구성: `META` · `base.log` · `after.log` · `base_names.txt` · `after_names.txt` · `new_red.txt` · `EXIT`.

### 종료코드

| exit | 뜻 | 진리표 입력 |
|---|---|---|
| 0 | 새 빨강 0 | `regress=True` |
| 1 | 새 빨강 있음 (`new_red.txt`) | `regress=False` |
| 2 | 사용법·프로파일·경로 제약 오류 — 측정 전에 고칠 설정 | `probe_ok=False` (ENV) |
| 3 | 측정 무효 — 전수 미실행·표지 없음·방향 역전·측정 중 변경·이름 파일 없음 | `probe_ok=False` (ENV) |

2 와 3 을 가르는 것은 대응이 달라서다: 2 는 설정을 고치고, 3 은 다시 잰다. 진리표에서는 둘 다 ENV 라 cap 을 태우지 않는다.

## 7. 검사기 `scripts/bp_profile.py`

의존 0, python 3.9 호환.

- 라이브러리: `load(root) -> Profile`. 문제는 **전부 모아서** `ProfileError` 로 낸다.
- CLI: `python3 scripts/bp_profile.py check [root]` → exit 0 + 요약 / exit 2 + 문제 목록. `--selftest`.
- 검사:
  - 파일 존재, JSON 파싱
  - `schema == 1`, 모르는 키 없음
  - 필수 필드 존재, 타입
  - `side_cmd[0]`: `/` 포함이면 호출 루트 기준 파일이 있고 실행 가능, 아니면 `shutil.which` 로 찾아짐
  - 패턴: **실제 엔진으로** 검사한다 — `grep -E -- <패턴> /dev/null` 이 exit 2 면 거부. 파이썬 `re` 와 ERE 는 문법이 달라 `re` 검사는 거짓 통과를 낸다
  - `tree_marker`: 상대 경로이고 호출 루트에 존재
  - `allowed_roots`: `~` 펼친 뒤 절대 경로

## 8. 테스트

| 층 | 대상 | 도구 |
|---|---|---|
| 개발 | `tests/test_bp_profile.py` — 거부 경로마다 하나 + 정상 하나 | pytest (`uvx`) |
| 개발 | `tests/test_bp_regress.py` — 임시 git 레포 + 가짜 `side_cmd`. exit 0 · 1 · 3(방향 역전·표지 없음·`not_fully`·측정 중 커밋·이름 파일 없음) · 2(경로 제약·잘못된 프로파일). 래퍼가 받는 argv 가 정확히 `[트리, 이름 출력]` 인지 | pytest |
| 설치처 | `bp_profile.py --selftest` · `bp_regress.py --selftest` — 같은 픽스처를 의존 0 으로 (git·sh 는 원래 필요) | python3 |
| 양성 대조 | 검사마다 사보타주해 빨개지는지 — 예: 방향 검증을 끄면 역전 사례가 빨개져야 한다 | 수동 |

## 9. 문서

`docs/profile.md` — 스키마, 래퍼 계약, 특정 프로젝트가 드러나지 않는 래퍼 예시(pytest 기준).

## 10. 범위 밖

- `SKILL.md` 연결
- 조사자 에이전트의 탈-프로젝트화
- 프로파일 초안 자동 생성
- 버그별 표적 보강 — 결함의 기존 테스트가 공통 수집 루트 밖에 있을 때. 버그마다 달라지는 값이라 프로파일이 아니라 루브릭의 몫이다. **알려진 공백.**
