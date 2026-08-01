---
title: Building fireEngine with a cleaner design
date: 2026-07-27 00:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, 3d-engine, devlog]
description: >-
  An introduction to the fireEngine devlog and how each engine release will
  connect working source code with a technical deep-dive.
---

Building a 3D engine is a long chain of choices. The final code shows *what*
works, but it rarely captures why one design won, which experiments failed, or
what trade-offs only became visible later.

This devlog is where those details will live.

The companion
[fireEngine tutorial repository](https://github.com/nnewson/fireEngine-tutorial)
will keep the working source. Each meaningful engine release will have a
matching post here, while the release tag preserves the exact code being
discussed.

That pairing should make the project useful in three ways: as an engine that
evolves over time, as a practical record of how a renderer grows from its first
frame into a larger 3D system, and as a cleaner refactor of my
[fireEngine](https://github.com/nnewson/fireEngine) repo.

## How each release post is structured

Each release deep-dive will follow the same broad sequence:

1. **Connection to the release.** The information box near the top links to the
   exact release checkpoint, keeping every explanation and code sample tied to
   a version that can still be built and explored later.
2. **Introducing the new pieces.** Before looking at implementation details,
   the post explains the new tools, Vulkan objects, or engine systems at a high
   level: what each one does, which problem it solves, and how it fits into the
   larger engine.
3. **The implementation walkthrough.** A show-and-tell tour follows the code,
   build changes, design choices, diagnostics, and any bugs or constraints that
   shaped the release.
4. **What the release gives us.** The conclusion collects the working contract
   established by the milestone and identifies what it makes possible next.
5. **Recommended reading.** Most entries end with a short list of books and
   primary documentation for readers who want to explore the topics in greater
   depth.

The details will vary with the work. A rendering milestone may need profiling
results and diagrams; an infrastructure release may spend more time on build
files and failure modes. The common structure should still make it clear where
the release starts, what changed, and where the engine can go next.

The first release starts with the smallest useful Vulkan process: establish a
repeatable build, create an instance, and prove that its lifetime is managed
safely.

## Recommended reading

- [Real-Time Rendering](https://www.realtimerendering.com/) — the classic
  end-to-end reference for real-time rendering systems, spanning the graphics
  pipeline, hardware, transforms, shading, effects, optimisation, and
  acceleration techniques.

The [Reading page]({% link _tabs/reading.md %}) keeps the site-wide list in one
place.
