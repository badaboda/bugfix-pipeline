# 프로파일 — 호스트 프로젝트 설정

bugfix-pipeline 의 `R-REGRESS` 실행부는 호스트 프로젝트에 대해 추정하지 않는다. 호스트가
`.claude/bugfix-pipeline.json` 한 파일과 래퍼 스크립트 하나를 커밋한다. 설계 근거는
[`superpowers/specs/2026-09-24-profile-v1-design.md`](superpowers/specs/2026-09-24-profile-v1-design.md).

## 파일

```json
{
  "schema": 1,
  "regress": {
    "side_cmd": ["scripts/bp_side.sh"],
    "ran_fully": "^=+ .*[0-9]+ (passed|failed)",
    "not_fully": "Interrupted|INTERNALERROR",
    "tree_marker": "tests",
    "allowed_roots": ["~"]
  }
}
```

| 필드 | 필수 | 기준 | 뜻 |
|---|---|---|---|
| `schema` | ✔ | | 정수 `1` |
| `side_cmd` | ✔ | 호출 루트 | 래퍼 argv. 첫 요소에 `/` 가 있으면 호출 루트 기준 파일, 없으면 PATH 명령 |
| `ran_fully` | ✔ | | `grep -E` — 로그에 있어야 전수가 돈 것 |
| `not_fully` | | | `grep -E` — 로그에 있으면 전수가 안 돈 것 |
| `tree_marker` | ✔ | 측정 트리 | 각 트리에 있어야 하는 경로 — 빈 마운트·엉뚱한 트리를 막는다 |
| `allowed_roots` | | 절대 (`~` 허용) | 두 트리와 출력이 이 아래여야 한다 (예: 홈만 공유하는 VM) |

호출 루트 = `bp_regress.py run` 을 부른 곳의 git 최상위. 모르는 키, `schema: true`,
빈 줄에도 걸리는 패턴, 개행이 든 패턴, 빈 `allowed_roots` 는 거부한다.

```sh
python3 <플러그인>/scripts/bp_profile.py check   # exit 0 OK · 2 문제 목록
```

## 래퍼 계약

`<side_cmd…> <트리 절대경로> <이름 출력 절대경로>` — cwd 는 호출 루트, 두 쪽이 같은 래퍼.

1. 어느 쪽인지 알려 주지 않는다. 쪽마다 다르게 굴 수 없어야 대칭이다.
2. stdout·stderr 가 곧 로그다. `ran_fully`·`not_fully` 가 여기에 걸린다.
3. 이름 출력: 한 줄에 실패 id 하나. `#` 줄·빈 줄 무시, 정렬 불필요. 안 쓰면 측정 무효.
4. 종료코드는 판정에 쓰지 않는다.
5. **주어진 트리를 잰다.** 떠 있는 스택에 exec 하면 사본이 아니라 원본을 잰다.

테스트 명령·수집 루트·실행 환경(컨테이너·마운트)·환경 변수·이름 추출은 전부 래퍼 몫이다.

### 예시 — pytest

```sh
#!/bin/sh
# bp_side.sh <트리> <이름 출력> — 주어진 트리에서 전체 테스트를 돌리고 실패·오류 id 를 쓴다.
# stdout 이 곧 로그다 — 프로파일의 ran_fully 가 여기서 요약 줄을 찾는다.
tree=$1; names=$2
raw="$names.raw"
( cd "$tree" && ${BP_PYTEST:-python3 -m pytest} tests -rfE -p no:cacheprovider ) > "$raw" 2>&1
status=$?
cat "$raw"
# FAILED 만 세면 fixture·setup 오류(ERROR)가 빠진다 — 그것도 «새 빨강»이다
grep -E '^(FAILED|ERROR) ' "$raw" | sed -E 's/^(FAILED|ERROR) //; s/ - .*//' > "$names"
rm -f "$raw"
exit $status
```

실측(2026-09-24, pytest 8.4):

- 실패 1·통과 1 트리 → 이름 파일 `tests/test_x.py::test_broken` 한 줄, 요약 줄이 `ran_fully` 에 걸림
- 실패 1·통과 1·fixture 오류 1 트리 → 이름 파일에 실패와 오류 두 줄. `-rf`·`^FAILED` 만 쓰면 오류가
  빠지는데 요약 줄(`1 failed, 1 passed, 1 error`)은 여전히 `ran_fully` 에 걸려 — 고친 수정이 fixture 를
  깨도 초록이 된다
- 수집 오류 트리 → `not_fully` 가 걸리고 `ran_fully` 는 안 걸림

pytest id 에 ` - ` 가 들어 있으면 이 `sed` 가 잘라 낸다 — 그런 id 를 쓰는 프로젝트는 추출을 바꾼다.

## 실행

```sh
python3 <플러그인>/scripts/bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리>
```

| exit | 뜻 | 진리표 |
|---|---|---|
| 0 | 새 빨강 0 | `regress=True` |
| 1 | 새 빨강 있음 — `new_red.txt` | `regress=False` |
| 2 | 설정 오류 — 고치고 다시 | `probe_ok=False` |
| 3 | 측정 무효 — 다시 잰다 | `probe_ok=False` |

출력: `META`(쪽별 트리·실행 전후 HEAD·dirty·시각) · `EXIT` · `base.log` · `after.log` ·
`base_names.txt` · `after_names.txt` · `new_red.txt`.

무효(3)가 되는 경우: 전수 미실행 · `tree_marker` 없음 · 기준선이 수정 후의 조상이 아님(방향 역전) ·
측정 중 트리 HEAD 변경 · 이름 파일 없음.
