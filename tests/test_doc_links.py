"""Every relative link in the repository's Markdown files points at a file that exists.

Moving a document breaks links to it silently. This check finds them: for each tracked
Markdown file it resolves every relative link target (and the #heading anchor, when the
target is a Markdown file) and fails with the file, link and reason.
"""
from pathlib import Path
import re
import subprocess

import pytest

REPO = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~)")


def tracked_markdown():
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [REPO / p for p in out.splitlines() if (REPO / p).is_file()]


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`|\*|_(?=\W)|(?<=\W)_", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    found, seen, fenced = set(), {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            base = slug(line.lstrip("#"))
            n = seen.get(base, 0)
            seen[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(path):
    fenced = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in LINK.finditer(re.sub(r"`[^`]*`", "", line)):
            yield number, match.group(1)


def test_relative_markdown_links_resolve():
    problems = []
    for doc in tracked_markdown():
        for number, target in links(doc):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("/"):
                continue
            path, _, anchor = target.partition("#")
            dest = (doc.parent / path).resolve() if path else doc
            where = f"{doc.relative_to(REPO)}:{number} -> {target}"
            if not dest.exists():
                problems.append(f"{where}: no such file")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                problems.append(f"{where}: no heading #{anchor}")
    assert not problems, "Broken links:\n" + "\n".join(problems)


@pytest.mark.parametrize("heading, expected", [
    ("Setting it up", "setting-it-up"),
    ("Triage checks (ADR-007)", "triage-checks-adr-007"),
    ("My skills", "my-skills"),
])
def test_slug(heading, expected):
    assert slug(heading) == expected
