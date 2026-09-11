---
icon: fas fa-list
order: 6
---

Terms that recur across the fireEngine posts and are specific to this project
or its tooling. Vulkan's own vocabulary is defined by the
[specification](https://registry.khronos.org/vulkan/specs/latest/html/) and is
not repeated here; what follows is the set a competent Vulkan reader would
still have to guess at.

Each post introduces the terms it needs near the top. This page collects them
in one place for anyone arriving part-way through a series.

## Implementations and environments

### Lavapipe

Mesa's CPU implementation of Vulkan. It renders entirely on the processor with
no GPU, which makes it available on continuous-integration machines that have
no graphics hardware. Its absolute timings are not comparable with a hardware
driver, but it runs the same API and the same validation.

### KosmicKrisp

The Vulkan implementation for Apple Silicon supplied as a technical preview in
the LunarG Vulkan SDK. fireEngine targets it for macOS rather than using the
portability extensions directly.

### ICD

Installable Client Driver: a manifest file that tells the Vulkan loader where
an implementation lives. Selecting a specific ICD is how a machine with several
Vulkan implementations is told which one to use.

### Xvfb

X virtual framebuffer — an X server that draws to memory instead of a display.
It lets a headless CI machine create a real window and swapchain, so
presentation code runs rather than being skipped.

### Decision-bearing implementation

A mature, conformant Vulkan implementation whose behaviour is considered sound
enough to base an architectural decision on. A measurement from a prototype or
an unusual configuration may be informative without being decision-bearing.

## Measurement

### A/X/B

The measurement ordering used for every performance claim. A control run `A`,
then the candidate `X`, then a second control `B`, all from the same binary in
one session. The control baseline is `C = (A + B) / 2`.

### Control drift

The gap between the two controls in an A/X/B run, `D = abs(B - A)`. It is the
noise floor for that measurement: the machine's own variation between two runs
of identical code.

### Unresolved within drift

A candidate result whose distance from the baseline is no larger than the
control drift, `abs(X - C) <= D`. Such a result supports no directional claim.
Only `abs(X - C) > D` counts as a measured difference.

### Active work

The host work a frame performs, as observed by the coordinating thread,
excluding time spent blocked waiting for presentation. Speedups are computed
over active work so that a slower display cannot disguise a change in CPU cost.

### Materialisation

The share of a predicted improvement that measurement actually delivers. A
model predicting a 40% reduction that measures 20% has materialised half of it.

### Registered decision rule

A gate written down with its threshold **before** the measurement that tests
it, so a disappointing result cannot be rescued by moving the bar afterwards.
The same applies to a registered remediation: one pre-agreed fix, not unlimited
tuning until the gate passes.

### Direct-primary control

A diagnostic rendering mode that records the same draws straight into the
primary command buffer instead of into secondary buffers. Comparing it with the
normal path prices what secondary command buffers cost on a given driver rather
than assuming that cost is negligible.

### Positive control

A temporary fault injected on purpose to prove that a test can fail. A gate
that has only ever been green demonstrates that the program exits, not that the
gate detects the defect it claims to.

## Engine and testing vocabulary

### Participant, coordinator, helper

A **participant** is one CPU thread recording part of a frame's draws. The
**coordinator** is the thread that owns the frame and always participates; a
**helper** is the optional second thread it dispatches work to. The number of
participants is chosen from the draw count.

### Device-free test

A test that runs without a window, Vulkan instance, or GPU. Most engine rules —
maths, validation, scene traversal, dependency selection — are decidable this
way, and are covered by Catch2 cases rather than by rendering.

### Smoke scenario

A bounded run of the real application, driven through CTest, that exercises a
complete path on an actual device and then exits. Named scenarios such as
`basic`, `prepare-twice`, `untextured`, and `resize` each compose a different
set of engine pieces.

### Vulkan-free

A type or layer that carries no Vulkan header, handle, or enum. It is the
boundary that keeps content, scene, and animation code independent of the
renderer, and testable without a device.
