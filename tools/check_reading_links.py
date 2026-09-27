#!/usr/bin/env python3
"""Check that every reading link cited by a post is listed on the Reading page.

Posts cite background material through `[reading-*]` reference definitions and
then point at the Reading page for the site-wide list. That convention only
holds if the page actually contains what the posts cite, and nothing else
enforces it — a post can define a perfectly valid external link that the page
never mentions, and both build and render cleanly.

Only one direction is checked. The Reading page is a curated collection, so it
may list a book or site that no post has cited yet; that is not an error.

Usage:  tools/check_reading_links.py [paths...]  (default: _posts, _architecture)
        tools/check_reading_links.py --page _tabs/reading.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_PAGE = Path("_tabs/reading.md")

# `[reading-something]: <https://…>` or the same without angle brackets.
READING_DEF = re.compile(r"^\[(reading-[a-z0-9-]+)\]:\s*<?(https?://[^>\s]+)>?", re.M)
PAGE_URL = re.compile(r"\((https?://[^)]+)\)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["_posts", "_architecture"])
    parser.add_argument("--page", type=Path, default=DEFAULT_PAGE)
    args = parser.parse_args()

    if not args.page.exists():
        print(f"error: {args.page} does not exist", file=sys.stderr)
        return 2
    listed = set(PAGE_URL.findall(args.page.read_text(encoding="utf-8")))

    files: list[Path] = []
    for entry in args.paths:
        path = Path(entry)
        files.extend(sorted(path.rglob("*.md")) if path.is_dir() else [path])

    findings = 0
    cited = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name, url in READING_DEF.findall(text):
            cited += 1
            if url in listed:
                continue
            line = next(
                (i for i, l in enumerate(text.split("\n"), 1) if l.startswith(f"[{name}]:")),
                1,
            )
            findings += 1
            print(f"{path}:{line}: {name} cites a URL absent from {args.page}\n    {url}")

    print(
        f"\n{len(files)} files, {cited} reading citations, {len(listed)} URLs on the page, "
        f"{findings} findings",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
