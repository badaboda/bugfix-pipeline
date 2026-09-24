#!/bin/sh
# bugfix-pipeline 훅 설치/제거. 작업 가지 한정 — P6 에서 제거한다.
#
# 🔴 설치했다는 보고는 증거가 아니다. 설치 후 반드시 verify 를 돌린다.
set -e

here=$(cd "$(dirname "$0")" && pwd)
# 🔴 워크트리의 `.git` 은 정규 파일이라 `$repo/.git/hooks` 는 ENOTDIR 로 깨진다.
# `--git-path` 는 워크트리에서도 «공용» hooks 디렉토리로 정확히 해소된다 (실측 확인).
hooks_dir=$(git rev-parse --git-path hooks)
target="$hooks_dir/commit-msg"

# verify 가 쓰는 임시 메시지 파일. mktemp 은 복합 셸에서 권한 프롬프트를 유발하므로 고정 경로를 쓴다.
tmp="$(git rev-parse --git-path bugfix-pipeline-verify-msg)"

# 🔴 `git hook run <h>` 은 훅이 «없을 때도» exit 1 ("cannot find a hook")이다.
# 그래서 종료코드만 보면 「훅이 거부했다」와 「훅이 없다」가 같은 얼굴이다 — 실측으로 확인했다.
# verify 는 둘을 반드시 가른다: ① 설치·실행권한을 선행 조건으로 확인하고
# ② 거부가 «우리 훅의» 거부인지 표지 문구로 확인한다. 안 그러면 훅이 없는데 초록이 난다.
marker='commit-msg 거부'

_run_hook() {
  # stdout+stderr 를 합쳐 파일로 받고 종료코드를 반환한다.
  git hook run commit-msg -- "$tmp" >"$tmp.out" 2>&1
}

case "$1" in
  install)
    mkdir -p "$hooks_dir"
    if [ -e "$target" ]; then
      echo "이미 commit-msg 훅이 있다: $target" >&2
      echo "덮어쓰지 않는다 — 남의 훅일 수 있다. 수동으로 확인하라." >&2
      exit 1
    fi
    branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
    if [ -z "$branch" ]; then
      echo "detached HEAD 에서는 설치하지 않는다 — 가지 범위를 못 정한다." >&2
      exit 1
    fi
    # 🔴 워크트리들이 hooks 디렉토리를 공유한다. 가지를 훅에 박아 «이 가지에서만» 발화시킨다.
    # 안 그러면 남의 워크트리 커밋까지 막는다 (실측으로 겪었다).
    sed "s|@@BUGFIX_PIPELINE_BRANCH@@|$branch|" "$here/commit-msg" > "$target"
    chmod +x "$target"
    echo "설치: $target (가지 $branch 한정)"
    ;;
  uninstall)
    if [ ! -e "$target" ]; then
      echo "없다: $target"
      exit 0
    fi
    if ! grep -q 'bugfix-pipeline' "$target"; then
      echo "우리 훅이 아니다 — 지우지 않는다: $target" >&2
      exit 1
    fi
    rm "$target"
    echo "제거: $target"
    ;;
  verify)
    # ── 선행 조건: 훅이 «있고 실행 가능»한가 ────────────────────────────
    # 실행 권한이 없으면 git 은 hint 만 내고 조용히 무시한다.
    if [ ! -f "$target" ]; then
      echo "FAIL: 훅이 설치돼 있지 않다 — $target" >&2
      exit 1
    fi
    if [ ! -x "$target" ]; then
      echo "FAIL: 훅에 실행 권한이 없다 — git 이 조용히 무시한다: $target" >&2
      exit 1
    fi

    # ── 선행 조건 ③: 이 훅이 «이 가지» 것인가 ──────────────────────────
    if ! grep -q "_bp_branch=\"$(git symbolic-ref --short HEAD 2>/dev/null)\"" "$target"; then
      echo "FAIL: 설치된 훅이 다른 가지 것이다 — 이 가지에서는 발화하지 않는다" >&2
      exit 1
    fi

    # ── 축 1: RED 없는 fix 는 «우리 훅이» 거부해야 한다 ─────────────────
    printf 'fix(x): 본문에 RED 가 없다\n' > "$tmp"
    if _run_hook; then
      echo "FAIL: RED 없는 fix 가 통과했다 — 훅이 안 불린다" >&2
      rm -f "$tmp" "$tmp.out"; exit 1
    fi
    if ! grep -q "$marker" "$tmp.out"; then
      echo "FAIL: 거부됐지만 «우리 훅의» 거부가 아니다 — 표지 문구가 없다" >&2
      echo "  실제 출력: $(cat "$tmp.out")" >&2
      rm -f "$tmp" "$tmp.out"; exit 1
    fi

    # ── 축 2: RED 있는 fix 는 통과해야 한다 ────────────────────────────
    printf 'fix(x): RED 가 있다\n\nRED: 3c8cb05\n' > "$tmp"
    if ! _run_hook; then
      echo "FAIL: RED 있는 fix 가 거부됐다 — 훅이 과잉 차단한다" >&2
      echo "  실제 출력: $(cat "$tmp.out")" >&2
      rm -f "$tmp" "$tmp.out"; exit 1
    fi

    # ── 축 3: feat/fix 가 아닌 타입은 건드리지 않는다 ───────────────────
    printf 'docs(x): feat/fix 가 아니다\n' > "$tmp"
    if ! _run_hook; then
      echo "FAIL: docs 커밋이 거부됐다 — 범위가 너무 넓다" >&2
      echo "  실제 출력: $(cat "$tmp.out")" >&2
      rm -f "$tmp" "$tmp.out"; exit 1
    fi

    rm -f "$tmp" "$tmp.out"
    echo "verify OK — 선행 조건 + 세 축 전부 통과"
    ;;
  *)
    echo "사용법: $0 install|uninstall|verify" >&2
    exit 2
    ;;
esac
