---
title: "Measuring fireEngine's CPU work before adding another thread"
date: 2026-09-13 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, performance, benchmarking, vulkan, cpp]
description: >-
  Build a phase-level benchmark, remove redundant recording work, and locate
  the command-pool reset cost that a future recording thread could own.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

The [secondary-command post][secondary-command-post] establishes that
fireEngine can execute inherited secondary command buffers cleanly. It does
not establish that recording them on another CPU thread would help. A frame
duration cannot supply that missing answer: it combines work that a recorder
might shorten with work that must remain on the coordinating thread and time
spent waiting for presentation.

fireEngine therefore measures before it divides. A deterministic scene and a
phase-level report first locate the observable CPU work. Those measurements
then expose redundant binding commands that should be removed without
concurrency. A direct-primary control supplies the baseline that did not exist
before secondary recording was introduced. Finally, a temporary command-pool
split determines whether reset cost belongs with the primary or with the
secondary commands recorded into the pool.

The result is a correction to the model, not a speedup. On Mesa Lavapipe at
10,000 draws, the report collected after removing redundant resource bindings
assigned only 41.13% of active work to secondary recording. Separating the
pools showed that almost all reset cost that grew with the recorded command
workload followed the secondary pool.
Assigning that reset cost to the recording participant raised the provisional
share that two recorders could divide from 41.13% to 74.70%, without making a
single command execute faster.

This post covers the phase-measurement and attribution work introduced in the
[0.9 release map][map-post]. The [0.9 architecture page][architecture-0-9]
records the final ownership that those experiments informed, while this post
keeps the temporary controls and their limits visible.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Functional prerequisite: [the secondary-command post][secondary-command-post]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
>
> The measurements below compare phases only within the named environment and
> acquisition. Absolute timings are not compared between machines or between
> unrelated CI sessions.
{: .prompt-info }

## Introducing the measurement vocabulary and environments

Five terms keep the measurements tied to the questions they can answer:

- the **coordinator** is the main rendering thread that owns the primary
  command buffer, queue submission, and presentation;
- **active work** is the CPU work observed by that coordinator after
  excluding waits for frame completion, image acquisition, and presentation;
- the **snapshot** is the CPU work that turns the current scene state into the
  ordered, validated input needed by command recording;
- a **direct-primary control** records the same draws directly into the primary
  command buffer, allowing the secondary-command structure to be compared
  without changing the surrounding frame; and
- an **attribution control** changes where a cost can be observed or who could
  own it. It identifies the relevant phase or owner; it does not prove why a
  driver incurred that cost internally.

One temporary experiment uses an **A₁/X/A₂ bracketed control comparison**: the
control configuration as `A₁`, the candidate as `X`, and the same control again
as `A₂`. Their mean is the baseline and `abs(A₂ - A₁)` is the control drift. A
candidate whose change is no larger than that drift supports no directional
claim.

Two Vulkan implementations supply the early observations. **Lavapipe** is
Mesa's CPU implementation, running through Ubuntu CI without a GPU.
**KosmicKrisp** is the Apple Silicon implementation distributed as a technical
preview in the LunarG SDK. Their absolute timings are not comparable.

The [Terminology page][terminology-page] collects these definitions with the
implementation and measurement vocabulary used across the 0.9 series.

## Measure the frame another recorder would join

The benchmark needs repeatable CPU work rather than an interesting scene. It
creates one synthetic root with a configurable number of child nodes. Every
child uses the same compiled cube render object, while their transforms place
them on a grid. A fixed mutation advances the root before each frame.

That fixture deliberately removes several variables:

| Property | Benchmark choice | Consequence |
|---|---|---|
| geometry and material | every draw reuses one render object | compilation and resource variety do not grow with draw count |
| draw count | selected explicitly with `--benchmark N` | the same workload can be repeated after architectural changes |
| animation | one fixed step per accepted frame | transform work does not depend on wall-clock timing |
| sample window | 16 warm-up and 64 measured frames | setup and early driver behaviour stay outside the report |
| presentation outcome | only cleanly presented frames are retained | out-of-date and suboptimal attempts do not distort the sample set |

The fixture is intentionally favourable to equal range splitting and repeated
binding reuse. It is not a model of arbitrary scenes. That limitation later
prevents its worker result from becoming a universal policy claim.

[`BenchmarkRun`][source-benchmark-run] verifies the requested instance, node,
and draw counts before collecting samples. Its report records the build,
device, driver, presentation configuration, workload, discarded attempts, and
fixed animation step alongside the phase statistics. Each phase includes a
mean, median, and nearest-rank 95th percentile.

The benchmark also has a bounded one-instance CTest registration. It checks
scene generation and report production under validation, but contains no
timing threshold. Hosted-runner performance can vary without turning a
correctness scenario red.

## Put each timer around one question

The renderer exposes timings for one `drawFrame()` attempt through an optional
output value:

```cpp
struct RendererCpuTimings
{
    std::chrono::nanoseconds drawListBuild{};
    std::chrono::nanoseconds drawListValidation{};
    std::chrono::nanoseconds frameFenceWait{};
    std::chrono::nanoseconds imageAcquisitionWait{};
    std::chrono::nanoseconds presentationFenceWait{};
    std::chrono::nanoseconds commandPoolReset{};
    std::chrono::nanoseconds secondaryCommandRecording{};
    std::chrono::nanoseconds primaryCommandRecording{};
    std::chrono::nanoseconds secondaryCommandExecution{};
    std::chrono::nanoseconds queueSubmission{};
    std::chrono::nanoseconds presentation{};
};
```

Timing data belongs to the frame attempt that produced it. The renderer does
not retain a `lastFrameTimings()` property whose value could be mistaken for
persistent state or read after an unrelated frame.

The phases are reported in two groups:

```text
included in active work
├── transform update
├── draw-list construction
├── draw-list validation
├── command-pool reset
├── secondary recording
├── primary recording
├── execution of the secondary
└── queue submission

reported separately as blocking context
├── frame-fence wait
├── image-acquisition wait
├── presentation-fence wait
└── presentation call
```

The distinction is about the decision being made. A monitor or compositor can
hide a reduction in CPU work behind a presentation wait. That reduction may
still provide headroom for a more complex scene, but it has not made the
currently displayed frame arrive sooner. Conversely, another recording thread
cannot shorten a fence or image-acquisition wait merely because both contribute
to elapsed frame time.

The [`RendererCpuTimings` definition][source-cpu-timings] and the
[`BenchmarkRun` report][source-benchmark-report] make both the individual
phases and the active-work sum explicit.

## Let the first baseline challenge the proposed optimization

The initial 10,000-draw reports put the same valid secondary-command structure
under two very different Vulkan implementations:

- the KosmicKrisp run used an Apple M2 Pro and the KosmicKrisp technical
  preview supplied with [LunarG Vulkan SDK 1.4.357.0][lunarg-sdk], in a Release
  build at 1600x1200 with FIFO presentation; and
- the Lavapipe run used `llvmpipe (LLVM 20.1.2, 256 bits)`, Mesa
  25.2.8-0ubuntu0.24.04.2, a Release build, an 800x600 extent, and Mailbox
  presentation.

Both discarded 16 warm-up frames and summarized 64 measured frames. The work
record retained arithmetic means for this initial comparison but not its median
and p95 rows, so the figures below establish phase placement rather than the
spread of each phase.

| Environment | Snapshot | Pool reset | Secondary record | Primary record | Execute secondary | Submission |
|---|---:|---:|---:|---:|---:|---:|
| KosmicKrisp on Apple M2 Pro | 403.556 us | 190.615 us | 590.634 us | 37.215 us | 6,984.228 us | 1,946.678 us |
| Mesa Lavapipe in Ubuntu CI | 650.730 us | 6,180.324 us | 3,435.351 us | 2.447 us | 1.400 us | 7.339 us |

The absolute rows are not comparable: the environments, presentation modes,
and extents differ. Relationships within each row are useful. KosmicKrisp
spends far more observed host time executing the secondary and submitting the
primary than recording the secondary. Lavapipe makes secondary execution almost
free but spends more time resetting the shared pool than recording commands.

Neither row supports “secondary recording is the dominant cost.” More
importantly, the fixture reveals that much of its emitted work is unnecessary.
Every draw refers to the same buffers, sampler, and image view, yet the renderer
binds them again for every cube. Dividing that work between threads would
optimize commands that should not have been recorded in the first place.

## Remove redundant commands before dividing useful work

`DrawBindingState` is local to one command buffer. It remembers the vertex and
index buffers, sampler, and image view most recently emitted. The first draw
binds everything; a later draw emits only the resource bindings that changed:

```cpp
const detail::DrawBindingChanges changes =
    bindingState.update(draw.vertexBuffer, draw.indexBuffer, draw.sampler, draw.imageView);
if (changes.geometry)
{
    commandBuffer.bindVertexBuffers(0, draw.vertexBuffer, bufferOffset);
    commandBuffer.bindIndexBuffer(draw.indexBuffer, 0, vk::IndexType::eUint32);
}
if (changes.texture)
{
    const vk::DescriptorImageInfo textureInfo{
        .sampler = draw.sampler,
        .imageView = draw.imageView,
        .imageLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
    };
    const vk::WriteDescriptorSet textureWrite{
        .dstBinding = 1,
        .descriptorCount = 1,
        .descriptorType = vk::DescriptorType::eCombinedImageSampler,
        .pImageInfo = &textureInfo,
    };
    commandBuffer.pushDescriptorSet(vk::PipelineBindPoint::eGraphics,
                                    *presentation_->pipeline().pipelineLayout(), 0,
                                    textureWrite);
}

const detail::DrawConstants constants{
    .model = item.world,
    .baseColor = draw.baseColor,
};
commandBuffer.pushConstants<detail::DrawConstants>(
    *presentation_->pipeline().pipelineLayout(), vk::ShaderStageFlagBits::eVertex, 0,
    constants);
commandBuffer.drawIndexed(draw.indexCount, 1, 0, 0, 0);
```

Push constants and indexed draws remain per draw. Input order remains
unchanged. The cache is not shared between command buffers because each one
starts with its own unknown binding state; a future second recorder must pay
its own fixed setup before it can benefit from repeated resources inside its
range.

A paired exploratory run on KosmicKrisp at 10,000 draws measured the effect
before the design was retained. Active work fell from 9,928.671 us to
5,312.563 us, a 46.5% reduction. Secondary recording fell from 588.326 us to
219.443 us, while the combined primary-recording and secondary-execution phase
fell from 6,689.827 us to 3,756.768 us. Submission fell from 2,057.743 us to
829.913 us.

The production rebaseline preserved the conclusion while showing normal
run-to-run variation. On Lavapipe, comparison with the earlier CI observation
showed secondary recording falling by 84.7% and combined-pool reset by 93.0%
at 10,000 draws. Those values come from separate hosted runs and are contextual,
not a paired performance claim. Their direction and scale show that redundant
recording can also inflate work a driver performs later when recycling the
pool.

The important result precedes any thread: remove commands without changing draw
semantics before deciding whether the remaining commands are worth dividing.
See the [command-local cache][source-binding-state] and its use in
[`recordDraws()`][source-binding-use] for the retained implementation.

## Add the missing direct-primary control

The initial baseline cannot compare secondary recording with the earlier 0.8
renderer. It was collected after the secondary structure existed, and its
coarse predecessor already measured the secondary and primary together.
Reconstructing a direct-primary result from those numbers would invent evidence.

The benchmark therefore adds a control inside the same executable:

```text
shared frame path
├── acquire and transition attachments
├── begin dynamic rendering
│
│   secondary path             direct-primary control
│   ├── record secondary       ├── record the same state and draws
│   └── execute from primary   └── directly into the primary
│
├── end rendering
├── submit
└── present
```

Both paths retain the same render objects, ordering, attachment operations,
rendering instance, and presentation. The changed command structure is the
thing being measured.

After redundant resource bindings were removed, the same-session 10,000-draw
results were:

| Environment | Secondary active work | Direct-primary active work | Difference |
|---|---:|---:|---:|
| KosmicKrisp | 6,894.338 us | 5,774.703 us | direct primary was 16.2% lower |
| Lavapipe | 1,280.163 us | 1,214.882 us | direct primary was 5.1% lower |

This does not select a second production renderer. It locates the observable
cost of the secondary structure in those sessions. KosmicKrisp moves much of
the draw-related host work into `executeCommands()` and submission; Lavapipe
does not. Later measurements can disagree without changing the control's
purpose.

The [two command paths][source-direct-control] share their prefix and suffix in
the experiment source. Keeping them in one executable avoids comparing
different builds while making the selected structure part of every report.

## Split the pools temporarily to locate reset cost

One ambiguity remains. The primary and secondary command buffers share a
command pool, so a single reset recycles allocations associated with both. Its
duration cannot be assigned to either recording context from that measurement.

The attribution experiment adds a temporary second topology:

```text
combined topology                   split topology

one command pool                    coordinator pool
├── primary command buffer          └── primary command buffer
└── secondary command buffer
                                    worker-shaped pool
                                    └── secondary command buffer

one combined reset                  two separately timed resets
```

Both modes remain single-threaded. The split does not test concurrent reset or
recording; it makes the reset owners observable. In direct-primary mode the
worker-shaped pool is still created but contains no command buffer, supplying
the cost of resetting an empty pool. A separate one-draw secondary run supplies
a fixed-cost estimate after a command buffer has been allocated and minimally
recorded.

The [temporary pool construction][source-pool-construction] chooses whether the
secondary shares the primary pool. The [timed reset path][source-pool-reset]
records coordinator and worker-shaped resets separately.

The experiment ran in one Release CI environment: Mesa Lavapipe 25.2.8 at
800x600 with Mailbox presentation, 16 warm-up frames, and 64 measured frames.
The relevant reset means were:

| Path and workload | Coordinator reset | Worker-shaped reset | What the second reset contained |
|---|---:|---:|---|
| split secondary, 1,000 draws | 1.677 us | 91.934 us | one secondary containing 1,000 draws |
| split secondary, 10,000 draws | 2.303 us | 728.253 us | one secondary containing 10,000 draws |
| split direct primary, 1,000 draws | 76.271 us | 0.138 us | an empty pool |
| split direct primary, 10,000 draws | 697.674 us | 0.201 us | an empty pool |

In the secondary path, the worker-shaped pool accounted for 98.21% of total
reset time at 1,000 draws and 99.68% at 10,000. In the direct-primary control,
the same pool topology cost almost nothing when that pool contained no recorded
commands. Reset cost follows the recorded command workload on this Lavapipe
version; it is not explained merely by creating another pool.

The split does not demonstrate that two pools are faster. The 10,000-draw
direct-primary topology comparison used a combined/split/combined `A₁/X/A₂`
order.
The split result differed from the mean control by less than the drift between
the two controls, so the cost of the topology change itself was unresolved.
Submission outliers also prevent the active-total changes from being attributed
to the pool split.

The [recorded CI run][pool-ci-run] preserves the complete reports. Once the
question was answered, the topology flag and split-pool implementation were
removed. Their source remains reachable through the release tag's ancestry;
the final release contains the ownership chosen with that evidence, not the
measurement switch.

## Correct the model without claiming a speedup

After redundant resource bindings were removed, the 10,000-draw Lavapipe
report classified 41.13% of active work as secondary recording and treated the
combined-pool reset as work that could not yet be assigned to another recorder.
The split-pool result moves the workload-dependent part of reset beside the
secondary recording that created it.

Using the one-draw reset as the fixed-cost estimate changes the provisional
model:

| 10,000-draw Lavapipe model | Work available to two recorders | Ideal two-recorder result |
|---|---:|---:|
| secondary recording only | 41.13% | `1.26x` |
| secondary recording plus its variable pool reset | 74.70% | `1.596x` |

No measured frame became `1.596x` faster. The figure is the ideal result if the
identified work could be divided perfectly between two recorders with no
coordination overhead. Later ownership changes alter the production path and
require another baseline before this model can become a gate.

What this experiment establishes is narrower and more useful:

- the snapshot, primary frame boundary, secondary execution, and submission
  remain coordinator-observed work;
- secondary recording is an obvious candidate for another recorder; and
- the reset of the pool containing that secondary's commands belongs beside
  its recording work rather than in an unexplained combined total.

Measurement has now located the candidate region. It has not made that region
safe to hand to another thread. The [recording-boundary post][recording-boundary-post]
establishes how fireEngine freezes its scene-derived input, separates recording
pools from submission ownership, and lets a recorder consume only the handles
and values required to encode commands.

## Run the surviving and experimental measurements

The released benchmark retains the deterministic workload, environment report,
phase timings, direct-primary control, and one-participant secondary path. These
commands run their final 0.9 descendants:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg -DCMAKE_BUILD_TYPE=Release
cmake --build --preset default

./build/fireEngineTutorial --benchmark 10000 --recording-threads 1
./build/fireEngineTutorial --benchmark 10000 --direct-primary
```

The temporary pool topology is absent from the final tree. Its immutable
experiment source remains in the release ancestry and can be run separately:

```shell
git checkout 1196aff
cmake --fresh --preset vcpkg -DCMAKE_BUILD_TYPE=Release
cmake --build --preset default

./build/fireEngineTutorial --benchmark 10000
./build/fireEngineTutorial --benchmark 10000 --split-command-pools
./build/fireEngineTutorial --benchmark 1 --split-command-pools

./build/fireEngineTutorial --benchmark 10000 --direct-primary
./build/fireEngineTutorial --benchmark 10000 \
  --direct-primary --split-command-pools
./build/fireEngineTutorial --benchmark 10000 --direct-primary
```

These commands reproduce the control paths, not the published timing values.
A comparison still needs the same machine, driver, build, presentation setup,
and background load, and the combined/split/combined ordering must be preserved
when applying the drift rule.

## Recommended reading

- [C++ `std::chrono::steady_clock`][reading-steady-clock] — the monotonic clock
  used to place phase boundaries around elapsed CPU work.
- [Vulkan specification: Command Buffers][reading-command-buffers] — the
  recording, pool, reset, execution, and external-synchronization rules behind
  the measured phases.
- [Real-Time Rendering][reading-real-time-rendering] — wider context for
  distinguishing CPU headroom, total frame time, and visible frame-rate change.
- [C++ Software Design][reading-cpp-design] — the design background for keeping
  diagnostic values and temporary controls from becoming permanent renderer
  state.

The [Reading page][reading-page] keeps the site-wide list in one place, and the
[Terminology page][terminology-page] collects the project-specific language
used across the measurements.

[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[secondary-command-post]: {% post_url 2026-09-12-proving-fireengines-secondary-command-path-before-measuring-it %}
[recording-boundary-post]: {% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-benchmark-run]: <https://github.com/nnewson/fireEngine-tutorial/blob/06a803a/src/app/benchmark.cpp#L116-L218>
[source-cpu-timings]: <https://github.com/nnewson/fireEngine-tutorial/blob/06a803a/include/fire_engine/render/renderer.hpp#L37-L51>
[source-benchmark-report]: <https://github.com/nnewson/fireEngine-tutorial/blob/06a803a/src/app/benchmark.cpp#L220-L331>
[source-binding-state]: <https://github.com/nnewson/fireEngine-tutorial/blob/6289a25/include/fire_engine/render/detail/draw_binding_state.hpp#L9-L68>
[source-binding-use]: <https://github.com/nnewson/fireEngine-tutorial/blob/6289a25/src/render/renderer.cpp#L811-L853>
[source-direct-control]: <https://github.com/nnewson/fireEngine-tutorial/blob/6289a25/src/render/renderer.cpp#L597-L664>
[source-pool-construction]: <https://github.com/nnewson/fireEngine-tutorial/blob/1196aff/src/render/frame_in_flight.cpp#L14-L60>
[source-pool-reset]: <https://github.com/nnewson/fireEngine-tutorial/blob/1196aff/src/render/renderer.cpp#L485-L513>
[pool-ci-run]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33124389848>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[lunarg-sdk]: <https://vulkan.lunarg.com/sdk/home>
