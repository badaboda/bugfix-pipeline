"""계약 린트 — SKILL.md · 에이전트 문서가 bp_gate 코드와 어긋나면 빨개진다(스펙 §13)."""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import bp_gate  # noqa: E402

SKILL = REPO / "skills" / "bugfix-pipeline" / "SKILL.md"
AGENTS = ("bug-root-cause-investigator", "bug-red-writer", "bug-green-engineer",
          "bug-cta-sweeper", "bug-sweep-gate", "bug-light-fixer")
FORMAL_AGENTS = AGENTS[:5]
GATE_FILES = {bp_gate.LEDGER, bp_gate.REPRO_MD, bp_gate.REPRO_SH, bp_gate.ROOT_CAUSE, bp_gate.RUBRIC,
              bp_gate.LIGHT_CAUSE, bp_gate.LIGHT_REPORT, bp_gate.PR_BODY}
AGENT_OUTPUTS = {"investigation.md", "sweep.json", "sweep.md", "gate_round<N>.md", "control/*.diff",
                 "verdict_<n>.json", ".claude/bugfix-pipeline.json", "new_red.txt"}
# 플러그인에 실제로 있는 파일 이름(스크립트 · 훅 · 문서) — 없는 파일(예: rubric.yaml)을 가리키면 stale 문서다
PLUGIN_FILES = {p.name for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts}
LABELS = (bp_gate.LABEL_NO_DETERMINISM, bp_gate.LABEL_NO_REGRESS, bp_gate.LABEL_NO_BASELINE_REPRO)
COUPLING = re.compile(r"슬롯|\bslot\b|docker exec|webapp-testing|nginx|rubric\.yaml|\bqueue\b", re.I)
_FILE_TOKEN = re.compile(r"`([^`\s]+\.(?:json|md|sh|diff|ya?ml|txt|py))`")
_GATE_CALL = re.compile(r"bp_gate\.py\s+([a-z][a-z-]*)")


def _doc(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name}: frontmatter 가 없다"
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, text


def _all_docs():
    return [SKILL] + [REPO / "agents" / f"{a}.md" for a in AGENTS]


def _text(path):
    return path.read_text(encoding="utf-8")


def test_every_agent_exists_with_matching_frontmatter():
    found = sorted(p.stem for p in (REPO / "agents").glob("*.md"))
    assert found == sorted(AGENTS)
    for a in AGENTS:
        meta, _ = _doc(REPO / "agents" / f"{a}.md")
        assert meta.get("name") == a
        assert meta.get("model") in ("opus", "sonnet", "haiku", "inherit")
        assert meta.get("description")


def test_skill_frontmatter_names_the_plugin():
    meta, _ = _doc(SKILL)
    assert meta.get("name") == "bugfix-pipeline" and meta.get("description")


@pytest.mark.parametrize("path", _all_docs(), ids=lambda p: p.stem)
def test_description_triggers_are_bilingual(path):
    desc = _doc(path)[0]["description"]
    assert re.search(r"«[^»]*[가-힣][^»]*»", desc), "한국어 트리거(«…»)가 없다"
    assert re.search(r"«[a-z]+( [a-z]+)+»", desc), "영어 트리거(«두 단어 이상»)가 없다"


def test_docs_only_call_real_gate_commands():
    for path in _all_docs():
        for cmd in _GATE_CALL.findall(_text(path)):
            assert cmd in bp_gate.COMMANDS, f"{path.name}: 없는 게이트 명령 {cmd}"


def test_skill_covers_every_gate_command():
    called = set(_GATE_CALL.findall(_text(SKILL)))
    assert set(bp_gate.COMMANDS) - called == set()


def test_docs_name_only_known_files():
    for path in _all_docs():
        for name in _FILE_TOKEN.findall(_text(path)):
            known = name in GATE_FILES | AGENT_OUTPUTS or name.split("/")[-1] in PLUGIN_FILES | GATE_FILES
            assert known, f"{path.name}: 모르는 파일명 {name}"


def test_skill_names_every_label_and_gate_file():
    text = _text(SKILL)
    for s in (*LABELS, bp_gate.LEDGER, bp_gate.REPRO_MD, bp_gate.REPRO_SH, bp_gate.PR_BODY, bp_gate.LIGHT_REPORT):
        assert s in text, f"SKILL.md 에 {s} 가 없다"


def test_skill_dispatches_every_agent_by_namespaced_name():
    text = _text(SKILL)
    for a in AGENTS:
        assert f"bugfix-pipeline:{a}" in text


def test_agents_share_one_assignment_contract():
    for a in AGENTS:
        text = _text(REPO / "agents" / f"{a}.md")
        for key in ("workspace", "tree") + (("cause_id",) if a in FORMAL_AGENTS else ()):
            assert f"`{key}`" in text, f"{a}: 배정 계약 키 {key} 가 없다"


def test_producers_name_their_outputs():
    need = {"bug-root-cause-investigator": (bp_gate.ROOT_CAUSE, bp_gate.RUBRIC, "investigation.md"),
            "bug-light-fixer": (bp_gate.LIGHT_CAUSE,),
            "bug-cta-sweeper": ("sweep.json", "sweep.md"),
            "bug-sweep-gate": ("gate_round<N>.md",)}
    for a, files in need.items():
        text = _text(REPO / "agents" / f"{a}.md")
        for f in files:
            assert f"`{f}`" in text, f"{a}: 산출물 {f} 가 없다"


def test_no_source_project_coupling():
    for path in _all_docs():
        hit = COUPLING.search(_text(path))
        assert not hit, f"{path.name}: 원천 결합어 {hit.group(0)!r}"


def test_lint_reads_something():
    # 0 은 질문이다 — 정규식이 아무것도 못 잡으면 위 검사들이 공허하게 초록이 된다
    skill = _text(SKILL)
    assert len(_GATE_CALL.findall(skill)) >= len(bp_gate.COMMANDS)
    assert len(_FILE_TOKEN.findall(skill)) >= 5
    assert "bp_gate.py" in PLUGIN_FILES and "watch.sh" in PLUGIN_FILES


def test_light_fixer_leaves_verification_to_code():
    text = _text(REPO / "agents" / "bug-light-fixer.md")
    assert "light-verify" in text                      # 검증은 누가 하는지 명시
    assert not _GATE_CALL.search(text)                 # 그러나 스스로 게이트를 부르지 않는다 — 리더 몫
    assert "승급" in text and "가설 하나" in text
