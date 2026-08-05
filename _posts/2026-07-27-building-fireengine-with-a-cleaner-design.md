---
title: Building fireEngine with a cleaner design
date: 2026-07-27 00:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, 3d-engine, devlog]
description: >-
  An introduction and release-by-release roadmap for the fireEngine devlog,
  connecting each working source checkpoint with its technical deep-dive.
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

## The road to the first triangle

The first six releases take fireEngine from an empty project to a triangle on
screen. Each one is a buildable checkpoint that proves a single new contract
before the next layer depends on it, so the split between them follows what can
be verified in isolation rather than what happens to fit in one sitting.

The opening sequence is:

```text
toolchain and instance
    -> device, surface, and queues
        -> allocator, swapchain, and image views
            -> shaders and graphics pipeline
                -> command and synchronization state
                    -> vertex data, frame loop, and first triangle
```

Each release can be cloned and explored independently, but they are designed to
be read in order. The code and explanation accumulate without asking a later
post to hide setup that an earlier one has not established.

### Release 0.1 — Create the Vulkan foundation

[Creating fireEngine's Vulkan foundation][post-0-1] establishes the development
environment used by every later checkpoint: C++23, CMake, reproducible vcpkg
dependencies, Vulkan-Hpp RAII, strict warnings, formatting, static analysis,
cross-platform CI, and a CTest smoke test.

The executable creates and automatically destroys a Vulkan 1.4 instance. It
does not open a window or select a device yet; its job is to prove that the
toolchain, Vulkan loader, and installed driver can complete the smallest useful
lifecycle. The exact source is preserved in [release 0.1][release-0-1].

### Release 0.2 — Connect to a usable device

[Connecting fireEngine to its first Vulkan device][post-0-2] opens a GLFW
window, creates its Vulkan surface, enables optional validation, and evaluates
the physical devices exposed by the loader. Device selection checks Vulkan 1.4,
swapchain support, dynamic rendering, Synchronization 2, and the graphics and
presentation queue families needed by the renderer.

The release finishes with one logical device and queues capable of drawing and
presenting, while clearer core, platform, and rendering boundaries keep startup
responsibilities separate. It still exits as soon as initialization succeeds.
See [release 0.2][release-0-2].

### Release 0.3 — Prepare presentable images

[Preparing fireEngine for its first frame][post-0-3] introduces Vulkan Memory
Allocator and constructs the swapchain. Surface capabilities drive the colour
format, presentation mode, image count, physical-pixel extent, transform,
compositing mode, and sharing policy, with one image view created for every
presentable image.

The allocator is created, but nothing is allocated from it yet. Buffer
ownership waits until release 0.6, where there is finally a command path ready
to use it, and keeping the two apart leaves this checkpoint free to concentrate
on presentation storage. See [release 0.3][release-0-3].

### Release 0.4 — Build the graphics pipeline

[Creating fireEngine's first graphics pipeline][post-0-4] adds the program and
fixed-function state that will eventually write into a swapchain image. A Slang
source file compiles to SPIR-V 1.6 during the normal build, with vertex and
fragment entry points joined by explicit shader and C++ interfaces.

The Vulkan 1.4 pipeline uses dynamic rendering, a push-descriptor layout for a
future frame uniform, dynamic viewport and scissor state, and maintenance5 to
consume SPIR-V without temporary shader modules. No buffer is bound and no draw
is recorded yet; this release proves that the driver accepts the complete
pipeline contract first. See [release 0.4][release-0-4].

### Release 0.5 — Prepare one frame in flight

[Preparing fireEngine's first frame in flight][post-0-5] creates the command and
synchronization state needed to use that pipeline. One `FrameInFlight` owner
groups a graphics command pool, primary command buffer, image-available binary
semaphore, and initially signaled completion fence.

Presentation semaphores instead follow swapchain images, preventing a later
frame from re-signaling a semaphore while presentation may still be waiting on
it. Whole-pool recycling and the separation between frame-indexed and
image-indexed resources establish the reuse policy before recording and
submission make it stateful. See [release 0.5][release-0-5].

### Release 0.6 — Render and present the triangle

[Rendering fireEngine's first triangle][post-0-6] completes the first visible
rendering path. A VMA-backed `AllocatedBuffer` supplies the three coloured
vertices and one identity-transform uniform per frame slot. A `Renderer` waits
for safe reuse, acquires an image, resets and records the command buffer,
submits it to the graphics queue, and presents it through the presentation
queue.

The recording uses Synchronization 2 image barriers, a dynamic colour
attachment, viewport and scissor state, a pushed uniform descriptor, and one
non-indexed draw. The persistent GLFW event loop renders until the window
closes, while a bounded mode lets CTest prove one complete presented frame.
Swapchain recreation remains a later concern: an out-of-date or suboptimal
surface reports the change and exits cleanly rather than rebuilding. That leaves
[release 0.6][release-0-6] as a complete but deliberately small first triangle.

The triangle is not the destination. It is the smallest path that exercises
every stage a real frame uses, which makes it a solid base to widen rather than
a demo to throw away. The next step keeps that image deliberately unchanged
while restructuring everything behind it: meshes, materials, and scene
hierarchy become Vulkan-free descriptions that a renderer compiles into GPU
work, with unit tests covering the parts that no longer need a device.
Swapchain recreation and window resize then follow as some of the first new
features built on that structure.

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
   established by the checkpoint and identifies what it makes possible next.
5. **Recommended reading.** Most entries end with a short list of books and
   primary documentation for readers who want to explore the topics in greater
   depth.

The details will vary with the work. A rendering checkpoint may need profiling
results and diagrams; an infrastructure release may spend more time on build
files and failure modes. The common structure should still make it clear where
the release starts, what changed, and where the engine can go next.

Together, these releases move from a repeatable empty Vulkan process to a
presented triangle without skipping the ownership and synchronization
boundaries between them.

## Recommended reading

- [Real-Time Rendering](https://www.realtimerendering.com/) — the classic
  end-to-end reference for real-time rendering systems, spanning the graphics
  pipeline, hardware, transforms, shading, effects, optimization, and
  acceleration techniques.

The [Reading page]({% link _tabs/reading.md %}) keeps the site-wide list in one
place.

[post-0-1]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[post-0-2]: {% post_url 2026-07-31-connecting-fireengine-to-its-first-vulkan-device %}
[post-0-3]: {% post_url 2026-08-01-preparing-fireengine-for-its-first-frame %}
[post-0-4]: {% post_url 2026-08-03-creating-fireengines-first-graphics-pipeline %}
[post-0-5]: {% post_url 2026-08-04-preparing-fireengines-first-frame-in-flight %}
[post-0-6]: {% post_url 2026-08-05-rendering-fireengines-first-triangle %}
[release-0-1]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.1
[release-0-2]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.2
[release-0-3]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.3
[release-0-4]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.4
[release-0-5]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.5
[release-0-6]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6
