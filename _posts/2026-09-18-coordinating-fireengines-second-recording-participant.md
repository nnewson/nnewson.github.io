---
title: "Coordinating fireEngine's second recording participant"
date: 2026-09-18 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, ownership, synchronization, vulkan, cpp]
description: >-
  Add one persistent recording helper while keeping input lifetime, failure
  handling, command-pool ownership, submission, and presentation explicit.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

The [rebaseline post][rebaseline-post] establishes that fireEngine contains
enough participant-owned work to justify trying another recording thread. It
does not make the thread safe. The renderer still needs a protocol that keeps
one frame's frozen input alive until both participants finish, propagates a
failure without abandoning the other participant, and returns completed
secondary command buffers to the coordinator in draw order.

Release 0.9 uses one persistent helper rather than a general thread pool. The
coordinator records the first contiguous range while the helper records the
second. Each participant owns its command pool and secondary command buffer.
Both read the same immutable recording state, but neither shares writable
recording output. Only after both have stopped reading the frame does the
coordinator execute their command buffers, submit, and present.

The important change is therefore a frame-scoped completion contract, not the
existence of `std::thread`. Dispatch and completion form one transaction. If
the coordinator throws, a scope guard still waits. If the helper throws, it
still publishes completion before the exception is rethrown on the coordinator.
No error path may let stack unwinding invalidate input that the other thread is
still reading.

This post covers the concurrent-recording mechanism from the [0.9 release
map][map-post]. It stops before asking whether the mechanism earns
its cost. The [retention post][retention-post] prices dispatch, duplicated
setup, completion, and the released completion-wait policy against the
registered retention gate.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Measurement prerequisite: [the rebaseline post][rebaseline-post]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
{: .prompt-info }

## Introducing the coordination vocabulary

Three roles remain asymmetric:

- a **participant** is one CPU thread that resets its own command pool and
  records one range of secondary commands;
- the **coordinator** is the application's rendering thread. It always records
  one range, then retains primary-command, submission, and presentation
  authority; and
- the **helper** is one persistent internal thread that records the other
  range. It cannot submit, present, replace resources, or reach the live scene.

The protocol is a small **fork-and-join** operation. The coordinator publishes
one helper job, records its own range concurrently, then observes helper
completion before it uses or releases anything shared by the two ranges.

A **scope guard** is a stack object whose destructor performs required cleanup.
Here it waits for the helper during both ordinary control flow and exception
unwinding. The destructor does not report the helper's exception; it establishes
that the helper has finished. Failure reporting happens afterwards, when every
borrow is safe to release.

The [Terminology page][terminology-page] collects the participant, coordinator,
helper, frozen-frame, and capability-boundary definitions used across the 0.9
series.

## Make the coordinator a participant

Creating two helpers while the coordinator waits would introduce two dispatches
and two completion hand-offs. Release 0.9 instead lets the coordinator perform
useful recording work:

```text
frozen RecordingInput
        |
        +--> coordinator --> secondary 0 --+
        |                                  |
        +--> helper ------> secondary 1 ---+--> primary --> submit
```

This is why “two recording participants” means one coordinator and one helper,
not two background workers. Both participants run the same chunk recorder.
Their authority differs only outside that operation: the coordinator owns the
frame before the fork and regains sole control after the join.

The helper is persistent so creating and joining an operating-system thread is
not part of every frame. Between frames it waits for one request. It is not a
task scheduler, and it retains no frame job after completion. The
[`SecondaryRecordingWorker` interface][source-helper-interface] exposes exactly
one dispatch, one completion observation, failure reporting, and an idle-state
query.

Keeping the mechanism this small also makes rejection affordable. At this
point measurement has only permitted an experiment. If the retention gate later
fails, the helper can be removed without unwinding a general job system from
the renderer.

## Pass a recording job rather than the renderer

The ownership work in the [recording-boundary post][recording-boundary-post]
made the hand-off narrow enough to write down. One helper job contains only:

```cpp
struct SecondaryChunkJob
{
    const RecordingContext* context = nullptr;
    RecordingState state{};
    std::span<const RecordingDraw> draws;
};
```

See the [released chunk description][source-chunk-job].

Each field closes a different lifetime or authority question:

| Job field | Why the helper receives it this way |
|---|---|
| `RecordingContext*` | selects one participant-owned pool and secondary buffer without exposing a queue or frame slot |
| `RecordingState` by value | copies the fixed handles and viewport state, so the helper does not borrow the coordinator's stack object |
| `span<const RecordingDraw>` | borrows one immutable contiguous range from the compiler-owned arena |

The job contains no `Renderer::Impl*`, live `Scene`, allocator, resource owner,
submission fence, or presentation state. `const` alone would not create that
boundary: a read-only renderer reference would still provide a route to far
more state than recording needs. The smaller type makes excess authority
unrepresentable.

The draw span remains a borrow. Its storage belongs to the reusable
`RecordingInputCompiler` arena, so the coordinator must not rebuild that arena
while the helper is reading. This is the lifetime the join protects. The
compiled Vulkan buffers, image views, and samplers have their own longer-lived
owners and continue through GPU execution; the CPU packet span does not.

## Split the frame without changing draw order

The first concurrent form uses two equal contiguous ranges. If the draw count
is odd, the coordinator receives the extra draw. If two non-empty ranges cannot
be formed, recording stays on the coordinator.

```text
ordered packets: [0 1 2 3 4]
                  |-----| |---|
coordinator:      [0 1 2]
helper:                 [3 4]

primary executes: secondary 0, then secondary 1
```

Contiguous ranges avoid inventing a scheduling policy before the first correct
measurement. They also preserve ordering: the primary executes the coordinator
secondary first and the helper secondary second. See the [split, dispatch, and
ordered execution][source-split-recording].

Equal draw counts are only a defensible starting point for the synthetic
benchmark, where every draw uses the same cube. They do not imply equal work in
a varied scene. Different meshes and textures can change binding behaviour,
and every secondary pays its own fixed geometry-state setup before its first
draw.

For the same reason, each participant begins with a fresh `DrawBindingState`.
One command buffer cannot inherit the binding cache accumulated by another.
The [chunk recorder][source-chunk-recorder] resets its own pool, begins its
secondary with the required rendering inheritance, establishes complete
geometry state, and records only its span.

## Make completion the lifetime boundary

The vulnerable path is not ordinary success. It is a coordinator-side Vulkan
exception after the helper has started:

```text
dispatch helper
      |
      +-----------------------> helper reads draw span
      |
coordinator records
      |
      +-- throws
      |
stack unwinds ----------------> draw span would expire too early
```

A manual wait placed after coordinator recording would be skipped by that
throw. `ChunkJoin` makes the wait unconditional:

```cpp
class ChunkJoin final
{
public:
    explicit ChunkJoin(SecondaryRecordingWorker& helper) noexcept
        : helper_{&helper}
    {
    }

    ~ChunkJoin() noexcept
    {
        helper_->awaitCompletion();
    }

private:
    SecondaryRecordingWorker* helper_;
};
```

See the [frame-local completion guard][source-chunk-join].

The guard is constructed immediately after dispatch and before the coordinator
records its own chunk. Its destructor therefore runs after normal recording or
while a coordinator exception unwinds. In both cases, leaving the scope means
the helper has stopped reading its job.

This produces one useful invariant:

```text
dispatch
   |
   v
both participants may read the frozen frame
   |
   v
join completes
   |
   +--> input may be rebuilt
   +--> resources may be replaced
   +--> presentation may be recreated
   +--> renderer may be destroyed
```

`prepare()`, presentation replacement, `waitIdle()`, and renderer destruction
assert that the helper is idle when they begin. They do not need independent
join logic because `drawFrame()` cannot return with an outstanding job. The
helper is also declared after the frame resources it borrows, so reverse member
destruction stops and joins it before those recording contexts are released.

## Propagate failure only after both participants stop

An exception escaping a `std::thread` entry point terminates the process. The
helper instead catches every exception, stores an `exception_ptr`, and still
publishes completion. The coordinator observes completion before asking the
helper to rethrow. See the [helper's dispatch and run loop][source-helper-loop].

The order is deliberate:

```text
helper failure
    |
    +--> capture exception
    +--> publish completion
             |
coordinator observes completion
    |
    +--> all frame borrows have ended
    +--> rethrow helper exception
```

Waiting and reporting are separate operations because the scope-guard
destructor must not throw during stack unwinding. If the coordinator has already
failed, its exception continues only after the helper finishes. If the helper
failed, its exception is rethrown later from ordinary coordinator control flow.

Dispatch also clears the previous stored failure. A caller may deliberately
leave one helper exception unobserved during teardown or testing; it must not
resurface on a later successful frame. The device-free [worker unit
tests][source-worker-tests] cover successful dispatch, omitted instrumentation,
failure after completion, stale-failure clearing, and clean destruction with an
unobserved failure.

The final 0.9 implementation publishes completion through an atomic flag. A
release store by the helper and acquire observation by the coordinator make the
helper's earlier timing writes and captured exception visible before they are
read. How long the coordinator polls that flag before blocking is a measured
performance policy, not part of the lifetime proof, and belongs in the next
post.

## Keep the comparison topology unchanged

The one- and two-participant measurement arms must differ in execution, not in
which long-lived owners happen to exist. Every frame slot therefore constructs
two secondary `RecordingContext` values in both configurations. With one
participant, the second context is allocated but never reset or recorded into.

```text
frame slot 0                         frame slot 1
├── submission state                ├── submission state
├── coordinator primary context     ├── coordinator primary context
├── secondary context 0             ├── secondary context 0
└── secondary context 1             └── secondary context 1

one-participant arm: use context 0
two-participant arm: use contexts 0 and 1
```

That stable topology prevents construction differences from being mistaken for
threading cost. It also avoids optional storage around immovable recording
contexts. The [frame-resource grouping][source-frame-resources] owns the same
array regardless of the selected participant count.

The diagnostic `--recording-threads` option can consequently select one or two
participants in the same executable. Retaining both paths is necessary for the
later `A₁/X/A₂` experiment; whether ordinary rendering should select both is
still undecided here.

## Measure overlapping work without double-counting it

Once two participants overlap, their durations cannot be added and described
as elapsed time. A 100-microsecond coordinator range and a 100-microsecond
helper range may complete in roughly 100 microseconds, not 200.

Each participant therefore writes its own `ChunkRecordingTimings` block. The
blocks are aligned to separate cache lines so concurrent timestamp writes do
not make both CPU cores repeatedly invalidate the same line. Only after the
join does the coordinator merge them into public timing values. See the
[participant timing blocks][source-participant-timings] and their
[post-join merge][source-timing-merge].

The report distinguishes two ideas:

- summed participant reset and recording durations describe total CPU work;
- the region from publishing the helper job until completion is observed is
  elapsed work on the coordinator's critical path.

The latter includes dispatch and completion costs and is therefore the value a
retention comparison must price. The former remains diagnostic: it can reveal
that elapsed time fell while aggregate CPU work rose.

Timestamps from the two participants are compared only after both have
finished. On the supported targets `steady_clock` provides the shared monotonic
clock required for their offsets and critical-path boundaries to be meaningful.
Ordinary frames pass no timing block and avoid those clock samples.

## Exercise the split rather than merely starting a thread

The helper itself is device-free, so focused tests can exercise dispatch,
completion, failure capture, stale-failure clearing, and destruction without a
Vulkan device. The renderer still needs device scenarios because two secondary
command buffers now inherit and execute inside one dynamic-rendering instance.

Three details prevent those scenarios from passing accidentally:

1. A two-draw benchmark is forced to use two participants, and its report must
   say that both were effective.
2. A one-draw benchmark requests two participants but must report the required
   fallback to one non-empty range.
3. The repeated-preparation fixture uses the draw order `A, A, B / A, A, B`, so
   each secondary independently exercises its first bind, a redundant bind
   skip, and a resource change.

The [fixture construction][source-mixed-fixture] and [CTest
registrations][source-integration-tests] keep those cases explicit. The split
benchmark and mixed-resource scenario also run with synchronization validation
in Debug builds.

A ThreadSanitizer run reported no race on the exercised synthetic and
mixed-resource paths. That result proves only that no race was observed there.
A temporary non-atomic shared sentinel was therefore injected into the real
fork-and-join path; ThreadSanitizer reported it, and the sentinel was reverted.
The positive control shows that the instrument could detect a race on this path
rather than merely producing a green run.

The coordinator-failure path requires Vulkan and was exercised with temporary
fault injection. The exception propagated out of `drawFrame()` without a hang,
after the completion guard had observed the helper. The retained unit and
device paths passed in [the implementation CI run][worker-ci].

## Stop at functional evidence

At this point release 0.9 has established that:

- one coordinator and one helper can record disjoint ranges concurrently;
- each participant resets only its own command pool;
- immutable recording input remains alive until both readers finish;
- command-buffer execution preserves the original draw order;
- coordinator and helper failures cannot abandon an outstanding borrow;
- participant-local timing can be merged after completion; and
- the single-participant control remains available in the same executable.

None of those claims says the second participant is faster. The helper adds a
request hand-off, another fixed command-buffer setup, concurrent driver work,
and a completion wait. Correctness makes those costs measurable; it does not
make them small.

That distinction supplies the next dependency:

```text
safe recording boundary
        |
        v
correct coordinator/helper protocol
        |
        v
paired one/two/one measurement
        |
        v
retention gate and workload policy
```

The [retention post][retention-post] can now ask whether the real implementation
earns its overhead without mixing that question with input lifetime, exception
safety, or whether the command structure is valid.

## Run the released split path

Release 0.9 retains a diagnostic override that forces both participant counts.
These commands exercise the split, its one-draw fallback, and the mixed-resource
scenario:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg
cmake --build --preset default

./build/fireEngineTutorial --benchmark 2 --recording-threads 2
./build/fireEngineTutorial --benchmark 1 --recording-threads 2
./build/fireEngineTutorial --smoke prepare-twice --recording-threads 2
```

The first command gives each participant one draw. The second proves that a
requested split falls back rather than creating an empty range. The third
records the `A, A, B / A, A, B` fixture through resource replacement.

These are correctness scenarios. Performance comparison requires a Release
build, the complete one/two/one order, the named environment, and the registered
retention calculation covered next.

## Recommended reading

- [C++ `std::counting_semaphore`][reading-semaphore] — the standard request
  primitive used to park and wake the persistent helper.
- [C++ `std::atomic::wait`][reading-atomic-wait] — the final release's
  completion primitive, including the need to recheck the atomic value after a
  wake.
- [C++ `std::exception_ptr`][reading-exception-ptr] — capturing an exception on
  one thread and rethrowing it after the coordinator has observed completion.
- [Vulkan specification: Command Buffers][reading-command-buffers] — the
  command-pool synchronization, secondary inheritance, and execution rules that
  remain participant-local here.

The [Reading page][reading-page] keeps the site-wide list in one place, and the
[Terminology page][terminology-page] collects the project-specific vocabulary
used across the 0.9 series.

[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[recording-boundary-post]: {% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %}
[rebaseline-post]: {% post_url 2026-09-17-rebaselining-fireengine-before-adding-another-recording-thread %}
[retention-post]: {% post_url 2026-09-20-deciding-when-fireengines-second-recording-participant-earns-its-overhead %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-helper-interface]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/secondary_recording_worker.hpp#L60-L195>
[source-chunk-job]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/secondary_recording_worker.hpp#L60-L66>
[source-split-recording]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L834-L910>
[source-chunk-recorder]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L1245-L1288>
[source-chunk-join]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L228-L251>
[source-helper-loop]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/secondary_recording_worker.cpp#L26-L133>
[source-worker-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/tests/render/test_secondary_recording_worker.cpp#L35-L126>
[source-frame-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L100-L110>
[source-participant-timings]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/secondary_recording_worker.hpp#L40-L54>
[source-timing-merge]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L1290-L1355>
[source-mixed-fixture]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/app/main.cpp#L531-L568>
[source-integration-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/CMakeLists.txt#L272-L380>
[worker-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33269684864>
[reading-semaphore]: <https://en.cppreference.com/w/cpp/thread/counting_semaphore>
[reading-atomic-wait]: <https://en.cppreference.com/w/cpp/atomic/atomic/wait>
[reading-exception-ptr]: <https://en.cppreference.com/w/cpp/error/exception_ptr>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
