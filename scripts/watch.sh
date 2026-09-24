#!/bin/sh
# bugfix-pipeline 리더 감시 — 팀원이 «조용히 멈춘» 것을 리더가 알아챈다.
#
#   watch.sh <workspace> <완료 파일 이름> [정체 분]
#
# 리더가 Monitor 로 건다. stdout 한 줄이 곧 리더를 깨우는 이벤트다.
#   DONE   완료 파일이 생겼다 → 감시 종료
#   STALL  workspace 의 어떤 파일도 N분(기본 10) 동안 안 바뀌었다 → 리더가 팀원에게 메시지를 보낸다
#   ALIVE  STALL 뒤에 다시 움직였다
#
# 🔴 왜 리더 쪽인가 (2026-09-23 실측): 게이트는 기준선을 백그라운드로 돌리고 완료 알림을
# 세 겹(백그라운드 완료 · until 루프 · Monitor)으로 걸고 턴을 끝냈다 — 기다리는 법은 옳았다.
# 그런데 11:47 에 울렸어야 할 알림 셋이 18:30 에 «한꺼번에» 도착했다. 리더가 메시지를 보낸
# 바로 그 순간이다. 팀원 쪽 알림이 팀원을 못 깨웠고, 확인된 유일한 깨우는 수단이 리더의
# 메시지였다. 그래서 팀원에게 「잘 기다려라」를 더 적는 것은 처방이 아니다.
# 🔴 「조용함」은 「진행 중」이 아니다 — 이 스크립트는 그 둘을 가르려고 있다.
set -e

ws=$1; done_file=$2; mins=${3:-10}
if [ -z "$ws" ] || [ -z "$done_file" ]; then
  echo "사용법: $0 <workspace> <완료 파일 이름> [정체 분]" >&2; exit 2
fi
if [ ! -d "$ws" ]; then
  # 없는 경로를 감시하면 영원히 STALL 도 DONE 도 아닌 침묵이 된다.
  echo "workspace 가 없다: $ws" >&2; exit 2
fi

stalled=0
while true; do
  if [ -f "$ws/$done_file" ]; then echo "DONE $done_file"; exit 0; fi
  # 최근 N분 안에 바뀐 파일이 하나라도 있나
  if [ -n "$(find "$ws" -type f -mmin -"$mins" -print -quit)" ]; then
    if [ "$stalled" -eq 1 ]; then echo "ALIVE $(date '+%H:%M')"; stalled=0; fi
  elif [ "$stalled" -eq 0 ]; then
    echo "STALL ${mins}분 동안 $ws 변화 없음 · $done_file 없음 ($(date '+%H:%M'))"
    stalled=1
  fi
  sleep 60
done
