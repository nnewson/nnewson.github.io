#!/usr/bin/env python3
"""Check that every section quoting source code links to where that code lives.

Two failures this catches, neither of which reading reliably does:

  S1  missing link      a section shows a source excerpt but links to no file
  S2  wrong file        a section links to files, but none of them contain any
                        line of the code it shows

S2 exists because the natural mistake is to link the type a section is *about*
rather than the file its snippet came from. Those diverge whenever a section
discusses a class and quotes its implementation, and a presence check cannot
see it because a link is present.

Only source excerpts are considered. Diagrams, shell commands, and program
output are not expected to carry a link.

A section preceded by `<!-- source-link: ignore -->` is skipped; naming rules
(`<!-- source-link: ignore S2 -->`) silences only those. Use it where a snippet
is deliberately illustrative rather than quoted. A marker that stops matching
anything is reported so suppressions do not rot.

S2 needs a local clone of the linked repository. Without one it is skipped with
a notice rather than failing, so the check still runs on a fresh machine.

Usage:  tools/check_source_links.py [paths...]   (default: _posts, _architecture)
        tools/check_source_links.py --only S1
        tools/check_source_links.py --repo /path/to/clone
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_REPO = Path("/Users/nick/Development/fireEngine-tutorial")

# Fences holding source. Diagrams, commands, and captured output are excluded.
SOURCE_LANGS = {"cpp", "cmake", "hlsl", "slang", "json", "yaml"}

# A section passes S2 on one matching line. Measured against the site's 196
# source-quoting sections: genuine wrong-file links matched zero lines, while
# every correctly linked section matched at least one. Requiring two produced
# six false positives from rewrapped or comment-stripped excerpts.
MIN_MATCHING_LINES = 1
MIN_LINE_LENGTH = 10  # shorter lines match too much to be evidence

BLOB = re.compile(r"github\.com/[^/]+/([^/]+)/blob/([^/]+)/([^#\s)]+)")
LINK_DEF = re.compile(r"^\[([^\]]+)\]:\s*<?([^>\s]+)>?", re.M)
REF_USE = re.compile(r"\]\[([^\]]+)\]")
INLINE = re.compile(r"\]\((https?://[^)]+)\)")
IGNORE = re.compile(r"^[ \t]*<!--[ \t]*source-link:[ \t]*ignore([ \tA-Z0-9]*)-->[ \t]*$")


@dataclass
class Finding:
    path: Path
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.message}"


@dataclass
class Section:
    path: Path
    line: int
    heading: str
    body: list[str]
    ignores: frozenset[str] = field(default_factory=frozenset)


def normalise(text: str) -> str:
    """Drop comments and collapse whitespace so reformatting does not matter."""
    text = re.sub(r"///<.*$", "", text)
    text = re.sub(r"//.*$", "", text)
    text = re.sub(r"/\*.*?\*/", "", text)
    return re.sub(r"\s+", " ", text).strip()


def sections(path: Path):
    """Split one file into `##` sections, ignoring headings inside fences."""
    lines = path.read_text(encoding="utf-8").split("\n")
    current = Section(path, 1, "(preamble)", [])
    fenced = False
    for index, line in enumerate(lines, start=1):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            yield current
            marker = IGNORE.match(lines[index - 2]) if index >= 2 else None
            named = marker.group(1).split() if marker else []
            ignores = frozenset(named or (RULES if marker else ()))
            current = Section(path, index, line[3:].strip(), [], ignores)
        else:
            current.body.append(line)
    yield current


def excerpts(section: Section) -> list[list[str]]:
    """Source-language code blocks inside one section."""
    found: list[list[str]] = []
    collecting, language, buffer = False, None, []
    for line in section.body:
        if line.startswith("```"):
            if not collecting:
                collecting, language, buffer = True, line[3:].strip(), []
            else:
                collecting = False
                if language in SOURCE_LANGS:
                    found.append(buffer)
        elif collecting:
            buffer.append(line)
    return found


def linked_blobs(section: Section, definitions: dict[str, str]):
    """(repo, ref, path) for every source link reachable from this section."""
    body = "\n".join(section.body)
    targets = [definitions.get(name, "") for name in REF_USE.findall(body)]
    targets += INLINE.findall(body)
    return [match.groups() for target in targets if (match := BLOB.search(target))]


class Repo:
    """Reads files at a ref, caching, and degrades to empty when unavailable."""

    def __init__(self, root: Path):
        self.root = root
        self.available = (root / ".git").exists()
        self._cache: dict[tuple[str, str], set[str]] = {}

    def lines(self, ref: str, path: str) -> set[str]:
        key = (ref, path)
        if key not in self._cache:
            result = subprocess.run(
                ["git", "show", f"{ref}:{path}"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            self._cache[key] = (
                {normalise(line) for line in result.stdout.split("\n")}
                if result.returncode == 0
                else set()
            )
        return self._cache[key]


def rule_missing_link(section: Section, definitions, _repo) -> list[Finding]:
    """S1: the section shows source but names no file."""
    if not excerpts(section) or linked_blobs(section, definitions):
        return []
    return [
        Finding(
            section.path,
            section.line,
            "S1",
            f"section quotes source but links to no file: {section.heading!r}",
        )
    ]


def rule_wrong_file(section: Section, definitions, repo) -> list[Finding]:
    """S2: the linked files do not contain any line the section shows."""
    blobs = linked_blobs(section, definitions)
    code = excerpts(section)
    if not code or not blobs or not repo.available:
        return []

    pool: set[str] = set()
    for _, ref, path in blobs:
        pool |= repo.lines(ref, path)
    if not pool:  # unknown ref or path; the path checker owns that failure
        return []

    matches = sum(
        1
        for block in code
        for line in block
        if len(normalise(line)) >= MIN_LINE_LENGTH and normalise(line) in pool
    )
    if matches >= MIN_MATCHING_LINES:
        return []
    listing = ", ".join(path for _, _, path in blobs)
    return [
        Finding(
            section.path,
            section.line,
            "S2",
            f"no line of the shown code appears in {listing} "
            f"— section {section.heading!r}",
        )
    ]


RULES = {"S1": rule_missing_link, "S2": rule_wrong_file}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["_posts", "_architecture"])
    parser.add_argument("--only", nargs="+", choices=sorted(RULES), default=sorted(RULES))
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    args = parser.parse_args()

    repo = Repo(args.repo)
    files: list[Path] = []
    for entry in args.paths:
        path = Path(entry)
        files.extend(sorted(path.rglob("*.md")) if path.is_dir() else [path])

    findings: list[Finding] = []
    stale: list[str] = []
    considered = suppressed = 0
    for path in files:
        definitions = dict(LINK_DEF.findall(path.read_text(encoding="utf-8")))
        for section in sections(path):
            if not excerpts(section):
                continue
            considered += 1
            silenced = 0
            for name in args.only:
                hits = RULES[name](section, definitions, repo)
                if name in section.ignores:
                    suppressed += len(hits)
                    silenced += len(hits)
                    continue
                findings.extend(hits)
            # A marker is stale only when it silenced nothing at all. Reporting
            # per rule would flag every blanket ignore for the rules a section
            # never trips.
            if section.ignores and silenced == 0:
                stale.append(f"{path}:{section.line}")

    for finding in sorted(findings, key=lambda f: (str(f.path), f.line)):
        print(finding)
    for entry in stale:
        print(f"{entry}: stale source-link marker, it silenced nothing")

    if not repo.available and "S2" in args.only:
        print(f"note: {args.repo} is not a clone, so S2 was skipped", file=sys.stderr)

    counts = {name: sum(1 for f in findings if f.rule == name) for name in sorted(RULES)}
    summary = "  ".join(f"{k}={v}" for k, v in counts.items() if k in args.only)
    print(
        f"\n{len(files)} files, {considered} sections quoting source, "
        f"{len(findings)} findings ({suppressed} suppressed)   {summary}",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
