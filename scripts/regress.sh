#!/bin/sh
# bugfix-pipeline R-REGRESS 판정부 — 기준선과 수정 후의 «실패 이름 집합» 차집합.
#
#   regress.sh diff <기준선 이름> <수정 후 이름> <기준선 로그> <수정 후 로그> <새 빨강 출력>
#   regress.sh selftest
#
# 이름 목록: 한 줄에 테스트 id 하나. `#` 머리 줄과 빈 줄은 뺀다. 순서는 상관없다.
#
# 「전수가 돌았다」는 러너마다 문구가 다르다 — 이 파일은 그것을 모른다. 프로파일이 준다:
#   BP_RAN_FULLY  로그에 «있어야» 하는 grep -E 패턴 (필수 — 없으면 측정 무효)
#   BP_NOT_FULLY  로그에 «있으면 안 되는» grep -E 패턴 (선택)
#
# 종료코드: 0 = 새 빨강 0 · 1 = 새 빨강 있음 · 3 = 측정 무효(한쪽이 «안 돌았다»)
# ⇒ 루브릭: assert `exit == 0`. exit 3 은 FAIL 이 아니라 probe_ok=False 다.
#
# 실행부(두 쪽을 «한 명령»·«같은 조건»·«순차»로 돌리기)는 프로파일에 달려 있어 아직 없다.
set -e

here=$(cd "$(dirname "$0")" && pwd)

# 한 줄에 id 하나. `#` 머리와 빈 줄은 뺀다.
_names() {
  grep -v '^#' "$1" | grep -v '^[[:space:]]*$' | sort -u
}

# 로그가 «전수가 돌았다»고 말하나. 아니면 그 쪽 이름 목록은 «못 본» 것이다.
_ran_fully() {
  log=$1
  [ -f "$log" ] || return 1
  # -e: `-` 로 시작하는 패턴이 옵션으로 읽히지 않게. 읽을 수 없는 패턴(exit 2)은 «못 쟀다»다
  grep -qE -e "$BP_RAN_FULLY" "$log" || return 1
  [ -n "$BP_NOT_FULLY" ] || return 0
  # `set` 을 건드리지 않는다 — 부르는 쪽의 set +e 구간을 깨면 스크립트가 조용히 죽는다
  rc=0; grep -qE -e "$BP_NOT_FULLY" "$log" || rc=$?
  [ "$rc" -eq 1 ]
}

# _diff <기준선 이름> <수정 후 이름> <기준선 로그> <수정 후 로그> <새 빨강 출력>
_diff() {
  if [ -z "$BP_RAN_FULLY" ]; then
    echo "측정 무효: BP_RAN_FULLY 가 없다 — 러너의 완료 문구를 프로파일에서 준다" >&2
    return 3
  fi
  for side in "$3" "$4"; do
    if ! _ran_fully "$side"; then
      echo "측정 무효: 전수가 돌지 않았다 — $side" >&2
      return 3
    fi
  done
  for f in "$1" "$2"; do
    if [ ! -f "$f" ]; then
      echo "측정 무효: 이름 목록이 없다 — $f" >&2
      return 3
    fi
  done
  _names "$1" > "$5.base"
  _names "$2" > "$5.after"
  comm -13 "$5.base" "$5.after" > "$5"
  rm -f "$5.base" "$5.after"
  n=$(wc -l < "$5" | tr -d ' ')
  echo "NEW_RED=$n"
  [ "$n" -eq 0 ]
}

case "$1" in
  diff)
    shift
    if [ "$#" -ne 5 ]; then
      echo "사용법: $0 diff <기준선 이름> <수정 후 이름> <기준선 로그> <수정 후 로그> <새 빨강 출력>" >&2
      exit 2
    fi
    set +e
    _diff "$@"
    rc=$?
    set -e
    exit "$rc"
    ;;
  selftest)
    t="$here/.selftest-regress"
    rm -rf "$t"; mkdir -p "$t"
    # selftest 는 자기 패턴을 쓴다 — 호출자 환경이 새어 들지 않게.
    BP_RAN_FULLY='^DONE '
    BP_NOT_FULLY='PARTIAL|DIED'
    printf 'DONE failed 2 passed 10\n' > "$t/ok.log"
    printf 'DONE failed 2 passed 10\nPARTIAL chunk 2 ran nothing\n' > "$t/partial.log"
    printf 'collected 12\n' > "$t/dead.log"
    printf '# 분모\n\ntests/a.py::t1\ntests/b.py::t[라벨 공백]\n' > "$t/base.txt"
    printf '# 다른 머리\ntests/b.py::t[라벨 공백]\ntests/a.py::t1\n' > "$t/same.txt"
    printf 'tests/a.py::t1\n' > "$t/fixed.txt"
    printf 'tests/a.py::t1\ntests/c.py::t9\n' > "$t/newred.txt"

    fail=0
    _expect() {  # _expect <기대 exit> <설명> <인자...>
      want=$1; what=$2; shift 2
      set +e; _diff "$@" "$t/new.out" >/dev/null 2>&1; got=$?; set -e
      if [ "$got" -ne "$want" ]; then
        echo "FAIL: $what — 기대 exit $want, 실제 $got" >&2; fail=1
      fi
    }
    # 축 1: 이름 집합이 같으면(순서·머리·빈 줄만 다르면) 초록
    _expect 0 "같은 집합" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/ok.log"
    # 축 2: 기준선에 없는 이름이 생기면 빨강 — 그리고 «그 이름»을 내놓는다
    _expect 1 "새 빨강" "$t/base.txt" "$t/newred.txt" "$t/ok.log" "$t/ok.log"
    if [ "$(cat "$t/new.out" 2>/dev/null)" != "tests/c.py::t9" ]; then
      echo "FAIL: 새 빨강 이름이 틀렸다 — $(cat "$t/new.out" 2>/dev/null)" >&2; fail=1
    fi
    # 축 3: 기준선에서 사라진 이름(고쳐진 것)은 빨강이 아니다
    _expect 0 "고쳐진 것만" "$t/base.txt" "$t/fixed.txt" "$t/ok.log" "$t/ok.log"
    # 축 4: 어느 쪽이든 «안 돌았으면» 무효(3) — 빈 목록을 «새 빨강 0»으로 읽지 않는다
    _expect 3 "수정 후 청크 미실행" "$t/base.txt" "$t/base.txt" "$t/ok.log" "$t/partial.log"
    _expect 3 "기준선이 요약 전 사망" "$t/base.txt" "$t/base.txt" "$t/dead.log" "$t/ok.log"
    _expect 3 "로그 없음" "$t/base.txt" "$t/base.txt" "$t/ok.log" "$t/nope.log"
    _expect 3 "이름 목록 없음" "$t/base.txt" "$t/nope.txt" "$t/ok.log" "$t/ok.log"
    # 축 5: 완료 문구를 모르면 무효(3) — 추정하지 않는다
    saved=$BP_RAN_FULLY; BP_RAN_FULLY=
    _expect 3 "완료 패턴 미지정" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/ok.log"
    BP_RAN_FULLY=$saved
    # 축 6: `-` 로 시작하는 패턴도 «패턴»이다 — grep 옵션으로 읽혀 검사가 꺼지면 안 된다
    saved=$BP_NOT_FULLY; BP_NOT_FULLY='-*PARTIAL'
    _expect 3 "- 로 시작하는 not_fully" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/partial.log"
    #   걸리지 않으면 통과여야 한다 — 옵션으로 읽혀 exit 2 가 나면 여기서 3 이 된다
    _expect 0 "- 로 시작하는 not_fully 안 걸림" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/ok.log"
    BP_NOT_FULLY=$saved; saved_rf=$BP_RAN_FULLY; BP_RAN_FULLY='-*DONE '
    _expect 0 "- 로 시작하는 ran_fully" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/ok.log"
    BP_RAN_FULLY=$saved_rf
    # 축 7: grep 이 못 읽는 패턴은 «안 걸림»이 아니라 무효다
    BP_NOT_FULLY='('
    _expect 3 "읽을 수 없는 not_fully" "$t/base.txt" "$t/same.txt" "$t/ok.log" "$t/ok.log"
    BP_NOT_FULLY=$saved

    rm -rf "$t"
    [ "$fail" -eq 0 ] || exit 1
    echo "selftest OK — 일곱 축(열두 사례) 전부 통과"
    ;;
  *)
    echo "사용법: $0 diff <기준선 이름> <수정 후 이름> <기준선 로그> <수정 후 로그> <새 빨강 출력> | selftest" >&2
    exit 2
    ;;
esac
