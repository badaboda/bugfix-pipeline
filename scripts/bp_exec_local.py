"""내장 exec 기본값 — 프로파일에 exec 가 없을 때 «트리에서 명령 하나»를 그대로 돈다.

  python3 scripts/bp_exec_local.py <트리> -- <명령…>

명령의 종료코드를 그대로 돌려준다. 명령을 «돌리지 못하면»(트리 없음·명령 없음) 125 —
exec 계약에서 125 는 「probe 가 돌지 못했다」(ENV)다. 사본에는 git 이 추적하지 않는 파일이
없다는 것을 이 기본값은 해결하지 않는다 — 그런 프로젝트는 프로파일에 exec 를 둔다.
"""
import subprocess
import sys
from pathlib import Path

ENV_FAILED = 125


def main(argv) -> int:
    if len(argv) < 3 or argv[1] != "--":
        print("사용법: bp_exec_local.py <트리> -- <명령…>", file=sys.stderr)
        return ENV_FAILED
    tree = Path(argv[0])
    if not tree.is_dir():
        print(f"bp_exec_local: 트리가 없다 — {tree}", file=sys.stderr)
        return ENV_FAILED
    try:
        return subprocess.run(argv[2:], cwd=str(tree)).returncode
    except OSError as e:
        print(f"bp_exec_local: 명령을 돌리지 못했다 — {e}", file=sys.stderr)
        return ENV_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
