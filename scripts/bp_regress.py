"""bugfix-pipeline R-REGRESS 실행부 — 기준선·수정 후를 «한 명령·같은 래퍼·순차»로 잰다.

  python3 scripts/bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리>
  python3 scripts/bp_regress.py --selftest

종료코드: 0 새 빨강 0 · 1 새 빨강 있음 · 2 설정 오류(고치고 다시) · 3 측정 무효(다시 잰다)
판정은 regress.sh diff 가 한다 — 판정 로직은 한 곳에만 둔다.
설계: docs/superpowers/specs/2026-09-24-profile-v1-design.md §5·§6
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bp_profile  # noqa: E402

EXIT_CONFIG = 2
EXIT_VOID = 3
_DIFF_FILES = ("base_names.txt", "after_names.txt", "base.log", "after.log", "new_red.txt")


class _Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _git(tree, *args):
    r = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _head(tree) -> str:
    rc, out = _git(tree, "rev-parse", "HEAD")
    if rc:
        raise _Stop(EXIT_CONFIG, f"설정 오류: git 트리가 아니다 — {tree}")
    return out


def _inside(path, roots) -> bool:
    return not roots or any(path == r or r in path.parents for r in roots)


def _preflight(profile, base, after, out) -> None:
    for tree in (base, after):
        if not tree.is_dir():
            raise _Stop(EXIT_CONFIG, f"설정 오류: 트리가 없다 — {tree}")
    for p in (base, after, out):
        if not _inside(p, profile.allowed_roots):
            raise _Stop(EXIT_CONFIG, f"설정 오류: allowed_roots 밖이다 — {p}")
    base_head, after_head = _head(base), _head(after)
    for tree in (base, after):
        marker = tree / profile.tree_marker
        if not marker.exists():
            # 빈 마운트 지점·엉뚱한 트리 — 러너 부재가 «빨강»처럼 읽히는 것을 막는다
            raise _Stop(EXIT_VOID, f"측정 무효: tree_marker 가 없다 — {marker}")
    rc, _ = _git(after, "merge-base", "--is-ancestor", base_head, after_head)
    if rc == 1:
        raise _Stop(
            EXIT_VOID,
            f"측정 무효: 방향이 거꾸로다 — 기준선 {base_head} 가 수정 후 {after_head} 의 조상이 아니다",
        )
    if rc:
        raise _Stop(EXIT_VOID, f"측정 무효: 조상 관계를 못 쟀다 — {base_head} · {after_head}")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _run_side(profile, side, tree, out, meta) -> None:
    names, log = out / f"{side}_names.txt", out / f"{side}.log"
    before = _head(tree)
    meta[f"{side}_tree"] = str(tree)
    meta[f"{side}_head_before"] = before
    meta[f"{side}_start"] = _now()
    with open(log, "wb") as f:
        # 쪽 표지를 넘기지 않는다 — 래퍼가 쪽마다 다르게 굴 수 없게
        subprocess.run(
            [*profile.side_cmd, str(tree), str(names)],
            cwd=str(profile.root), stdout=f, stderr=subprocess.STDOUT,
        )
    after = _head(tree)
    _, dirty = _git(tree, "status", "--porcelain")
    meta[f"{side}_head_after"] = after
    meta[f"{side}_end"] = _now()
    meta[f"{side}_dirty"] = "1" if dirty else "0"
    if after != before:
        raise _Stop(EXIT_VOID, f"측정 무효: 측정 중 {side} 트리의 HEAD 가 바뀌었다 — {before} → {after}")


def _judge(profile, out) -> int:
    env = dict(os.environ)
    # 호출자 셸의 값이 새어 들지 않게 둘 다 «명시»한다 — 프로파일에 없으면 빈 값
    env["BP_RAN_FULLY"] = profile.ran_fully
    env["BP_NOT_FULLY"] = profile.not_fully or ""
    r = subprocess.run(
        ["sh", str(HERE / "regress.sh"), "diff", *(str(out / n) for n in _DIFF_FILES)], env=env
    )
    return r.returncode


def run(base, after, out, root=None) -> int:
    out = Path(out).resolve()
    meta = {}
    code = EXIT_VOID
    try:
        try:
            root = Path(root) if root else bp_profile.toplevel(Path.cwd())
            profile = bp_profile.load(root)
        except bp_profile.ProfileError as e:
            raise _Stop(EXIT_CONFIG, "설정 오류: 프로파일\n" + "\n".join(f"  - {p}" for p in e.problems))
        base, after = Path(base).resolve(), Path(after).resolve()
        _preflight(profile, base, after, out)
        out.mkdir(parents=True, exist_ok=True)
        for name in _DIFF_FILES:
            # 지난 실행의 산출물을 «이번 결과»로 읽지 않는다
            (out / name).unlink(missing_ok=True)
        meta["side_cmd"] = " ".join(profile.side_cmd)
        _run_side(profile, "base", base, out, meta)
        _run_side(profile, "after", after, out, meta)  # 곧바로 — 사이에 아무것도 기다리지 않는다
        code = _judge(profile, out)
    except _Stop as stop:
        print(str(stop), file=sys.stderr)
        code = stop.code
    finally:
        if out.is_dir():
            (out / "META").write_text("".join(f"{k}={v}\n" for k, v in meta.items()), encoding="utf-8")
            (out / "EXIT").write_text(f"{code}\n", encoding="utf-8")
    return code


def main(argv) -> int:
    if argv[:1] == ["run"] and len(argv) == 4:
        return run(*argv[1:])
    print("사용법: bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리> | --selftest", file=sys.stderr)
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
