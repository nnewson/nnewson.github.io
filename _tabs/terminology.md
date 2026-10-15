---
icon: fas fa-list
order: 6
---

Terms that recur across the fireEngine posts, including project vocabulary and
the particular meaning the engine gives to standard graphics terms. Vulkan's
API vocabulary is defined by the
[specification](https://registry.khronos.org/vulkan/specs/latest/html/vkspec.html);
this page explains the choices a reader would otherwise have to infer from
the posts.

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

A release-specific sum of measured CPU phases used to compare the work of
producing a frame, separately from frame-fence, image-acquisition and
presentation-fence waits and the presentation call. It is neither whole-frame
elapsed time nor a sum of every thread's CPU time. The 0.10 definition is
[total active work](#total-active-work) below.

### Total active work

The primary measurement in fireEngine 0.10, adding these named CPU phases:

- snapshot: transform update, draw-list build and frame recording-input build;
- shared frame-uniform update;
- shadow command-pool reset and primary command recording;
- forward coordinator command-pool reset, secondary recording region, primary
  command recording and secondary command execution; and
- queue submission.

The [released measurement definition](https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tools/benchmark/benchmark_report.py)
excludes frame-fence wait, image-acquisition wait, presentation-fence wait and
the presentation call. The forward recording region still includes dispatch
and waiting for the helper: that is coordination cost, not an excluded frame
wait. Overlapping participant diagnostics are not added again.

This is a sum of instrumented host phases, not all application or pass-call
bookkeeping, GPU time or frame rate. Comparing its values does not measure
the net cost of enabling shadows without a matched shadows-off control.

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
than assuming that cost is negligible. Version 0.9 names the option
`--direct-primary`; 0.10 renames it to `--forward-direct-primary` and rejects
the old spelling. The new name makes its scope explicit: only forward
recording changes; the shadow pass still runs.

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

A **participant** is one CPU thread recording part of the forward pass's draws.
The **coordinator** is the main rendering thread: it controls primary recording,
submission and presentation, and always participates in forward recording.
A **helper** is the optional second thread it dispatches forward secondary
recording to. The number of participants is chosen from the forward draw count;
0.10's shadow pass records serially on the coordinator.

The diagnostic override is `--recording-threads` in 0.9 and
`--forward-recording-participants` in 0.10, taking either `1` or `2` as its
argument. Version 0.10 rejects the old spelling;
the count includes the coordinator, not just helpers, and applies only to
forward recording.

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
finished. Recording participants receive immutable input derived from that
state rather than reading or modifying the live scene. The complete input is
named `RecordingInput` in 0.9 and `FrameRecordingInput` in 0.10, where it
contains separate restricted views for the two passes.

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

## Shadow rendering

These definitions describe the conventions used in fireEngine 0.10.

### Caster

An object included in the light-view depth rendering so it can block light
from reaching other surfaces, including its own. In 0.10,
`RenderObject::castsShadow` controls whether a draw enters the shadow packet
sequence. It defaults to true and does not control whether the object appears
in the camera view.

### Receiver

A surface whose forward shading uses the shadow map to decide whether it is
occluded from the light. Every forward draw in 0.10 receives shadows. The
procedural ground plane is **receive-only**: it is drawn and samples the map,
but its `castsShadow` value is false, so it contributes no depth to that map.
An object can be both a caster and a receiver.

### Shadow map

A depth image rendered from the light's view. The forward shader projects a
receiver into that view and compares its depth with the stored depth to test
for occlusion. Version 0.10 uses one fixed 1024-by-1024 map per frame slot;
the two maps are independent of swapchain images and survive window resizing.

### Frustum

The volume covered by a view's projection, bounded by its sides and near/far
planes. A perspective camera's frustum widens with distance. The orthographic
light view in 0.10 covers a box whose width and height stay constant. Receiver
positions outside that light volume are treated as lit by the shadow lookup.

### Depth bias

An adjustment to the depths used in a shadow comparison to reduce erroneous
self-shadowing caused by finite precision and sampling. Version 0.10 applies
constant and slope-scaled bias when writing the map, then subtracts a separate
small offset from the receiver's comparison depth. These are different places
to adjust the comparison; excessive bias can detach a shadow from its caster.

### Slope-scaled depth bias

The part of raster depth bias that grows with a primitive's depth slope in
framebuffer coordinates. It supplements the constant term on surfaces whose
depth changes rapidly across pixels. In 0.10 it is applied during the shadow
pass, using a slope factor of 1.75; it does not change the receiver offset or
provide a normal-based lighting calculation.

### Publication

In the shadow posts, making the shadow pass's depth writes available and
visible to later fragment-shader sampling. `ShadowRecorder` records the image
barrier after depth rendering, including the transition to a read-only depth
layout. This is a GPU memory dependency; it neither transfers C++ ownership
nor replaces the frame-slot fence that protects reuse of the map.

### Pass input

The immutable values and non-owning handles a particular recorder receives.
The frame compiler resolves the scene once and produces two restricted views:
shadow input contains geometry and model transforms, while forward input also
contains material values and texture handles. Neither view exposes the owners,
allocator, queue, or mutable scene. Its CPU storage must remain valid until
every recorder using it has finished.
