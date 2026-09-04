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
flight, and one CPU participant recorded every draw.

The tempting 0.9 story is therefore simple: add another thread and make command
recording faster. The released result is more conditional. Two recording
participants helped both measured implementations at 10,000 synthetic draws,
but the same split ran at `0.912x`, or 9.7% slower, at 1,000 draws on the
NVIDIA system. Several temporary controls answered their questions and were
removed; a flat transform
pass failed its retention rule; and the first worker measurement failed the
registered release gate.

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

## What pressure 0.9 responds to

The 0.8 renderer already separates application descriptions, prepared
dependencies, compiled Vulkan resources, current scene transforms, and
replaceable presentation state. Three remaining seams make concurrency a useful
test of that architecture:

- resource uploads borrow the command pool and fence used for the only frame;
- submission ownership and command-recording ownership are combined; and
- command recording reads a scene-derived list without a type that limits a
  worker to recording alone.

The goal is not merely to remove those seams. It is to make mutation and
ownership phases explicit enough that adding a recording participant changes
scheduling without reopening resource ownership.

That requires keeping four different kinds of depth separate:

| Kind of depth | Released 0.9 result |
|---|---|
| CPU frames being prepared concurrently | one |
| submitted Vulkan frames that may remain outstanding | two |
| CPU participants recording one frame | one or two, selected by workload |
| images retained for presentation | driver-selected |

Two Vulkan frame slots do not mean two application frames are being mutated at
once, and a three-image swapchain does not choose either number. The application
still mutates, freezes, records, submits, and presents one frame in order. The
second submission slot permits CPU/GPU overlap; the second recording participant
may only read one already-frozen frame.

## What had to be true before a measurement meant anything

A coarse frame duration cannot tell us whether command recording is divisible.
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
on CPU work it could actually shorten rather than on refresh pacing.

Comparisons use a one-participant A, two-participant X, one-participant B
sequence in the same binary and environment. The difference between A and B is
the control drift against which X must resolve. Hardware, driver, build
configuration, workload, run count, and timing boundaries travel with every
result; absolute values do not travel between machines.

One more control records all draws directly into the primary command buffer.
It attributes costs surrounding secondary commands, but it is not a competing
production renderer. Keeping the control in the same binary makes disagreement
observable without making a benchmark switch part of the public architecture.

## Can secondary recording work before it can be faster?

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

## Where does the worker-divisible CPU time actually live?

The phase harness answers several questions with one method:

- How much work is serial snapshot construction rather than recording?
- How much redundant binding work should disappear before any work is divided?
- Does a driver place secondary-command cost in recording, execution, or
  submission?
- Does command-pool reset follow the pool's identity or the commands recorded
  into it?
- Does the `eTransient` command-pool hint change that reset cost measurably?

Command-buffer-local binding caches were the first answer. They preserve draw
order and every draw, but rebind vertex and index buffers only when their
handles change and push a sampled-image descriptor only when its sampler or
image view changes. That reduced real work before concurrency and prevented the
worker prediction from counting redundant commands as an opportunity.

Ownership then corrected the measurement model. A shared command pool made its
reset impossible to assign honestly to either a coordinator or a future worker.
A temporary split showed that reset cost belongs with the context that records
that pool. No draw became faster, but work previously classified as serial
became attributable to a recording participant.

The result was not portable in magnitude. At 10,000 draws, worker-pool reset was
54.02% of active work on Lavapipe and 0.25% on the NVIDIA driver. The same
architecture exposed two different driver compositions. A registered A/X/B
experiment found no measurable reset change from `eTransient`; the hint stayed
because it describes the short-lived pool accurately, while its runtime switch
and measurement-only branches disappeared.

The direct-primary control resisted a universal conclusion too. Its direction
changed across environments and, on NVIDIA at 10,000 draws, across sessions.
That makes “which command structure is faster?” a question needing its own
paired measurement, not an answer 0.9 can infer from isolated runs.

## Which boundaries can be justified without timing?

The phase measurements identify command-pool reset and secondary recording as
the candidate divisible region. That creates a different kind of question: can
exactly that region be handed to another participant without also handing it
mutable resource ownership, submission authority, or CPU data that expires too
early? Timings cannot answer that.

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

The same measured region gives each recording context ownership of the command
pool it resets. A participant can therefore prepare its own pool without
receiving submission authority or asking the coordinator to perform worker
setup serially.

That is the measurement-driven half of the boundary work: isolate the region
the phase model says may divide, then give it only the data and authority it
needs.

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

Only after that production path was remeasured could its serial fraction
predict an ideal two-participant ceiling. The release registered two different
decisions before adding the helper:

1. attempt parallel recording only if the divisible share implied at least a
   `1.15x` ideal two-participant result; and
2. retain it only if measured work materialised at least half of the predicted
   reduction at both workloads on a decision-bearing implementation.

The first implementation of the persistent
[`SecondaryRecordingWorker`][source-worker] did not clear that retention rule.
Both implementations improved at 10,000 draws, but neither passed at both
workloads. The diagnostics showed the helper finishing last and the coordinator
resuming late from its completion wait.

One pre-registered remediation allowed the coordinator to poll completion for
at most 50 microseconds before falling back to an atomic wait. It did not spin
while the helper waited between frames, sweep several durations, or permit
further tuning if the gate still failed. The repeat produced the released
result:

| Implementation | 1,000 draws | 10,000 draws |
|---|---:|---:|
| Mesa Lavapipe | `1.374x` | `1.700x` |
| NVIDIA 580.173.02 | `0.912x` | `1.209x` |

The Lavapipe results came from the Ubuntu GitHub Actions llvmpipe environment,
Mesa 25.2.8, Release, 800x600 Mailbox presentation, with 16 warm-up and 64
measured frames per arm. Its initial 1,000-draw remediation acquisition was
discarded under the registered drift rule; one permitted same-commit
replacement acquisition supplied the resolved value above.

The NVIDIA measurements used an Intel i5-8300H and GeForce GTX 1050, driver
580.173.02, Release, 800x600 FIFO presentation, with the CPU governor fixed to
performance on AC power. The same A/X/B ordering and frame counts applied.
Every retained cell resolved against the difference between its two
one-participant controls.

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
| active-work speedup is the same as frame-rate improvement | presentation waits and refresh pacing are contextual rather than part of the worker gate |
| more workers will continue scaling | the release measures only a coordinator and one helper |
| every Vulkan implementation places cost in the same phase | Lavapipe and NVIDIA disagree sharply about command-pool reset |

The remaining serial fraction matters more as worker count grows. On NVIDIA at
10,000 draws, more than half of active work is the immutable snapshot phase. It
caps the measured unlimited-worker ideal at about `1.744x`, however cheaply
additional command recording could be divided.

Aggregate CPU work may also rise while elapsed critical-path time falls. That
is a normal trade in parallel work, but 0.9 does not diagnose how much of its
increase comes from driver contention, cache behaviour, CPU frequency, or
command allocation. The release records those candidates without selecting the
most convenient explanation.

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
```

Those commands reproduce the method, not the published numbers. A comparison
needs the same machine, driver, presentation setup, build, and background load.
The executable reports that environment with its phases. The ordinary
`--benchmark 10000` form exercises the automatic policy; `--direct-primary`
selects the attribution control.

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

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-8]: {{ page.previous_release_url }}
[release-0-9]: {{ page.release_url }}
[architecture-0-8]: {% link _architecture/0.8.md %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[closing-0-8-post]: {% post_url 2026-09-02-closing-fireengine-08-with-focused-ownership-and-executable-scenarios %}
[source-benchmark]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/app/benchmark.cpp>
[source-recording-input]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/recording_input.hpp>
[source-worker]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/secondary_recording_worker.hpp>
[reading-vulkan-guide]: <https://www.vulkanprogrammingguide.com>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-page]: {% link _tabs/reading.md %}
