---
title: "Rebaselining fireEngine before adding another recording thread"
date: 2026-09-17 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, performance, benchmarking, vulkan, cpp]
description: >-
  Remeasure fireEngine's final one-participant path and decide whether enough
  eligible work remains to justify trying a second recording participant.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

The [recording-boundary post][recording-boundary-post] leaves fireEngine with a
safe place for another CPU thread to work. Command recording consumes immutable
packets, each recording context owns its command pool, and only the coordinator
can submit or present the frame. Safety is necessary, but it is not a
performance result.

The ownership work also invalidates the earlier baseline. Recording-input
compilation adds serial work. Two frame slots alter how CPU work overlaps the
software renderer. Separating upload, submission, and recording ownership
changes the path whose cost a second participant is meant to reduce. Carrying
the earlier prediction forward would compare a future worker with a renderer
that no longer exists.

Release 0.9 therefore remeasures the complete one-participant path before
starting its helper experiment. The result clears a registered `1.15x` ideal
gate at both 1,000 and 10,000 draws on Mesa Lavapipe and an NVIDIA hardware
driver. That grants permission to try another participant. It does not predict
that the real implementation will retain all of that ideal gain—or even run
faster after dispatch and synchronization are included.

This post covers that eligibility decision from the [0.9 release map][map-post].
The worker experiment remains a separate question because it needs different
evidence: measured one-participant versus two-participant results rather than a
model of a perfect split.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Ownership prerequisite: [the recording-boundary post][recording-boundary-post]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
>
> Absolute timings below belong to the named environment and acquisition. They
> are not compared across machines or unrelated sessions.
{: .prompt-info }

## Introducing the decision vocabulary

Four quantities describe the one-participant path:

- `T1` is the coordinator-observed **active work** for one participant. It
  excludes frame, acquisition, and presentation waits that recording cannot
  shorten;
- `W` is the reset time for the participant's command pool;
- `R` is that participant's secondary-command recording time; and
- `F` estimates the fixed part of resetting its pool. `F0` comes from an empty
  worker pool in the direct-primary control, while `F1` comes from a minimally
  populated one-draw secondary run.

The estimated share available to two participants is:

```text
    W - F + R
p = ---------
        T1
```

Subtracting `F` keeps the fixed reset cost out of the divisible share. Using
both `F0` and `F1` tests whether uncertainty at that boundary can change the
decision.

An **ideal gate** asks whether the measured one-participant work contains enough
eligible work to make an experiment plausible. It assumes the eligible share
divides perfectly, with no dispatch, synchronization, duplicated setup, or
load imbalance:

```text
ideal two-participant speedup = 1 / (1 - p / 2)
```

The registered threshold is `1.15x`. Solving the formula in reverse means at
least 26.09% of active work must be eligible. Below that point, even a perfect
split predicts less than a 15% improvement, so introducing another thread would
be difficult to justify.

This is an **attempt gate**, not a retention gate. A later measurement must
still show that the real worker delivers at least half of its predicted
reduction at both selected workloads on a decision-bearing implementation.

The [Terminology page][terminology-page] collects active work, decision-bearing
implementations, registered decision rules, and the other measurement language
used across the 0.9 series.

## Audit the path that the prediction describes

The one-participant secondary path was assembled across the earlier ownership
work rather than introduced by one final change. Before treating its timings as
the denominator, the audit asks whether the current structure matches the
model:

| Model boundary | Production structure |
|---|---|
| serial frame boundary | the primary owns attachment transitions and dynamic-rendering begin/end |
| participant-local work | the secondary establishes its own geometry state and records resolved packets |
| participant-local reset | the secondary recording context owns and resets its own command pool |
| immutable input | recording reads the compiled `RecordingInput`, not the live scene |
| serial completion | the primary executes the finished secondary before submission |

Those properties all hold. The primary still encloses secondary execution
inside one rendering instance, and the participant's reset remains the first
operation in its recording region. Preparation replacement, presentation
recreation, the direct-primary control, and synchronization validation continue
to exercise the same ownership shape. See the [one-participant recording
path][source-one-participant-path] and the [recording-context
owner][source-recording-context].

The audit found no defect and changed no measurement boundary. An identical
binary did not need to be rebuilt and rerun merely to give the checkpoint a
new name. The already completed [one-participant CI matrix][baseline-ci] was
therefore eligible to supply `T1`, `W`, and `R`.

That restraint matters. A rebaseline is required after the measured program
changes; rerunning unchanged code until a more attractive sample appears is not
a rebaseline.

## Measure the final one-participant denominator

The decision-bearing Linux job used Mesa Lavapipe 25.2.8 at 800x600 with
Mailbox presentation, a Release build, 16 warm-up frames, and 64 measured
frames. It reported the complete active-work denominator rather than only the
two phases expected to divide:

| Phase | 1,000 draws | 10,000 draws |
|---|---:|---:|
| transform update | 32.209 us | 295.470 us |
| draw-list build | 11.724 us | 164.234 us |
| recording-input build | 14.547 us | 127.978 us |
| frame-uniform update | 1.898 us | 2.724 us |
| coordinator command-pool reset | 4.851 us | 6.196 us |
| participant command-pool reset `W` | 236.130 us | 1,884.305 us |
| secondary command recording `R` | 161.728 us | 996.901 us |
| primary command recording | 2.916 us | 2.680 us |
| secondary command execution | 0.398 us | 0.514 us |
| queue submission | 8.428 us | 7.143 us |
| **active work `T1`** | **474.829 us** | **3,488.145 us** |

The benchmark keeps waits visible but outside `T1`, and reports pool reset and
secondary recording separately. That is what lets the decision model select a
specific region instead of calling all CPU frame time parallel. See the
[phase report and active-work calculation][source-benchmark-report].

The next table is not an `A₁/X/A₂` comparison. It is an absolute description of
one production path, so it has no candidate arm and no drift classification.
The values are predictions calculated from that path, not measured speedups.

The one-draw run supplied `F1 = 2.586 us`. The direct-primary controls supplied
`F0 = 0.293 us` at 1,000 draws and `0.343 us` at 10,000. Both endpoints produce
the same decision:

| Draws | Fixed estimate | Eligible share `p` | Ideal two-participant result |
|---:|---|---:|---:|
| 1,000 | `F1` | 83.25% | `1.713x` |
| 1,000 | `F0` | 83.73% | `1.720x` |
| 10,000 | `F1` | 82.53% | `1.703x` |
| 10,000 | `F0` | 82.59% | `1.703x` |

Changing the fixed-cost estimate moves the ideal result by only `0.007x` at
1,000 draws and `0.001x` at 10,000. The result is insensitive to that bracket,
so the more conservative `F1` estimate can be used from here.

The supported conclusion is correspondingly narrow: the eligible share would
have to fall from roughly 83% to below 26.09% to reverse the attempt decision.

## Challenge the assumption carrying the prediction

The large Lavapipe margin initially looks reassuring, but its composition makes
it suspect. At 10,000 draws, variable participant-pool reset contributes
`1,881.719 us`, while secondary recording contributes `996.901 us`. Reset
provides 65.4% of the predicted reduction and consumes 54.0% of all active
work.

The earlier attribution experiment established that reset cost follows the
commands recorded into the pool. It did not establish that the variable part
will halve when two pools reset concurrently. Treating that assumption as a
fact would let an unmeasured driver behaviour carry most of the gate.

The prediction is therefore run in two forms:

```text
optimistic:  variable pool reset + secondary recording divide
pessimistic: secondary recording divides; every reset remains serial
```

| Draws | Optimistic result | Pessimistic result | Registered gate |
|---:|---:|---:|---:|
| 1,000 | `1.713x` | `1.205x` | `1.15x` |
| 10,000 | `1.703x` | `1.167x` | `1.15x` |

Both workloads still qualify without any reset benefit. That permits the worker
experiment while leaving reset divisibility open for the experiment itself to
measure. The 10,000-draw pessimistic margin is only `0.017x`, about 1.5%
relative to the gate, so it should not be described as comfortable.

This is also where the measurement contract had to grow. A two-participant run
must later record each participant's reset interval and the complete region from
the earliest reset start to the latest recording completion. Reset and
recording can overlap, so their durations cannot simply be added to manufacture
a critical path.

## Check whether the command-pool hint created the opportunity

One configuration detail could still make the Lavapipe result artificial.
Per-frame recording pools hold one-time command buffers and are reset before
reuse, but they had not declared `eTransient`. Vulkan treats that flag as a
lifetime hint; it does not relax synchronization or reset rules.

The final release applies the hint unconditionally because it describes the
pool accurately. See the [`RecordingContext` construction][source-transient-pool].
Before removing the temporary switch, an `A₁/X/A₂` experiment compared
unhinted controls with the hinted candidate in the same executable. The result
was fixed in advance:

- if reset fell beyond control drift, the existing baseline was ineligible and
  the complete matrix had to be rerun;
- if reset rose beyond drift, the hint would be removed; and
- if it remained within drift, the hint would stay as an accurate description
  without receiving credit for a speedup.

The [paired experiment][transient-ci] selected the third branch on both
decision-bearing implementations:

| Implementation | Draws | Candidate distance from control mean | Control drift | Result |
|---|---:|---:|---:|---|
| Lavapipe | 1,000 | 9.236 us | 9.499 us | unresolved within drift |
| Lavapipe | 10,000 | 6.384 us | 13.697 us | unresolved within drift |
| NVIDIA | 1,000 | 0.011 us | 0.171 us | unresolved within drift |
| NVIDIA | 10,000 | 0.188 us | 0.619 us | unresolved within drift |

The hint neither explains Lavapipe's reset cost nor invalidates the accepted
baseline. Keeping it expresses the lifetime correctly; claiming it made reset
faster would exceed the evidence.

## Let a hardware driver challenge the software result

Lavapipe is valuable because it makes the complete measurement available in
CI, but it executes Vulkan on the CPU. A released NVIDIA driver provides a
second decision-bearing implementation with a different cost structure.

The hardware session used an Intel i5-8300H and GeForce GTX 1050 with NVIDIA
580.173.02, a Release build at 800x600 with FIFO presentation, and the CPU
governor fixed to performance while running on mains power. Its one-participant
model was:

| Quantity | 1,000 draws | 10,000 draws |
|---|---:|---:|
| active work `T1` | 168.681 us | 1,243.215 us |
| participant pool reset `W` | 1.394 us | 3.147 us |
| secondary recording `R` | 69.184 us | 522.327 us |
| snapshot, entirely serial | 60.645 us | 676.323 us |
| `F1` | 1.299 us | 1.299 us |
| eligible share `p`, using `F1` | 41.07% | 42.16% |
| ideal two-participant result | `1.258x` | `1.267x` |

Both workloads clear `1.15x`, but almost none of the NVIDIA prediction comes
from reset. At 10,000 draws, participant-pool reset measured `1,884.305 us`
(54.02% of active work) on Lavapipe and `3.147 us` (0.25%) on NVIDIA. The
absolute times remain local to their machines; the shares show that reset
dominates one active-work composition and is negligible in the other.

That disagreement changes the explanation without changing the decision:

| Implementation | Why the ideal gate clears |
|---|---|
| Lavapipe | secondary recording plus a large, driver-specific reset phase |
| NVIDIA | secondary recording itself; reset is negligible |

The pessimistic model matters on Lavapipe because it removes most of the
predicted opportunity. On NVIDIA, treating all reset as serial changes the
10,000-draw ideal result from `1.267x` to `1.266x`. The hardware case therefore
supports attempting the worker without relying on reset divisibility at all.

The disagreement also reveals the next limit. Snapshot construction consumes
54.40% of NVIDIA active work at 10,000 draws and cannot be shortened by adding
recording participants. Even unlimited, cost-free recorders would leave enough
serial work to cap the measured ideal at about `1.729x`.

## Register the hand-off to the worker experiment

The rebaseline answers one question:

> Does the final one-participant architecture contain enough eligible work to
> justify implementing a second participant?

For both decision-bearing implementations and both selected workloads, yes.
The answer survives uncertainty over the fixed reset cost and the more severe
assumption that reset does not divide at all.

It does not answer whether another participant earns its real costs:

```text
one-participant measurement
        |
        v
ideal gate clears at both workloads
        |
        v
implement coordinator + helper
        |
        v
measure dispatch + duplicated setup + synchronization + join
        |
        v
retention gate decides what survives
```

The distinction protects the next experiment from hindsight. Its predicted
reduction and minimum acceptable materialisation are fixed before the helper
runs. A disappointing measurement cannot be rescued by treating the ideal
model as though it had already promised a speedup.

The [coordination post][coordination-post] establishes the coordinator/helper
protocol in the middle of that chain without yet claiming a performance
result.

For NVIDIA at 10,000 draws, the ideal model predicts a reduction of about
`262.07 us`. The registered retention gate requires at least half of that:
`131.03 us`. The two-participant path must therefore measure no more than
`1,112.19 us` of active work against the `1,243.215 us` one-participant
baseline. Dispatch, synchronization, the second command buffer's fixed state,
load imbalance, and joining the helper all have to fit inside the difference.

Only the worker measurement can say whether they do.

## Run the released one-participant path

Release 0.9 retains both recording-participant counts in the same executable.
Forcing one participant runs the descendant of the path measured here:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg -DCMAKE_BUILD_TYPE=Release
cmake --build --preset default

./build/fireEngineTutorial --benchmark 1000 --recording-threads 1
./build/fireEngineTutorial --benchmark 10000 --recording-threads 1
```

The [benchmark option parser][source-benchmark-options] keeps the diagnostic
override inside benchmark and smoke scenarios. Omitting it uses the release's
automatic participant policy; forcing one is how a later paired experiment
keeps the control available in the same binary.

These commands reproduce the measurement path, not the published values. A
comparison still needs its environment, presentation mode, warm-up and sample
counts, and—in the next experiment—the complete bracketed control order.

## Recommended reading

- [Real-Time Rendering][reading-real-time-rendering] — wider context for CPU
  work, frame time, pipeline overlap, and the limits of converting one phase's
  reduction directly into frame-rate improvement.
- [C++ `std::chrono::steady_clock`][reading-steady-clock] — the monotonic clock
  used to place the phase boundaries behind `T1`, `W`, and `R`.
- [Vulkan specification: Command Buffers][reading-command-buffers] — command
  pool flags, reset, external synchronization, and the primary/secondary
  recording structure whose costs differ across the two implementations.
- [C++ Software Design][reading-cpp-design] — background for keeping diagnostic
  controls and performance policy separate from the ownership interfaces they
  measure.

The [Reading page][reading-page] keeps the site-wide list in one place, and the
[Terminology page][terminology-page] collects the measurement vocabulary used
across the 0.9 series.

[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[recording-boundary-post]: {% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %}
[coordination-post]: {% post_url 2026-09-18-coordinating-fireengines-second-recording-participant %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-one-participant-path]: <https://github.com/nnewson/fireEngine-tutorial/blob/791060a/src/render/renderer.cpp#L698-L792>
[source-recording-context]: <https://github.com/nnewson/fireEngine-tutorial/blob/791060a/include/fire_engine/render/detail/recording_context.hpp#L26-L77>
[baseline-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33253122167>
[source-benchmark-report]: <https://github.com/nnewson/fireEngine-tutorial/blob/791060a/src/app/benchmark.cpp#L222-L301>
[source-transient-pool]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/recording_context.cpp#L12-L40>
[transient-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33257839566>
[source-benchmark-options]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/app/main.cpp#L412-L489>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
