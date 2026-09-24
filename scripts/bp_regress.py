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
import tempfile
import time
import traceback
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


def _preflight(reg, base, after, out):
    """검사를 통과하면 방향을 잰 (기준선 HEAD, 수정 후 HEAD) 를 돌려준다."""
    for tree in (base, after):
        if not tree.is_dir():
            raise _Stop(EXIT_CONFIG, f"설정 오류: 트리가 없다 — {tree}")
    for p in (base, after, out):
        if not _inside(p, reg.allowed_roots):
            raise _Stop(EXIT_CONFIG, f"설정 오류: allowed_roots 밖이다 — {p}")
    base_head, after_head = _head(base), _head(after)
    for tree in (base, after):
        marker = tree / reg.tree_marker
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
    return base_head, after_head


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _run_side(reg, side, tree, out, meta, checked_head, root) -> None:
    names, log = out / f"{side}_names.txt", out / f"{side}.log"
    before = _head(tree)
    if before != checked_head:
        # 방향은 사전 검사 때의 HEAD 로 쟀다 — 그 사이 움직였으면 잰 것과 잴 것이 다르다
        raise _Stop(EXIT_VOID, f"측정 무효: {side} 트리가 사전 검사 뒤 움직였다 — {checked_head} → {before}")
    meta[f"{side}_tree"] = str(tree)
    meta[f"{side}_head_before"] = before
    meta[f"{side}_start"] = _now()
    with open(log, "wb") as f:
        # 쪽 표지를 넘기지 않는다 — 래퍼가 쪽마다 다르게 굴 수 없게
        try:
            subprocess.run(
                [*reg.side_cmd, str(tree), str(names)],
                cwd=str(root), stdout=f, stderr=subprocess.STDOUT,
            )
        except OSError as e:
            raise _Stop(EXIT_CONFIG, f"설정 오류: side_cmd 를 실행할 수 없다 — {e}")
    after = _head(tree)
    _, dirty = _git(tree, "status", "--porcelain")
    meta[f"{side}_head_after"] = after
    meta[f"{side}_end"] = _now()
    meta[f"{side}_dirty"] = "1" if dirty else "0"
    if after != before:
        raise _Stop(EXIT_VOID, f"측정 무효: 측정 중 {side} 트리의 HEAD 가 바뀌었다 — {before} → {after}")


def _judge(reg, out) -> int:
    env = dict(os.environ)
    # 호출자 셸의 값이 새어 들지 않게 둘 다 «명시»한다 — 프로파일에 없으면 빈 값
    env["BP_RAN_FULLY"] = reg.ran_fully
    env["BP_NOT_FULLY"] = reg.not_fully or ""
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
        reg = profile.regress
        if reg is None:
            raise _Stop(
                EXIT_CONFIG,
                "설정 오류: 프로파일에 regress 섹션이 없다 — R-REGRESS 는 테스트 스위트가 있는 프로젝트에서만 잰다",
            )
        base, after = Path(base).resolve(), Path(after).resolve()
        base_head, after_head = _preflight(reg, base, after, out)
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise _Stop(EXIT_CONFIG, f"설정 오류: 출력 디렉토리를 만들 수 없다 — {e}")
        for name in _DIFF_FILES:
            # 지난 실행의 산출물을 «이번 결과»로 읽지 않는다
            (out / name).unlink(missing_ok=True)
        meta["side_cmd"] = " ".join(reg.side_cmd)
        _run_side(reg, "base", base, out, meta, base_head, profile.root)
        _run_side(reg, "after", after, out, meta, after_head, profile.root)  # 곧바로 — 사이에 아무것도 기다리지 않는다
        code = _judge(reg, out)
    except _Stop as stop:
        print(str(stop), file=sys.stderr)
        code = stop.code
    except Exception:
        # 마지막 방어선 — 예상 못 한 예외가 exit 1(«새 빨강», cap 소모)로 새지 않게
        traceback.print_exc()
        print("측정 무효: 예상 못 한 예외", file=sys.stderr)
        code = EXIT_VOID
    finally:
        if out.is_dir():
            (out / "META").write_text("".join(f"{k}={v}\n" for k, v in meta.items()), encoding="utf-8")
            (out / "EXIT").write_text(f"{code}\n", encoding="utf-8")
    return code


def _case_equal(tmp):
    root, base = bp_fixture.make_host(tmp, ["t::a"], ["t::a"])
    return root, base, root


def _case_new_red(tmp):
    root, base = bp_fixture.make_host(tmp, ["t::a"], ["t::a", "t::b"])
    return root, base, root


def _case_fixed_only(tmp):
    root, base = bp_fixture.make_host(tmp, ["t::a", "t::b"], ["t::a"])
    return root, base, root


def _case_reversed(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    return root, root, base


def _case_marker_missing(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    (base / "tests" / "marker").unlink()
    return root, base, root


def _case_partial(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    bp_fixture.set_mode(root, "partial")
    return root, base, root


def _case_no_names(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    bp_fixture.set_mode(root, "nonames")
    return root, base, root


def _case_moved(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    bp_fixture.set_mode(base, "commit")
    return root, base, root


def _case_outside_roots(tmp):
    root, base = bp_fixture.make_host(tmp, [], [], {"regress.allowed_roots": ["/nonexistent-bp-root"]})
    return root, base, root


def _case_bad_profile(tmp):
    root, base = bp_fixture.make_host(tmp, [], [])
    bp_fixture.write_profile(root, {"schema": 3})
    return root, base, root


# (이름, 준비(tmp) -> (호출 루트, 기준선, 수정 후), 기대 exit)
SCENARIOS = [
    ("같은 집합", _case_equal, 0),
    ("새 빨강", _case_new_red, 1),
    ("고쳐진 것만", _case_fixed_only, 0),
    ("방향 역전", _case_reversed, 3),
    ("기준선 표지 없음", _case_marker_missing, 3),
    ("수정 후 전수 미실행", _case_partial, 3),
    ("수정 후 이름 파일 없음", _case_no_names, 3),
    ("기준선 측정 중 커밋", _case_moved, 3),
    ("allowed_roots 밖", _case_outside_roots, 2),
    ("잘못된 프로파일", _case_bad_profile, 2),
]


def _selftest() -> int:
    global bp_fixture
    import bp_fixture

    failures = []
    for name, prepare, want in SCENARIOS:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            root, base, after = prepare(tmp)
            out = tmp / "out"
            # CLI 로 부른다 — cwd 에서 호출 루트를 푸는 경로까지 잰다
            r = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "run", str(base), str(after), str(out)],
                cwd=str(root), capture_output=True, text=True,
            )
            if r.returncode != want:
                failures.append(f"{name}: 기대 exit {want}, 실제 {r.returncode} — {r.stderr.strip()}")
            if name == "같은 집합" and r.returncode == 0:
                for side, tree in (("base", base), ("after", after)):
                    first = (out / f"{side}.log").read_text().splitlines()[0]
                    if first != f"argv: 2|{tree}|{out / f'{side}_names.txt'}":
                        failures.append(f"argv 대칭 깨짐 ({side}): {first}")
    if failures:
        print("selftest FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"selftest OK — 시나리오 {len(SCENARIOS)}개 + argv 대칭")
    return 0


def main(argv) -> int:
    if argv[:1] == ["run"] and len(argv) == 4:
        return run(*argv[1:])
    if argv == ["--selftest"]:
        return _selftest()
    print("사용법: bp_regress.py run <기준선 트리> <수정 후 트리> <출력 디렉토리> | --selftest", file=sys.stderr)
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
