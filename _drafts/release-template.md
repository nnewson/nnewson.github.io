---
title: "<Verb> <what changed> in <project>"
date: 2026-01-01 10:00:00 +0100
categories: [<project>, Development]
tags: [<project>, "X.Y", <topic>, <topic>, cpp]
description: >-
  One or two lines saying what this article establishes. Not a list of
  contents.
release_url: "https://github.com/nnewson/<repo>/releases/tag/X.Y"
previous_release_url: "https://github.com/nnewson/<repo>/releases/tag/X.Y-1"
---

<!--
This file is a checklist, not a skeleton. Copy the front matter, then delete
everything below it and write the article the argument needs.

Deliberately there is no section list. A fixed set of headings produces
articles that are complete and interchangeable; the sections get filled
because they exist, not because the argument needs them. Sections are decided
per article, from the questions below.

Version tags MUST be quoted: `"0.9"`, not 0.9. Unquoted, YAML parses it as a
float and the generated tag page is wrong.
-->

## Before writing

**What is the claim?** One sentence, written down before the article. If it
cannot be stated in one sentence, the article has more than one subject.

**What would falsify it?** If nothing would, it is a description rather than a
claim, and the piece is reference material — which is fine, but say so and
stop applying the rest of this list.

**What does the reader believe at the end that they did not believe at the
start?** That is the conclusion. It is not a summary of what was covered.

## While writing

**Every section needs a *because*.** For each one, ask what the argument loses
if it is deleted. "A fact" is not an answer.

**Can any two sections swap without damage?** If yes, they are topics, not
moves in an argument. Either give the later one a dependency on the earlier, or
collapse the set into a table and keep only the case that carries the weight.

**Nothing is claimed before it is earned.** If a section says a test found a
defect, the mechanism that detects defects is already established. Walk the
order once looking only for this.

**Code excerpts argue or they go.** A before/after pair usually argues. A
single excerpt has to justify itself. Link to the tag with a line range where
the exact lines matter.

**Cite where the evidence is, not everywhere.** Links belong inline at the
point of the claim.

**Link the file the snippet came from, not the type the section is about.**
Those diverge whenever a section discusses a class and quotes its
implementation, which is often. A section about `Pipeline` that shows pipeline
*creation* wants `pipeline.cpp`, not `pipeline.hpp`. Keep any other genuinely
relevant link alongside it. A section that shows no source needs no link at
all.

## Evidence

**Measurements** state the hardware, driver, workload, run count, and spread.
A number without them is an assertion with a decimal point. Say what the
measurement does *not* cover — a result on one implementation limits the
claim, it does not merely record where it came from.

**Experiments** — a deliberate temporary change made to learn something —
record all of:

- that it was a temporary local mutation, since it is not in the tag;
- the exact change, or a link to the affected lines;
- the precise command and the named test registrations;
- the device and driver environment;
- what failed, what stayed green, and the message that identified it;
- that the mutation was reverted afterwards.

If any of those was not captured, say so in the article. An author-reported
result with a stated gap is honest; one presented as recoverable from the tag
is not.

**Rejected approaches** need somewhere to point. A branch is not a permalink.
Prefer a small recorded recipe — patch plus command plus result — over
preserving dead code in the repository.

## Include

- **A way to run it.** Checkout, configure, build, and the specific command
  that reproduces what the article discusses.

  ```shell
  git clone https://github.com/nnewson/<repo>.git
  cd <repo>
  git checkout X.Y
  cmake --preset <preset> && cmake --build --preset <preset>
  ctest --preset <preset> -R "^(<the tests this article is about>)$"
  ```

- **Recommended reading**, with every link also added to `_tabs/reading.md`.

- **Cross-links** to the release's architecture page and to the posts this one
  depends on, by descriptive name — "the descriptions post", not "the previous
  article".

## Do not include

Retired with the tutorial format, because each assumes a reader reproducing a
known outcome rather than following an argument:

- a **Verify** section — verification is part of the argument, not an appendix;
- a **Diagnose / troubleshooting** runbook;
- a closing **delivery checklist** of what the release gives you;
- per-section `See [file]` footers;
- **ordinal or positional framing** — "the third post", "the next article" —
  while the set is unfinished and its cuts may still move.

## Before publishing

- every linked source path resolves **at the tag**, not on a branch;
- every quoted snippet matches the tag, including field order;
- every count — tests, registrations, cases — checked against the tag;
- every named test or CTest registration exists, and any `-R` regex selects
  exactly the intended set;
- every section quoting source links to the file that source lives in;
- link references balance: nothing undefined, nothing orphaned;
- `python3 tools/check_diagrams.py` is clean;
- `python3 tools/check_source_links.py` is clean;
- `bundle exec jekyll build` is clean;
- reading links are present in `_tabs/reading.md`.

The two script checks run automatically in `.githooks/pre-commit`. The build
and everything above them are judgement or manual steps no tool makes for you.
