#!/usr/bin/env python3
"""Lightweight integrity checks for post-merge resolution regressions."""

from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

PRESENCE_CHECKS = [
    (
        "Disambiguation module exposes core helpers",
        ROOT / "backend" / "disambiguation.py",
        [
            r"def\s+detect_option_reference\(",
            r"def\s+resolve_candidate_reference\(",
            r"def\s+is_probable_disambiguation_followup\(",
        ],
    ),
    (
        "Chat pipeline imports disambiguation helpers",
        ROOT / "backend" / "chat.py",
        [
            r"from\s+backend\.disambiguation\s+import\s+.*detect_option_reference",
            r"resolve_candidate_reference",
            r"is_probable_disambiguation_followup",
        ],
    ),
    (
        "Chat response includes disambiguation return branch",
        ROOT / "backend" / "chat.py",
        [
            r'"disambiguation"\s*:\s*\{',
            r'"return_branch"\s*:\s*"disambiguation"',
            r"set_pending_disambiguation\(",
        ],
    ),
    (
        "Query decomposition keeps legal canonicalization",
        ROOT / "backend" / "smart" / "query_decompose.py",
        [
            r"def\s+canonicalize_legal_query\(",
            r"canonical_query\s*=\s*canonicalize_legal_query\(query\)",
        ],
    ),
    (
        "Release gate still validates guarded suite",
        ROOT / "scripts" / "ci_release_gate.sh",
        [
            r"backend/tests/test_ranking_scorer\.py",
            r"backend/tests/test_query_canonicalization\.py",
            r"tests/test_disambiguation\.py",
        ],
    ),
    (
        "Attorney-mode defaults are opt-in (False)",
        ROOT / "backend" / "main.py",
        [
            r"attorney_mode:\s*bool\s*=\s*False",
            r"attorneyMode:\s*bool\s*=\s*False",
        ],
    ),
]

ABSENCE_CHECKS = [
    (
        "Citation-guide route removed from router",
        ROOT / "client" / "src" / "App.tsx",
        [r"/citation-guide"],
    ),
    (
        "Legacy citation guide page removed",
        ROOT / "client" / "src" / "pages" / "CitationGuide.tsx",
        [],
    ),
]


def check_presence(path: Path, patterns: list[str]) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, [f"missing file: {path}"]

    text = path.read_text(encoding="utf-8")
    missing = [pat for pat in patterns if re.search(pat, text, flags=re.DOTALL) is None]
    return len(missing) == 0, missing


def check_absence(path: Path, patterns: list[str]) -> tuple[bool, list[str]]:
    if not path.exists():
        return True, []

    text = path.read_text(encoding="utf-8")
    found = [pat for pat in patterns if re.search(pat, text, flags=re.DOTALL) is not None]
    return len(found) == 0, found


def main() -> int:
    failures = 0
    print("Merge Resolution Integrity Check")
    print("=" * 34)

    for title, path, patterns in PRESENCE_CHECKS:
        ok, missing = check_presence(path, patterns)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {title}")
        if not ok:
            failures += 1
            for pat in missing:
                print(f"   - missing pattern: {pat}")

    for title, path, patterns in ABSENCE_CHECKS:
        ok, found = check_absence(path, patterns)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {title}")
        if not ok:
            failures += 1
            for pat in found:
                print(f"   - forbidden pattern present: {pat}")

    print("=" * 34)
    if failures:
        print(f"Result: {failures} check(s) failed")
        return 1

    print(f"Result: all {len(PRESENCE_CHECKS) + len(ABSENCE_CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
