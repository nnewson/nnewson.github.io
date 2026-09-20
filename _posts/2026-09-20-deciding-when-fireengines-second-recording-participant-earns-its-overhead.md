---
title: "Deciding when fireEngine's second recording participant earns its overhead"
date: 2026-09-20 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, performance, benchmarking, synchronization, vulkan, cpp]
description: >-
  Apply registered retention and drift rules, one bounded remediation, and two
  Vulkan implementations to decide when parallel recording should run.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

The [coordination post][coordination-post] leaves fireEngine with a safe second
recording participant. Safe is not the same as worthwhile. Dispatching a helper
adds another command buffer's fixed setup, a request hand-off, concurrent driver
work, and a completion wait. That cost can be smaller than the recording time it
removes at one workload and larger at another.

This is the final performance decision posed by the [0.9 release map][map-post].

This makes the last 0.9 question unusually easy to answer dishonestly. A poor
result could be rescued by moving the workload threshold, trying several wait
durations, rerunning until the controls happen to be close, or reporting only
the implementation that improved. Each choice can sound reasonable after the
numbers are visible.

The experiment therefore needs to be capable of rejecting the worker before it
is allowed to measure one. Its retention threshold, noise rule, and single
remediation allowance must constrain the result rather than explain it
afterwards. When one remediated acquisition contains more control drift than
candidate movement, a replacement rule must also be recorded before another
result exists.

That discipline produces a conditional answer. The remediated helper satisfies
the registered retention gate on Lavapipe and benefits both measured Vulkan
implementations at 10,000 draws. It still makes 1,000 draws 9.7% slower on the
NVIDIA system. Release 0.9 consequently retains parallel recording but selects
it automatically only at the measured large-workload boundary.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Measurement model: [the rebaseline post][rebaseline-post]
>
> Recording protocol: [the coordination post][coordination-post]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
{: .prompt-info }

## Introducing the decision vocabulary

The experiment compares one and two recording participants in an `A₁/X/A₂`
order. `A₁` and `A₂` are matching one-participant controls around the
two-participant candidate `X`. Their mean is the baseline
`C = (A₁ + A₂) / 2`; their difference is the control drift
`D = abs(A₂ - A₁)`.

A candidate is **resolved** only when its distance from the control mean is
larger than that drift:

```text
abs(X - C) > D
```

Otherwise it is **unresolved within drift** and supports no directional claim.
It is neither a pass nor a failure because the experiment has not distinguished
the candidate from variation between identical controls.

The retention gate uses **materialisation**: the share of the ideal reduction
predicted by the one-participant model that the measured worker actually
delivers. A **decision-bearing implementation** is an environment selected in
advance as suitable for retaining or rejecting the change, rather than an
informative preview driver or incidental machine.

The [Terminology page][terminology-page] collects these definitions and the
distinction between attempt and retention gates used across the 0.9 series.

## Make the experiment capable of saying no

Before either worker matrix is interpreted, the complete decision contract is
visible:

| Constraint | Consequence |
|---|---|
| Retention gate | The worker must materialise at least half of the predicted reduction at both 1,000 and 10,000 draws on at least one decision-bearing implementation. Otherwise it is removed. |
| Drift rule | A cell with `abs(X - C) <= D` produces no measurement, so it cannot pass or fail the retention gate. |
| Remediation allowance | After a failed matrix, one diagnosed change may be registered before its code is written. The full matrix is then repeated once; no duration sweep or second adjustment is allowed. |
| Void-cell replacement | When the remediated 1,000-draw Lavapipe acquisition later proved unresolved, exactly one same-commit replacement was registered before its result or the NVIDIA result was known. The void acquisition cannot be averaged with it, selected over it, or retried again. |

The replacement clause was not part of the original protocol: that protocol did
not anticipate its drift guard erasing a cell completely. The record was
extended after the void was known but before any replacement was run. It also
required the replacement regardless of the NVIDIA outcome, preventing the
decision to collect it from depending on whether a favourable result was still
needed.

The order is the protection:

```text
question
   |
   v
decision contract
   |
   v
first matrix --fails--> one diagnosed remediation
                            |
                            v
                     repeated matrix
                            |
                            v
                      release policy
```

The registered protocol fixes the run order, active-work boundary, model inputs,
and reporting requirements. Both implementations run 16 warm-up frames and 64
measured frames per arm. Participant durations remain diagnostic; the
comparison uses the coordinator-observed recording region so dispatch and
completion costs stay inside `X`.

## Let the first implementation fail visibly

The first complete worker matrix used the [registered comparison
implementation][initial-measurement-commit]: the persistent coordinator/helper
protocol without bounded polling. Lavapipe ran in Release at 800×600 with
Mailbox presentation on Mesa llvmpipe 25.2.8. NVIDIA ran in Release at 800×600
with FIFO presentation on an Intel i5-8300H and GeForce GTX 1050, driver
580.173.02, with the CPU governor fixed to performance on AC power. The local
acquisition ran on 29 August 2026.

`T1` is the mean active-work duration of the two one-participant controls. `T2`
is the two-participant candidate. “Gate needs” is the largest `T2` that would
materialise half of the model's predicted reduction.

| Implementation | Draws | `T1` | `T2` | Gate needs | Verdict | Materialisation | Measured |
|---|---:|---:|---:|---:|---|---:|---:|
| Lavapipe | 1,000 | 291.582 µs | 260.308 µs | 234.916 µs | fail | 27.6% | 1.120× |
| Lavapipe | 10,000 | 2,478.580 µs | 1,794.304 µs | 2,000.290 µs | pass | 71.5% | 1.381× |
| NVIDIA | 1,000 | 166.430 µs | 199.940 µs | 149.849 µs | fail | −101.1% | 0.832× |
| NVIDIA | 10,000 | 1,234.246 µs | 1,092.181 µs | 1,101.723 µs | pass | 53.6% | 1.130× |

Every cell resolves against its controls. Lavapipe's candidate movements are
31.274 and 684.276 microseconds against drift of 14.167 and 206.214;
NVIDIA's are 33.510 and 142.065 microseconds against drift of 3.750 and 31.453.
None can be softened into noise after failing.

The `−101.1%` materialisation at 1,000 NVIDIA draws is particularly useful. The
model predicted a reduction, but the measured implementation increased active
work by 20.1%. The negative ratio preserves that failure instead of clipping it
at zero. At 10,000 draws both implementations pass, but the retention rule asks
one implementation to pass both workloads. Neither does, so the initial worker
fails its retention gate. The Lavapipe evidence remains available in the
[initial CI acquisition][initial-ci]; the NVIDIA acquisition is author-reported
from the named local environment because no public job exercised that hardware.

## Diagnose one change instead of tuning the worker

The failed matrix did more than produce four verdicts. In every cell the helper
finished last, leaving the coordinator blocked in its completion wait. The gap
between the coordinator-observed recording region and the participants'
critical path was 31.220 and 16.952 microseconds on Lavapipe, then 18.698 and
44.086 microseconds on NVIDIA. That gap includes dispatch before either
participant starts and the delay after the last participant finishes, so it
only bounds the completion delay from above.

The matrix also closes the earlier reset-overlap question. At 10,000 Lavapipe
draws, the reset region spanned `706.479 µs`; the slower participant reset took
`692.481 µs` and the helper began `14.872 µs` after the coordinator. The two
resets therefore overlapped. The model was still optimistic because splitting
increased the participants' aggregate CPU work:

| Implementation | Draws | Recording, one to two | Reset, one to two |
|---|---:|---:|---:|
| Lavapipe | 1,000 | +3.4% | +7.4% |
| Lavapipe | 10,000 | +22.5% | +22.5% |
| NVIDIA | 1,000 | +67.7% | +247.7% |
| NVIDIA | 10,000 | +5.2% | +141.3% |

The cause remains undiagnosed. Cache locality, concurrent driver contention,
processor-frequency behaviour, and command allocation are possible
explanations, not findings. The NVIDIA reset percentages are also ratios of
small durations: its 1,000-draw reset rose from `1.254 µs` to `4.360 µs`, not by
an amount comparable with Lavapipe's reset work.

The helper began recording 21.774 and 14.872 microseconds after the coordinator
on Lavapipe, then 21.742 and 41.541 microseconds after it on NVIDIA. Those
offsets and the completion-side gaps identify where latency appears without
claiming that processor scheduling or power states caused it.

The single permitted [remediation change][remediation-commit] targeted the
latter. After finishing its own recording, the coordinator polls the completion
flag for at most 50 microseconds. If the helper has not published completion by
then, the coordinator falls back to the existing blocking atomic wait:

```cpp
const auto start = std::chrono::steady_clock::now();
bool acquiredBySpin = false;
while (true)
{
    if (completionPublished_.load(std::memory_order_acquire))
    {
        acquiredBySpin = true;
        break;
    }
    if (std::chrono::steady_clock::now() - start >= kCompletionSpinBudget)
    {
        break;
    }
}

bool usedBlockingWait = false;
while (!completionPublished_.load(std::memory_order_acquire))
{
    usedBlockingWait = true;
    completionPublished_.wait(false, std::memory_order_acquire);
}
```

See the [released completion wait][source-completion-wait]. The 50-microsecond
bound exceeds each measured exterior gap without pretending those gaps are pure
wake latency. No shorter or longer values were tried. The helper still blocks
while waiting for work between frames: under FIFO it waits for roughly 16
milliseconds, so polling there would occupy a core or expire on every frame.

The same change adds measurements for the join wait, the interval after the
last participant finishes, and whether polling or the blocking fallback
observed completion. Those measurements test the proposed mechanism; the
unchanged materialisation rule still decides retention. A speedup would not be
rejected merely because its cause remained unexplained, nor accepted merely
because the new diagnostics behaved as expected.

## Let drift erase an acquisition

The first remediated Lavapipe acquisition reaches the drift rule before it
reaches the gate. Its 1,000-draw controls measured `413.553 µs` and
`229.801 µs`, a difference of `183.752 µs`, or 57.12%. The candidate sat only
`108.549 µs` away from their mean.

```text
A₁ = 413.553 µs
A₂ = 229.801 µs

C = 321.677 µs
D = 183.752 µs

abs(X - C) = 108.549 µs <= D
```

That acquisition says nothing about whether the remediation helped. Using the
first control alone would imply 122% materialisation; using the second would
imply 18%. Choosing either would make the answer depend on which identical arm
the author preferred.

The already-stated replacement rule therefore fires. One complete acquisition
runs on the same commit, binary configuration, workload, and ordering. The void
cell is discarded rather than averaged with it. The replacement is
authoritative if it resolves; if it is also void, Lavapipe remains unclassified
at 1,000 draws and cannot satisfy the two-workload gate. No third attempt is
available. Recording both control arms here keeps the reason visible rather
than reducing the acquisition to an unexplained discarded run.

## Compare the same experiment after remediation

The remediated Lavapipe matrix ran in [CI run 33330427667][remediation-ci]. Its
1,000-draw cell was void, so [the permitted replacement][replacement-ci] is
authoritative for that cell only; the original resolved 10,000-draw result
remains authoritative. NVIDIA ran the same nine-arm block locally on 30 August
2026 with the hardware and settings used by the first matrix.

| Implementation | Draws | `T1` | `T2` | Gate needs | Verdict | Materialisation | Measured |
|---|---:|---:|---:|---:|---|---:|---:|
| Lavapipe | 1,000 | 282.267 µs | 205.501 µs | 228.367 µs | pass | 71.2% | 1.374× |
| Lavapipe | 10,000 | 2,463.293 µs | 1,448.550 µs | 1,980.371 µs | pass | 105.1% | 1.700× |
| NVIDIA | 1,000 | 168.817 µs | 185.136 µs | 152.333 µs | fail | −49.5% | 0.912× |
| NVIDIA | 10,000 | 1,231.291 µs | 1,018.864 µs | 1,099.977 µs | pass | 80.9% | 1.209× |

Every retained cell resolves against its controls. Lavapipe now passes both
workloads, satisfying the registered retention gate. That is enough to retain
the mechanism under the recorded rule, but it is a Lavapipe-backed retention
result rather than a general cross-driver win. NVIDIA still makes 1,000 draws
9.7% slower.

Lavapipe's 105.1% materialisation does not mean the worker scaled
superlinearly. Other measured phases also moved favourably relative to the
model, and that cell's controls differed by 15.97%. Materialisation compares
the observed reduction with a prediction; it is not itself a speedup.

Using the same table shape makes the movement visible:

| Implementation | Draws | Before | After |
|---|---:|---:|---:|
| Lavapipe | 1,000 | 27.6% | 71.2% |
| Lavapipe | 10,000 | 71.5% | 105.1% |
| NVIDIA | 1,000 | −101.1% | −49.5% |
| NVIDIA | 10,000 | 53.6% | 80.9% |

These are materialisation ratios, not a claim that polling alone caused every
difference between sessions. The mechanism diagnostics are narrower. The
post-remediation completion tail measured 0.937 and 1.383 microseconds on
Lavapipe, then 0.217 and 3.554 microseconds on NVIDIA. Polling observed
completion on 93.75%, 89.06%, 96.88%, and 68.75% of measured frames,
respectively. No frame landed between the final poll and the blocking wait.

The initial exterior gaps are not literal tail measurements because the tail
instrumentation did not yet exist. They are upper bounds containing dispatch as
well as completion. The small measured tails and frequent polling acquisitions
support the registered diagnosis without manufacturing a before/after quantity
that was never collected. The public CI acquisition and this record preserve
that distinction.

The remaining 1,000-draw NVIDIA shortfall is similarly bounded but not
explained. It misses the gate by `32.803 µs`, while the helper starts
`37.355 µs` behind the coordinator. Removing that offset might appear sufficient,
but the experiment does not establish that contention and participant costs
would remain unchanged. The release therefore retains the failure instead of
treating the offset as an unmeasured future win.

## Turn disagreement into the release policy

The retention gate decides whether the worker survives. It does not require the
renderer to dispatch it for every scene. The 1,000-draw NVIDIA regression makes
an unconditional two-participant policy indefensible, while both
implementations benefit at 10,000 draws.

Release 0.9 therefore gives each participant at least 5,000 draws. Fewer than
10,000 total draws stay on the coordinator; 10,000 or more use the coordinator
and helper, capped at the two participants the release supports:

```cpp
constexpr std::size_t automaticParticipantCount(std::size_t drawCount) noexcept
{
    const std::size_t supported = drawCount / kMinimumDrawsPerRecordingParticipant;
    if (supported < 2)
    {
        return 1;
    }
    return supported > kMaxSecondaryRecordingThreads ? kMaxSecondaryRecordingThreads : supported;
}
```

See the [released automatic selection][source-automatic-selection] and its
[measured threshold][source-workload-threshold]. This is the boundary tested by
the experiment, not an estimate of the crossover somewhere between 1,000 and
10,000. Nothing in the measurements locates that crossover, so choosing a lower
number would guess past the observed hardware regression.

The `--recording-threads` option remains a diagnostic override. It can force one
or two participants below the automatic threshold so later measurements and
validation do not lose either path. The release also registers application
scenarios immediately below and at the automatic boundary, proving that the
renderer consults the policy rather than only testing its arithmetic. See the
[automatic-policy scenarios][source-policy-tests].

## Keep the conclusion narrower than the numbers

The experiment supports a workload policy, not a general statement that another
thread makes rendering faster.

| Claim 0.9 does not make | Evidence limit |
|---|---|
| Parallel recording is universally faster | NVIDIA regressed at 1,000 draws. |
| The crossover occurs at 10,000 draws | Only 1,000 and 10,000 were decision workloads. |
| The result represents arbitrary scenes | The synthetic workload repeats one cube and divides unusually evenly. |
| Active-work speedup is frame-rate improvement | Presentation waits and display pacing remain outside the worker gate. |
| More helpers will continue scaling | The release measures only one coordinator and one helper. |
| The experiment explains every added CPU cost | Splitting increased aggregate participant work; cache effects, driver contention, processor frequency, and allocation behaviour remain possible causes rather than findings. |

Parallel recording deliberately trades more aggregate CPU work for a shorter
elapsed critical path. In the passing Lavapipe 1,000-draw cell, the recording
region fell 35.9% while summed participant recording rose 1.5% and summed reset
rose 15.6%. At 10,000 NVIDIA draws, the region fell 38.2% while summed recording
rose 2.6%. The trade is useful, but it is still a trade.

The durable result is conditional: fireEngine has a safe two-participant path,
a measured reason to retain it, and evidence that says when not to use it. The
failed matrix, the void acquisition, and the NVIDIA regression are not detours
from that conclusion. They are what prevent the released policy from claiming
more than the experiment established.

## Where 0.10 takes this

Version 0.9 proves that immutable frame input can be divided safely between
command-recording participants inside one graphics pass. Version 0.10 asks
whether the same boundaries survive the renderer's first genuine second pass.

The current plan adds a depth-only directional-shadow pass before the forward
pass. Each frame slot owns its shadow map; the shadow pass writes it and the
forward pass samples it. CPU recording, queue submission, and presentation
remain serial, while the existing one- or two-participant policy continues to
apply to the forward pass.

This is deliberately not a render-graph exercise. Two known passes and one
explicit resource dependency should first show whether frame input can provide
restricted per-pass views without exposing scene mutation or resource
ownership. Any later generalisation should follow evidence from that concrete
pressure.

## Run the released policy and its controls

Release 0.9 can exercise automatic selection and both forced comparison arms in
the same executable:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg -DCMAKE_BUILD_TYPE=Release
cmake --build --preset default

./build/fireEngineTutorial --benchmark 1000
./build/fireEngineTutorial --benchmark 10000
./build/fireEngineTutorial --benchmark 10000 --recording-threads 1
./build/fireEngineTutorial --benchmark 10000 --recording-threads 2

ctest --test-dir build \
  -R "^fireEngineTutorialAutomatic(Recording|Split)Correctness$" \
  --output-on-failure
```

The first two commands show automatic selection on either side of the measured
boundary. The next two retain the one- and two-participant controls used by an
`A₁/X/A₂` acquisition. The complete recorded order is:

```shell
# Minimal-content reset endpoint, F1
./build/fireEngineTutorial --benchmark 1 --recording-threads 1

# 1,000-draw A₁/X/A₂
./build/fireEngineTutorial --benchmark 1000 --recording-threads 1
./build/fireEngineTutorial --benchmark 1000 --recording-threads 2
./build/fireEngineTutorial --benchmark 1000 --recording-threads 1

# 10,000-draw A₁/X/A₂
./build/fireEngineTutorial --benchmark 10000 --recording-threads 1
./build/fireEngineTutorial --benchmark 10000 --recording-threads 2
./build/fireEngineTutorial --benchmark 10000 --recording-threads 1

# Direct-primary reset endpoints, F0
./build/fireEngineTutorial --benchmark 1000 --direct-primary
./build/fireEngineTutorial --benchmark 10000 --direct-primary
```

Reproducing the published figures still requires the recorded environment,
presentation mode, 16 warm-up frames, and 64 measured frames per arm; running
only one invocation is a path check, not the experiment.

## Recommended reading

- [Real-Time Rendering][reading-real-time-rendering] — context for CPU work,
  critical paths, and why reducing one phase is not automatically a matching
  frame-rate improvement.
- [C++ `std::chrono::steady_clock`][reading-steady-clock] — the monotonic clock
  used for control arms, candidate timings, and completion diagnostics.
- [C++ `std::atomic::wait`][reading-atomic-wait] — the blocking fallback used
  after the coordinator exhausts its bounded polling interval.
- [C++ Software Design][reading-cpp-design] — background for separating an
  internal workload policy and diagnostic override from the ownership
  interfaces whose behaviour they select.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[rebaseline-post]: {% post_url 2026-09-17-rebaselining-fireengine-before-adding-another-recording-thread %}
[coordination-post]: {% post_url 2026-09-18-coordinating-fireengines-second-recording-participant %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-completion-wait]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/secondary_recording_worker.cpp#L41-L84>
[source-workload-threshold]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L52-L62>
[source-automatic-selection]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L1165-L1183>
[source-policy-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/CMakeLists.txt#L289-L297>
[initial-measurement-commit]: <https://github.com/nnewson/fireEngine-tutorial/commit/4a47a35f7954a20d050d2ec3f4e520f1ebed3359>
[initial-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33326725046/job/99298074704>
[remediation-commit]: <https://github.com/nnewson/fireEngine-tutorial/commit/f2393554a8317ab4d8aee16acf9a17c799aee776>
[remediation-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33330427667/job/99307903727>
[replacement-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33330427667/job/99309552672>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-atomic-wait]: <https://en.cppreference.com/w/cpp/atomic/atomic/wait>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
