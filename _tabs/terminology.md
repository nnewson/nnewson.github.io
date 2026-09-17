---
icon: fas fa-list
order: 6
---

Terms that recur across the fireEngine posts and are specific to this project
or its tooling. Vulkan's own vocabulary is defined by the
[specification](https://registry.khronos.org/vulkan/specs/latest/html/vkspec.html) and is
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

A Vulkan implementation declared in advance as eligible to affect the decision
to retain or reject a change. A measurement from a preview implementation or
an unusual configuration may be informative without being decision-bearing.

## Measurement

### Bracketed control comparison

An `A₁/X/A₂` ordering used for performance comparisons. It runs the control
configuration as `A₁`, the candidate as `X`, then the same control again as
`A₂`, all using the same executable in one session. The control baseline is
`C = (A₁ + A₂) / 2`.

### Control drift

The gap between the two matching controls placed around a candidate. It is the
noise floor for that measurement: the machine's own variation between two runs
of identical code. In an `A₁/X/A₂` run, `D = abs(A₂ - A₁)`.

### Unresolved within drift

A candidate result whose distance from the mean control baseline is no larger
than the control drift. Such a result supports no directional claim. In an
`A₁/X/A₂` run, only `abs(X - C) > D` counts as a measured difference.

### Active work

The host work a frame performs, as observed by the coordinating thread,
excluding time spent blocked waiting for presentation. Speedups are computed
over active work so that a slower display cannot disguise a change in CPU cost.

### Snapshot

The CPU work that turns the current scene state into the ordered, validated,
immutable input consumed by command recording. Its internal phases can evolve
while the boundary remains before recording begins.

### Materialisation

The share of a predicted improvement that measurement actually delivers. A
model predicting a 40% reduction that measures 20% has materialised half of it.

### Registered decision rule

A gate written down with its threshold **before** the measurement that tests
it, so a disappointing result cannot be rescued by moving the bar afterwards.
The same applies to a registered remediation: one pre-agreed fix, not unlimited
tuning until the gate passes.

### Attempt gate

A model-based threshold applied before implementing an experiment. It asks
whether a perfect version of the proposed mechanism has enough theoretical
headroom to justify trying it; passing does not predict that the real mechanism
will earn its overhead.

### Retention gate

A threshold applied to the measured implementation after its dispatch,
synchronization, duplicated setup, and completion costs are included. It asks
whether enough of the predicted improvement materialised for the mechanism to
remain in the released design.

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

### Synchronization validation

An optional part of the Vulkan validation layer that checks whether resource
accesses are ordered and synchronized correctly. It detects hazards that can
remain hidden when ordinary valid-usage checks and the rendered image both look
clean.

### Participant, coordinator, helper

A **participant** is one CPU thread recording part of a frame's draws. The
**coordinator** is the main rendering thread: it owns the primary command
buffer, submission, and presentation, and always participates. A **helper** is
the optional second thread it dispatches secondary-command recording to. The
number of participants is chosen from the draw count.

### Capability boundary

An interface or value that gives a consumer only the data and operations its
role requires. It is narrower than a `const` view of a more powerful owner:
operations outside the role are absent rather than merely discouraged.

### Frame slot

The synchronization and per-frame storage reused for one submitted frame. A
frame slot is independent of both a CPU recording participant and a swapchain
image; fireEngine cycles slots while the Vulkan implementation chooses which
presentable image is acquired.

### Frozen frame

A frame whose scene mutation, transform resolution, and resource lookup have
finished. Recording participants receive an immutable `RecordingInput` derived
from that state rather than reading or modifying the live scene.

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
