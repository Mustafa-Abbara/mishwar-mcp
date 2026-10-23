"""Count the words of docs/summary.md, ignoring everything from '## References' on."""
import re
import sys
from pathlib import Path

SUMMARY = Path(__file__).resolve().parent.parent / "docs" / "summary.md"


def count_words(text: str) -> int:
    body = text.split("## References")[0]
    return len(re.findall(r"\b[\w'-]+\b", body))


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SUMMARY
    print(count_words(path.read_text(encoding="utf-8")))
