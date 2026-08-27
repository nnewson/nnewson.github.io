#!/usr/bin/env python3
"""Lint ASCII diagrams in ```text fences for alignment mistakes.

Proof of concept. Reports four classes of problem:

  R1  near-miss connectors  two line-art characters of the same kind that
                            almost share a column but do not
  R2  column drift          sibling tree nodes whose trailing descriptions
                            do not share one column
  R3  box integrity         box-drawing rectangles with ragged borders
  R4  width                 blocks wide enough to force a horizontal
                            scrollbar in the rendered page
  R5  broken run            a vertical with line art above and below but a
                            whitespace gap in between

A block preceded by `<!-- align: ignore -->` is skipped entirely; naming rules
(`<!-- align: ignore R1 -->`) silences only those. Use it where the layout is
deliberate and the checker cannot know it — a marker that stops matching
anything is reported so suppressions do not rot.

Usage:  tools/check_diagrams.py [paths...]     (default: _posts, _architecture)
        tools/check_diagrams.py --only R1 R3
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_WIDTH = 80
NEAR_MISS = 2  # column difference that counts as "almost aligned"
LINE_WINDOW = 4  # only compare connectors this close together

VERTICALS = "│|"
JOINTS = "┌┐└┘├┤┬┴┼+"
ARROWHEADS = "v^"
ARROWENDS = "><"
LINEART = "─-═=│|" + JOINTS
# A run is only broken if the character above reaches downward and the one
# below reaches upward. `┘` closing a join and `┬` opening a new one may share
# a column without being one line.
CONTINUES_DOWN = "│|┌┐├┤┬+^"
CONTINUES_UP = "│|└┘├┤┴+v"

BLOCK = re.compile(r"^([ \t]*)```text[ \t]*$")
FENCE_END = re.compile(r"^[ \t]*```[ \t]*$")
IGNORE = re.compile(r"^[ \t]*<!--[ \t]*align:[ \t]*ignore([ \tA-Z0-9]*)-->[ \t]*$")


@dataclass
class Finding:
    path: Path
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.message}"


@dataclass
class Block:
    path: Path
    start: int  # 1-based line of the opening fence
    lines: list[str]
    ignores: frozenset[str] = frozenset()  # rules silenced by an align marker

    def at(self, index: int) -> int:
        """Absolute file line for a 0-based index into this block's body."""
        return self.start + 1 + index


def blocks(path: Path):
    """Yield each ```text fenced block in one file."""
    lines = path.read_text(encoding="utf-8").split("\n")
    index = 0
    while index < len(lines):
        if BLOCK.match(lines[index]):
            start = index
            marker = IGNORE.match(lines[index - 1]) if index else None
            named = marker.group(1).split() if marker else []
            ignores = frozenset(named or (RULES if marker else ()))
            body: list[str] = []
            index += 1
            while index < len(lines) and not FENCE_END.match(lines[index]):
                body.append(lines[index])
                index += 1
            yield Block(path, start + 1, body, ignores)
        index += 1


def is_connector(line: str, column: int) -> bool:
    """Decide whether a character is line art rather than prose.

    Box-drawing characters always are. Ambiguous ASCII (+ > v) only counts
    when it sits against other line art, so `linear + repeat` and the `v` in
    `device` are not mistaken for connectors.
    """
    char = line[column]
    if char in "│┌┐└┘├┤┬┴┼":
        return True
    left = line[column - 1] if column > 0 else " "
    right = line[column + 1] if column + 1 < len(line) else " "
    if char in "><":
        # `a -> b` is inline notation; `+---->` and `──>` are line art.
        run = len(line[:column]) - len(line[:column].rstrip("─-═="))
        return run >= 2 or right in LINEART
    if char in "+|":
        return left in LINEART or right in LINEART
    if char in ARROWHEADS:
        # An arrowhead stands alone; a `v` inside a word does not.
        return not (left.isalnum() or right.isalnum())
    return False


def kind(char: str) -> str:
    if char in VERTICALS:
        return "vertical"
    if char in ARROWHEADS:
        return "arrowhead"
    if char in ARROWENDS:
        return "arrow end"
    return "joint"


def connectors(block: Block):
    """All (row, column, kind) line-art positions in a block."""
    for row, line in enumerate(block.lines):
        for column, char in enumerate(line):
            if char in VERTICALS + JOINTS + ARROWHEADS + ARROWENDS:
                if is_connector(line, column):
                    yield row, column, kind(char)


def rule_near_miss(block: Block) -> list[Finding]:
    """R1: two connectors of one kind that nearly share a column."""
    found: list[Finding] = []
    marks = list(connectors(block))
    seen: set[tuple[int, int, int]] = set()
    for i, (row_a, col_a, kind_a) in enumerate(marks):
        # Horizontal arrow heads sit wherever the words before them end, so
        # their columns carry no alignment intent across rows.
        if kind_a == "arrow end":
            continue
        for row_b, col_b, kind_b in marks[i + 1 :]:
            if kind_a != kind_b or row_b - row_a > LINE_WINDOW:
                continue
            if row_a == row_b:
                continue
            gap = abs(col_a - col_b)
            if 0 < gap <= NEAR_MISS:
                key = (min(col_a, col_b), max(col_a, col_b), row_a)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    Finding(
                        block.path,
                        block.at(row_a),
                        "R1",
                        f"{kind_a} at column {col_a + 1} (line {block.at(row_a)}) "
                        f"and column {col_b + 1} (line {block.at(row_b)}) "
                        f"differ by {gap}",
                    )
                )
    return found


def rule_column_drift(block: Block) -> list[Finding]:
    """R2: sibling tree nodes whose trailing descriptions do not share a column.

    Restricted to lines that carry a tree connector and end in prose, which is
    what separates a ragged label/description list from a deliberate
    multi-panel layout: in a panel the text after the gap is more line art, and
    in a nested list there is no connector on the line at all.
    """
    columns: dict[int, list[int]] = {}
    for row, line in enumerate(block.lines):
        if not any(c in line for c in "├└"):
            continue
        gaps = list(re.finditer(r"\S(  +)(\S)", line))
        if not gaps or not (gaps[-1].group(2).isalnum() or gaps[-1].group(2) == "-"):
            continue
        columns.setdefault(gaps[-1].end() - 1, []).append(row)
    total = sum(len(v) for v in columns.values())
    if len(columns) < 2 or total < 3:
        return []
    listing = ", ".join(str(c + 1) for c in sorted(columns))
    return [
        Finding(
            block.path,
            block.start,
            "R2",
            f"tree descriptions start at columns {listing} across {total} lines",
        )
    ]


def rule_box(block: Block) -> list[Finding]:
    """R3: box-drawing rectangles whose borders do not line up."""
    found: list[Finding] = []
    open_rows = [r for r, l in enumerate(block.lines) if "┌" in l and "┐" in l]
    for top in open_rows:
        bottoms = [
            r
            for r, l in enumerate(block.lines)
            if r > top and "└" in l and "┘" in l
        ]
        if not bottoms:
            continue
        bottom = bottoms[0]
        left = block.lines[top].index("┌")
        right = block.lines[top].index("┐")
        for row in range(top, bottom + 1):
            line = block.lines[row]
            edges = [c for c, ch in enumerate(line) if ch in "│┌┐└┘"]
            if not edges:
                continue
            if min(edges) != left or max(edges) != right:
                found.append(
                    Finding(
                        block.path,
                        block.at(row),
                        "R3",
                        f"box edge at columns {min(edges) + 1}..{max(edges) + 1}, "
                        f"expected {left + 1}..{right + 1}",
                    )
                )
    return found


def rule_broken_run(block: Block) -> list[Finding]:
    """R5: a vertical that has line art above and below, but a gap in between.

    Only whitespace counts as a gap. Where a label or arrow deliberately
    occupies the column the run is considered to pass behind it, which is a
    normal way to draw and not reported.
    """
    marks = {
        (row, column): block.lines[row][column]
        for row, column, kind in connectors(block)
        if kind != "arrow end"  # horizontal heads never form a vertical
    }
    found: list[Finding] = []
    for row in range(1, len(block.lines) - 1):
        line = block.lines[row]
        for column in sorted({c for r, c in marks if r == row - 1}):
            if (row, column) in marks or (row + 1, column) not in marks:
                continue
            if marks[(row - 1, column)] not in CONTINUES_DOWN:
                continue
            if marks[(row + 1, column)] not in CONTINUES_UP:
                continue
            if (line[column] if column < len(line) else " ") != " ":
                continue
            found.append(
                Finding(
                    block.path,
                    block.at(row),
                    "R5",
                    f"column {column + 1} carries line art above and below "
                    f"but is blank here, breaking the run",
                )
            )
    return found


def rule_width(block: Block) -> list[Finding]:
    if not any(True for _ in connectors(block)):
        # No line art: a console transcript or config excerpt, not a diagram.
        return []
    widest = max((len(l) for l in block.lines), default=0)
    if widest <= MAX_WIDTH:
        return []
    row = max(range(len(block.lines)), key=lambda r: len(block.lines[r]))
    return [
        Finding(
            block.path,
            block.at(row),
            "R4",
            f"block is {widest} columns wide (limit {MAX_WIDTH})",
        )
    ]


RULES = {
    "R1": rule_near_miss,
    "R2": rule_column_drift,
    "R3": rule_box,
    "R4": rule_width,
    "R5": rule_broken_run,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["_posts", "_architecture"])
    parser.add_argument("--only", nargs="+", choices=sorted(RULES), default=sorted(RULES))
    args = parser.parse_args()

    files: list[Path] = []
    for entry in args.paths:
        path = Path(entry)
        files.extend(sorted(path.rglob("*.md")) if path.is_dir() else [path])

    findings: list[Finding] = []
    stale: list[str] = []
    block_count = 0
    suppressed = 0
    for path in files:
        for block in blocks(path):
            block_count += 1
            for name in args.only:
                hits = RULES[name](block)
                if name in block.ignores:
                    suppressed += len(hits)
                    if not hits:
                        stale.append(f"{path}:{block.start}: {name}")
                    continue
                findings.extend(hits)

    for finding in sorted(findings, key=lambda f: (str(f.path), f.line)):
        print(finding)

    for entry in stale:
        print(f"{entry} stale align marker: rule found nothing to silence")

    counts = {name: sum(1 for f in findings if f.rule == name) for name in sorted(RULES)}
    summary = "  ".join(f"{k}={v}" for k, v in counts.items() if k in args.only)
    print(
        f"\n{len(files)} files, {block_count} blocks, {len(findings)} findings "
        f"({suppressed} suppressed)   {summary}",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
