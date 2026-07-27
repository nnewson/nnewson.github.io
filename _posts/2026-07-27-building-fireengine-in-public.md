---
title: Building fireEngine in Public
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
matching post here that explains:

- the goal for that release;
- the architecture and implementation choices;
- the bugs, profiling results, and unexpected constraints;
- how to build or explore that exact version; and
- what the release unlocks next.

That pairing should make the project useful in two ways: as an engine that
evolves over time, and as a practical record of how a renderer grows from its
first frame into a larger 3D system.

The first engine release is next.
