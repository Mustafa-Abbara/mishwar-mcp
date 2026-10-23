"""Checks on the written deliverables (Part 1 summary)."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from count_words import SUMMARY, count_words  # noqa: E402


@pytest.fixture
def summary_text() -> str:
    if not SUMMARY.exists():
        pytest.skip("docs/summary.md not written yet")
    return SUMMARY.read_text(encoding="utf-8")


def test_count_words_ignores_references():
    assert count_words("one two three\n## References\nfour five") == 3


def test_summary_length(summary_text):
    assert 300 <= count_words(summary_text) <= 400


@pytest.mark.parametrize("term", ["Host", "Client", "Server"])
def test_summary_names_architecture_roles(summary_text, term):
    assert re.search(rf"\b{term}\b", summary_text)


@pytest.mark.parametrize("principle", ["well-defined interface", "isolated functionality", "predictable behaviour"])
def test_summary_names_class_principles(summary_text, principle):
    assert principle in summary_text.lower().replace("behavior", "behaviour")
