---
title: Mapping fireEngine's path to multithreaded rendering
date: 2026-09-04 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, performance, benchmarking, vulkan, cpp]
description: >-
  A retrospective map of the questions, controls, measurements, and limits
  that turned parallel command recording into a conditional policy in
  fireEngine 0.9.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

Release 0.8 gave fireEngine a complete path from an animated glTF file to a
presented frame. Its ownership boundaries were visible in the facade and
executable through the scenario suite, but the work behind each frame remained
serial. Image uploads borrowed the sole frame slot, one submission could be in
flight, and one CPU thread recorded every draw.

The tempting 0.9 story is therefore simple: add another thread and make command
recording faster. The released result is more conditional. Two recording
threads helped both measured implementations at 10,000 synthetic draws, but at
1,000 draws the implementations disagreed: one improved while the other became
slower. Several experiments were rejected rather than becoming part of the
release. Replacing recursive transform traversal with a flat forward pass was
slower at 10,000 draws, while the first two-thread design did not improve both
selected workloads enough to keep.

This cannot honestly be a forward-looking plan in the style of the 0.7 and 0.8
introductions. Version 0.9 is already tagged, and its interesting decisions
depend on evidence that was not known before the work. This post is instead a
map of the questions the release asked, the methods that made their answers
credible, and the limits those answers retain.

Its central claim is narrower than “threads are faster”: explicit ownership and
immutable input made parallel recording safe to test, while measurement made it
a workload-dependent policy rather than a universal architectural choice.

> Starting point: [fireEngine 0.8][release-0-8]
>
> Released source: [fireEngine 0.9][release-0-9]
>
> Released architecture: [fireEngine 0.9 architecture][architecture-0-9]
>
> The [closing 0.8 post][closing-0-8-post] establishes the serial ownership and
> validation boundaries placed under pressure here. The detailed 0.9 posts
> will follow the methods used to answer these questions; their exact cuts can
> change without rewriting the evidence as a predetermined sequence.
{: .prompt-info }

## Introducing the measurement vocabulary

The questions below are answered by measurement, so the words describing how a
number was obtained matter as much as the number:

- **Lavapipe** is Mesa's CPU implementation of Vulkan. It renders without a GPU,
  which is what lets continuous integration run the real device path on a
  machine that has no graphics hardware. Its absolute timings are not
  comparable with a hardware driver;
- a **decision-bearing implementation** is one declared in advance as eligible
  to affect the decision to retain or reject a change;
- an **A₁/X/A₂ bracketed control comparison** runs the control as `A₁`, the
  candidate as `X`, then the same control again as `A₂`, all using the same
  executable in one session. The baseline is `C = (A₁ + A₂) / 2`;
- **control drift** is the gap between those two controls, `abs(A₂ - A₁)`. It is
  the machine's own variation between two runs of identical code, and a
  candidate closer to the baseline than that is **unresolved within drift** —
  it supports no directional claim;
- **active work** is the host work a frame performs as the coordinating thread
  observes it, excluding time blocked waiting for presentation, so a slow
  display cannot disguise a change in CPU cost; and
- **materialisation** is the share of a predicted improvement that measurement
  actually delivers. A model predicting a 40% reduction that measures 20% has
  materialised half of it.

A **registered** rule is one written down with its threshold before the
measurement that tests it, so a disappointing result cannot be rescued by
moving the bar afterwards.

Three environments contribute different kinds of evidence:

| Environment | Classification | Role in the decision |
|---|---|---|
| Ubuntu GitHub Actions with Mesa Lavapipe 25.2.8 | software Vulkan implementation | decision-bearing continuous measurement |
| Intel i5-8300H and GeForce GTX 1050 with NVIDIA 580.173.02 | hardware Vulkan implementation | decision-bearing hardware measurement |
| Apple M2 Pro with the KosmicKrisp technical preview | preview Vulkan implementation | correctness and longitudinal observation only |

KosmicKrisp can expose a portability or validation problem, but its preview
measurements do not choose the released worker policy. That distinction is
registered before looking at a result, just like the numerical gates.

The [Terminology page][terminology-page] collects these definitions with the
engine and testing vocabulary used across the fireEngine posts.

## What pressure 0.9 responds to

The 0.8 renderer already separates application descriptions, prepared
dependencies, compiled Vulkan resources, current scene transforms, and
replaceable presentation state. Three remaining seams make concurrency a useful
test of that architecture:

- resource uploads borrow the command pool and fence used for the only frame;
- submission ownership and command-recording ownership are combined; and
- command recording consumes scene-derived data without a narrow input type
  containing only the handles and values another thread needs to record
  commands.

The goal is not merely to remove those seams. It is to make mutation and
ownership phases explicit enough that adding a recording participant changes
scheduling without reopening resource ownership.

That requires keeping four independent concurrency counts separate:

| Count | What it describes | Released 0.9 result |
|---|---|---|
| application frame states | scene and animation states being updated concurrently | one |
| Vulkan frame slots | submitted frames whose GPU work may remain outstanding | two |
| recording participants per frame | CPU threads recording command buffers for the same frame | one or two, selected by draw count |
| swapchain images | presentable images managed by the Vulkan implementation | driver-selected |

The application advances one scene and animation state at a time. Two Vulkan
frame slots let the CPU prepare a later submission while the GPU completes an
earlier one. Independently, two recording participants may divide the command
recording for the same application frame. The swapchain image count and the
image index returned by acquisition choose which presentable image is used;
they do not choose either of those concurrency counts.

In this post, the **coordinator** is the main rendering thread. It owns the
primary command buffer, queue submission, and presentation. A primary command
buffer begins rendering and executes secondary command buffers. The
coordinator and an optional **helper** may each record a different range of
draws into one of those secondary buffers. Both threads are recording
**participants**, but the helper cannot submit or present the frame.

A **frozen frame** means that scene mutation, transform resolution, and
resource lookup have finished. Both participants receive the resulting
immutable `RecordingInput`; neither reads or modifies the live scene while
recording.

## What had to be true before a measurement meant anything

The completed measurement and attribution work is covered in the
[CPU-measurement post][cpu-measurement-post].

A total frame duration cannot show how much CPU time belongs to command
recording, or whether enough of that work can run concurrently to outweigh the
cost of involving another thread.
Presentation pacing may hide an active-work reduction, and a driver may perform
secondary-command work during recording, execution, submission, or command-pool
reset. Adding a thread before separating those phases would attach a speedup
number to an unknown mixture of work.

The permanent [`--benchmark` harness][source-benchmark] therefore creates a
deterministic scene of repeated cube instances. Each Release run discards 16
warm-up frames and measures 64 cleanly presented frames with a fixed animation
step. The representative workloads are 1,000 and 10,000 draws. Out-of-date and
suboptimal attempts do not enter the sample set.

The report separates transform resolution, draw-list construction,
recording-input compilation, frame-uniform update, command-pool resets, primary
and secondary recording, secondary execution, submission, and blocking waits.
“Active work” excludes presentation blocking, so the worker decision is based
on CPU work it could actually shorten rather than on time spent waiting for the
presentation system or the monitor.

Each candidate uses the `A₁/X/A₂` sequence defined above. The difference between
`A₁` and `A₂` is its drift allowance; `X` supports a directional claim only when
its distance from their mean exceeds that allowance. Every reported result
records its hardware, driver, build configuration, workload, run count, and
timing boundaries. Ratios are compared within one controlled acquisition; raw
timings are not compared across machines.

One more control records all draws directly into the primary command buffer.
Comparing it with one-participant secondary recording helps locate costs
introduced by the secondary-command structure. Both modes run through the same
executable and surrounding frame path, avoiding a comparison between different
builds. The `--direct-primary` flag exists only for measurement. In normal
automatic selection, the released renderer chooses one recording participant
below 10,000 draws and two from 10,000 draws upward; it does not select the
direct-primary path.

## Can secondary recording work before it can be faster?

The completed functional investigation is covered in the
[secondary-command post][secondary-command-post].

The first uncertainty is functional. Can a primary command buffer begin dynamic
rendering, execute inherited secondary command buffers with the correct colour
and depth formats, and then end and present cleanly on the available
implementations?

A deliberately small spike answered yes under standard and synchronization
validation. KosmicKrisp on Apple Silicon and Mesa Lavapipe both accepted the
command structure. That established the Vulkan contract but not its cost.

The distinction mattered immediately. KosmicKrisp spent substantial host time
executing the recorded secondary from the primary, while Lavapipe made that
execution nearly free relative to recording. Host timings cannot reveal either
driver's internal implementation, but the opposite phase shapes are enough to
reject a portable assumption that secondary execution is always cheap—or
always expensive.

This question therefore needs a validation method, not a speedup graph. Prove
that the structure is legal first; preserve different driver observations; then
measure the production form after its ownership is correct.

## Where does worker-eligible CPU time actually live?

The phase findings and temporary pool experiment are covered in the
[CPU-measurement post][cpu-measurement-post].

The phase harness answers several questions with one method:

- How much work is serial snapshot construction rather than recording?
- How much redundant binding work should disappear before any work is divided?
- Does a driver place secondary-command cost in recording, execution, or
  submission?
- Is command-pool reset mostly a fixed cost of resetting a pool, or does it grow
  with the commands recorded into that pool?
- Does the `eTransient` command-pool hint change that reset cost measurably?

Command-buffer-local binding caches were the first answer. They preserve draw
order and every draw, but rebind vertex and index buffers only when their
handles change and push a sampled-image descriptor only when its sampler or
image view changes. That reduced real work before concurrency and prevented the
worker prediction from counting redundant commands as an opportunity.

Ownership then corrected the measurement model. At this stage the primary and
secondary command buffers shared a pool, so the combined reset timing could not
show which recording context was responsible for the cost. A temporary
split-pool control tested that attribution directly and showed that reset cost
belongs with the context that records from the pool. No draw became faster, but
work previously classified as coordinator-only could now be assigned to a
recording participant.

The result was not portable in magnitude. At 10,000 draws, worker-pool reset was
54.02% of active work on Lavapipe and 0.25% on the NVIDIA driver. The same
architecture exposed two different driver compositions. A registered
`A₁/X/A₂` experiment found no measurable reset change from `eTransient`; the
hint stayed because it describes the short-lived pool accurately, while its
runtime switch and measurement-only branches disappeared.

The direct-primary control resisted a universal conclusion too. Its direction
changed across environments and, on NVIDIA at 10,000 draws, across sessions.
That makes “which command structure is faster?” a question needing its own
paired measurement, not an answer 0.9 can infer from isolated runs.

## Which boundaries can be justified without timing?

The phase measurements identify command-pool reset and secondary recording as
the candidate region for parallel recording. That creates a different kind of
question: can exactly that region be handed to another participant without
also handing it mutable resource ownership, submission authority, or CPU data
that expires too early? Timings cannot answer that.

The application also builds a `SceneDrawList` in a reusable arena before it
enters the renderer. The returned value is an immutable span, not an owning
container. Can that arena-backed view expire after CPU recording, or must it
survive until the GPU finishes?

The answer follows from what Vulkan retains. Recording consumes draw items,
transforms, and push-constant values to encode commands. The GPU later uses
buffers, image views, and samplers retained by their separate compiled-resource
owners; it does not dereference the CPU draw-list span. The arena may therefore
be reused after synchronous recording completes.

Immutability alone is not enough. A `const` Vulkan-Hpp RAII wrapper may still
offer operations that affect GPU state. The
[`RecordingInput` boundary][source-recording-input] instead resolves the frozen
scene view into packets containing plain, non-owning Vulkan handles and deletes
copy and move construction. Only its compiler can create it. The type removes
resource mutation, submission, presentation, and destruction authority from a
recording participant instead of relying on a comment asking the thread to be
careful.

Each recording context therefore owns and resets the command pool backing its
secondary command buffer. The helper can prepare its own recording resources,
while the coordinator retains sole control of the primary command buffer,
queue submission, and presentation.

That is the measurement-driven half of the boundary work: isolate the region
the phase model says could run concurrently, then give it only the data and
authority it needs.

The other half pays debts already named by the
[0.8 architecture][architecture-0-8]. Setup uploads borrowed the only frame's
command pool and fence, and asynchronous upload ownership and more than one
frame in flight were deliberate omissions from that release. They would need
attention regardless of where the phase timings landed.

Resource compilation therefore owns its setup command pool and fence rather
than borrowing a frame slot. Two `FrameSlot` values own frame-uniform storage,
image-available semaphores, submission fences, and pending-work state;
presentation owns two depth attachments indexed by those slots.

These inherited changes are still load-bearing for the worker experiment. They
alter the production path whose one-participant timings supply the gate's
denominator. The earlier baseline cannot simply flow around them; once both
branches are complete, the resulting path must be measured again.

This family of questions is answered by lifetime analysis, capability audits,
focused tests, validation, and temporary fault injection. Measuring it would
not make an unsafe lifetime safe, but changing it determines which performance
measurement remains valid. The method has to match the uncertainty.

## Does a second participant earn its overhead?

Both branches now converge on one measurement boundary:

```text
phase attribution
        |
        v
freeze recording input --------+
                               |
0.8 ownership debts            +--> rebaseline --> register gate --> add helper
        |                      |
        v                      |
change production path --------+
```

The debt branch makes the rebaseline necessary rather than merely tidy. Two
frame slots, a dedicated upload context, and separately owned recording pools
change the production path being measured. Registering a gate against the
earlier one-participant denominator would ask new code to satisfy a prediction
about code that no longer exists.

Only after that production path was remeasured could the share of active work
eligible for parallel recording predict an ideal two-participant result. The
release registered two different decisions before adding the helper:

1. attempt parallel recording only if a perfect two-way split of the eligible
   work predicted at least a `1.15x` ideal result; and
2. retain it only if measurement delivered at least half of the predicted
   reduction at both workloads on a decision-bearing implementation.

The first rule avoids adding thread coordination when even a perfect split
predicts less than a 15% improvement. The second requires a real implementation
to deliver a meaningful share of that prediction at both selected workloads,
rather than retaining the mechanism for one favourable result. The detailed
posts will show how the eligible share and thresholds were calculated and how
the gate was exercised.

The initial persistent [`SecondaryRecordingWorker`][source-worker] missed that
retention rule on both Vulkan implementations. It improved the 10,000-draw
result on each, but neither Lavapipe nor NVIDIA passed at both workloads.
Diagnostics showed that the helper consistently finished last and that the
coordinator resumed late after blocking for its completion.

The single pre-registered remediation changed the coordinator's completion
wait. It polls for at most 50 microseconds after finishing its own recording
work; if the helper has still not finished, it falls back to the existing
blocking atomic wait. The helper continues to block while waiting for work
between frames, and no other polling durations or tuning changes were tried.
After that single allowed change, the full `A₁/X/A₂` measurements were repeated.

Each multiplier below is the mean one-participant active-work time from `A₁`
and `A₂`, divided by the two-participant time from `X`. A value above `1.0x` is
faster; one below `1.0x` is slower.

| Implementation | 1,000 draws | 10,000 draws |
|---|---:|---:|
| Mesa Lavapipe | `1.374x` | `1.700x` |
| NVIDIA 580.173.02 | `0.912x` | `1.209x` |

The Lavapipe measurements used a Release build at 800x600 with Mailbox
presentation, 16 warm-up frames, and 64 measured frames per arm. Its first
1,000-draw `A₁/X/A₂` acquisition after the remediation provided no measurement
because its two one-participant controls differed by 57.12%. Before another
result was known, the experiment record allowed exactly one replacement
acquisition on the same commit and configuration. That replacement supplied
the `1.374x` result above; no further retries were allowed.

The NVIDIA measurements used an Intel i5-8300H and GeForce GTX 1050, driver
580.173.02, Release, 800x600 FIFO presentation, with the CPU governor fixed to
performance on AC power. The same `A₁/X/A₂` ordering and frame counts applied.
Every reported implementation-and-workload result differed from its
one-participant baseline by more than the drift between its two controls.

The disagreement is the result, not noise to average away. Parallel recording
helped both implementations at 10,000 draws and ran at `0.912x`, or 9.7%
slower, on NVIDIA at 1,000. Automatic mode therefore selects two participants
only from 10,000 total draws: at least 5,000 draws per participant. That is the
measured boundary where both implementations benefited, not an estimate of the
unmeasured crossover.

Participant durations are never added to claim a speedup because their work
overlaps. Active work uses the coordinator-observed recording region, including
dispatch and join, so the cost of threading remains inside the comparison.

## What the evidence does not establish

The released policy is deliberately narrower than the experiment that produced
it.

| Claim 0.9 does not make | Evidence limit |
|---|---|
| parallel recording is universally faster | NVIDIA regressed at 1,000 draws |
| the crossover occurs at 10,000 draws | only 1,000 and 10,000 were decision workloads |
| the result represents arbitrary scenes | the synthetic workload repeats one cube and is unusually easy to divide evenly |
| active-work speedup is the same as frame-rate improvement | presentation waits and monitor or compositor pacing are reported separately and excluded from the worker gate |
| more workers will continue scaling | the release measures only a coordinator and one helper |
| every Vulkan implementation places cost in the same phase | Lavapipe and NVIDIA disagree sharply about command-pool reset |

The portion of active work that recording helpers cannot shorten matters more
as their number grows. On NVIDIA at 10,000 draws, more than half of active work
is the immutable recording-input snapshot phase. Even with unlimited,
cost-free recording participants, that measured non-recording work limits the
theoretical active-work speedup to about `1.744x`.

The coordinator and helper run concurrently, so their CPU durations can add up
to more than the one-participant duration even while the elapsed recording
phase becomes shorter. The optimization targets elapsed time on the critical
path, not the total amount of CPU work performed. Version 0.9 does not diagnose
how much of that additional work comes from driver contention, cache behaviour,
CPU frequency, or command allocation; it records those candidates without
selecting the most convenient explanation.

KosmicKrisp remains valuable correctness and longitudinal evidence, but the
measured technical preview did not choose the worker policy. Two
decision-bearing implementations are enough to expose disagreement, not enough
to generalise across Vulkan drivers. A third Mesa hardware result would help
separate software-rasterizer behaviour from shared driver lineage.

## Run the released paths

The Debug suite checks both recording paths, automatic selection on either side
of the threshold, forced split fallback, mixed-resource binding changes,
standard validation, and synchronization validation:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default
```

That runs all 77 registered tests; it is a correctness gate rather than a
performance measurement. Reconfigure the same tree as Release before collecting
timings, then repeat the one/two/one control order at each workload:

```shell
cmake --preset vcpkg -DCMAKE_BUILD_TYPE=Release
cmake --build --preset default

./build/fireEngineTutorial --benchmark 1000 --recording-threads 1
./build/fireEngineTutorial --benchmark 1000 --recording-threads 2
./build/fireEngineTutorial --benchmark 1000 --recording-threads 1

./build/fireEngineTutorial --benchmark 10000 --recording-threads 1
./build/fireEngineTutorial --benchmark 10000 --recording-threads 2
./build/fireEngineTutorial --benchmark 10000 --recording-threads 1

./build/fireEngineTutorial --benchmark 10000 --direct-primary
```

Those commands reproduce the method, not the published numbers. A comparison
needs the same machine, driver, presentation setup, build, and background load.
The executable reports that environment with its phases. The ordinary
`--benchmark 10000` form exercises the automatic policy. The final command
records every draw directly into the primary command buffer, providing a
diagnostic comparison with the normal secondary-command path.

## Where this leaves the architecture

The [0.9 architecture page][architecture-0-9] describes only the state that
survived: insertion-time scene identity, compiler-owned uploads, arena-backed
draw views, immutable recording input, two frame slots, independent recording
contexts, and one persistent helper behind a workload threshold. Measurement
switches and rejected alternatives are absent because they are evidence about
that architecture rather than parts of it.

```text
serial mutation
      |
      v
freeze scene view -> compile immutable recording input
                              |
                 +------------+------------+
                 v                         v
             coordinator                helper
                 +------------+------------+
                              |
                              v
                    submit and present serially
```

That final thread is the smaller half of the release. The durable result is the
sequence that made it safe to introduce and possible to reject: owners were
separated, inputs were frozen, phases were measured, and a decision rule existed
before the answer arrived. Version 0.9 keeps parallel recording where the
evidence supports it and keeps the one-participant path where it does not.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan-guide] — the command-buffer,
  synchronization, and dynamic-rendering background behind the recording
  structure.
- [C++ `std::chrono::steady_clock`][reading-steady-clock] — the monotonic clock
  used to place comparable phase boundaries around CPU work.
- [C++ Software Design][reading-cpp-design] — a broader treatment of cohesive
  ownership and restricted interfaces, which matter here before concurrency
  begins.
- [Real-Time Rendering][reading-real-time-rendering] — the wider rendering and
  performance context for distinguishing CPU headroom from visible frame-rate
  change.

The [Reading page][reading-page] keeps the site-wide list in one place, and the [Terminology page][terminology-page] collects the definitions above.

[release-0-8]: {{ page.previous_release_url }}
[release-0-9]: {{ page.release_url }}
[architecture-0-8]: {% link _architecture/0.8.md %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[closing-0-8-post]: {% post_url 2026-09-02-closing-fireengine-08-with-focused-ownership-and-executable-scenarios %}
[secondary-command-post]: {% post_url 2026-09-12-proving-fireengines-secondary-command-path-before-measuring-it %}
[cpu-measurement-post]: {% post_url 2026-09-13-measuring-fireengines-cpu-work-before-adding-another-thread %}
[source-benchmark]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/app/benchmark.cpp>
[source-recording-input]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/recording_input.hpp>
[source-worker]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/secondary_recording_worker.hpp>
[reading-vulkan-guide]: <https://www.vulkanprogrammingguide.com>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-page]: {% link _tabs/reading.md %}
[terminology-page]: {% link _tabs/terminology.md %}
