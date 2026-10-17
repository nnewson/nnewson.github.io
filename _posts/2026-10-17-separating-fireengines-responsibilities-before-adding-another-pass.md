---
title: Separating fireEngine's responsibilities before adding another pass
date: 2026-10-17 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.10", 3d-engine, architecture, ownership, refactoring, testing, vulkan, cpp]
description: >-
  Separate presentation replacement, frame-slot synchronization, uniform
  storage and forward recording, then test what the refactor preserved—and
  what an unchanged image cannot prove.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.10"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
---

A second rendering pass does not just need another function that records
commands. It needs somewhere to put resources that change for different
reasons, and a way to use those resources without acquiring permission to
replace them.

In fireEngine 0.10, the shadow map has a fixed size while the camera-view depth
attachment follows the window. Both are selected by frame slot. Camera and
light matrices share a uniform buffer, but changing that buffer's layout
should not change submission synchronization. The forward recorder needs
attachment handles, but it does not need the presentation owner that can
replace those attachments.

Those distinctions answer the [release map's responsibility
question][map-responsibilities]. The aim is not to maximise the number of
classes. It is to make the reason for replacing each resource—and the
authority given to each recorder—visible before adding another consumer.

There is a preservation question alongside the design question. Moving a
recorder could keep the image correct while accidentally serialising its two
CPU participants. Separating uniforms could keep a reference capture unchanged
while selecting the wrong slot's buffer. No single green test answers both.

The responsibility-only work therefore had a narrow contract: preserve the
existing forward output, recording modes, draw order and lifetime rules; keep
the timing categories attached to the same work; and retain participant
overlap. It was not an optimisation experiment, and the old benchmark results
were not a new performance target.

> Code for this article: [fireEngine 0.10][release-0-10]
>
> Released design: [fireEngine 0.10 architecture][architecture-0-10]
>
> The source examples describe the released system. Historical preservation
> checks below concern the forward-only extraction, before shadows and the
> later rotation-interpolation correction changed the rendered image.
{: .prompt-info }

## Introducing the ownership and recording vocabulary

Shared engine terms are collected on the [Terminology page][terminology-page].
For this post, these distinctions matter:

- A **frame slot** is a reusable set of submission resources. Waiting for its
  fence establishes that the earlier submitted work has finished using them.
  A **swapchain image** is a separate selection, returned by image acquisition.
  Its index is not the frame-slot index.
- A **uniform buffer** holds shader values shared across draws. Here those
  values are camera and light view-projection matrices; the buffer is storage,
  not the synchronization that makes writing it safe.
- The **coordinator** is the rendering thread that acquires images, submits
  work and presents. A **recording participant** records a range of forward
  draws: the coordinator itself, optionally joined by one helper thread.
- A **primary command buffer** can be submitted to a queue. A **secondary
  command buffer** is executed through a primary. In the production forward
  path, each participant records a secondary; the coordinator records their
  execution into the primary.
- **Retirement** means establishing that the relevant earlier work has
  finished, so its resources may be reused or released. Submission completion
  and presentation completion are separate checks.

The forward pass produces the camera-view colour image. The shadow pass
produces depth for that forward pass to sample. Naming something “forward”
limits its responsibility; it does not imply a common base class for all
passes.

## An index does not decide an owner

The [0.9 renderer already has a `PresentationState`][source-old-presentation].
It is a file-local type in `renderer.cpp`, grouping the swapchain, depth
attachments, pipeline and presentation-completion state. Version 0.10 extracts
that existing group into an internal owner; it does not invent presentation
replacement.

The important question is which other resources belong in that group. “Used
by this frame” is too broad: it would put almost the entire renderer there.
“Indexed by frame slot” is also insufficient:

| Resource | Selected by | Replaced when presentation changes? |
| --- | --- | --- |
| Swapchain colour image and presentation fence | acquired image index | yes |
| Forward depth attachment | frame-slot index | yes; its extent follows the swapchain |
| Frame uniform buffer | frame-slot index | no; its values are updated for the new view |
| Fixed-size shadow map | frame-slot index | no |
| Forward pipeline | attachment compatibility | yes, as part of the presentation group |

The forward depth attachment is the useful counterexample. It is slot-local
because overlapping submitted frames need independent depth storage, but it
is presentation-dependent because its dimensions follow the swapchain. Its
index tells us when it can be reused; its dimensions help decide when it must
be replaced.

The released [presentation owner][source-presentation] therefore keeps the
per-slot forward depth attachments alongside the swapchain. The fixed-size
shadow maps belong to [presentation-independent frame
resources][source-frame-resources]. Putting every depth image into one owner
would conceal the distinction the second pass needs.

That choice gives presentation replacement a bounded job. The renderer waits
for submitted work and pending presentations, constructs a complete new
presentation group, and replaces its `unique_ptr` only after construction
succeeds. The [replacement call][source-recreation] passes the old swapchain
handle while the old C++ owner remains alive. Uniform buffers, recording
contexts and shadow maps are outside the replaced group.

The extracted [constructor][source-presentation-constructor] also retains
less visible behaviour: it passes through whether capture is enabled, rejects
unsupported capture formats, and checks that Vulkan returned a complete
swapchain. Moving only the obvious image and pipeline members would not have
preserved that contract. We will need a test that reaches replacement, not
just initial construction, to check it.

## Separate the completion check from the shader data it protects

Once presentation replacement stops claiming everything used by a frame,
there is another boundary inside the slot itself. The [0.9
`FrameSlot`][source-old-slot] owns both synchronization objects and the uniform
allocation. Its constructor consequently needs a device, an allocator and
initial shader values.

Those inputs reveal two jobs. Creating a submission fence does not depend on
the layout of camera data. Allocating camera data does not decide when an
earlier submission has finished reading it.

In 0.10, [`FrameSlot`][source-slot] owns only the image-available semaphore,
frame-finished fence and pending-work flag. [`FrameUniformBuffer`][source-uniform]
owns the allocation, initialises its values, and supplies a non-owning buffer
handle and an update operation. The released [containing
structure][source-frame-resources] makes their association explicit:

```cpp
struct FrameResources final
{
    FrameSlot slot;
    FrameUniformBuffer uniforms;
    ShadowFrameResources shadow;
    ForwardFrameResources forward;
};
```

This is the final two-pass structure, not an intermediate forward-only layout.
Both passes now use the same slot's `FrameUniforms`, containing camera and
light matrices. Expanding that shader contract did not require adding matrix
knowledge to the synchronization owner.

Separating the types does not itself enforce the update order.
`FrameUniformBuffer::update()` does not wait on a fence. The renderer must
select a single `FrameResources` and preserve this order:

```text
select frame slot
        |
        v
freeze CPU input using that slot's buffer handle
        |
        v
wait for that slot's earlier submission
        |
        v
write that slot's uniform buffer
        |
        v
acquire an image, record and submit
```

The [call site][source-slot-update] is the evidence: both pass states receive
`frame.uniforms.handle()`, the wait uses `frame.slot`, and the subsequent
write uses `frame.uniforms`. Building the CPU input before the wait does not
write the GPU buffer; it prepares values and borrows its handle.

There is an important test limit here. At the extraction checkpoint the smoke
camera and framebuffer aspect were constant. By the reference capture, both
slot buffers contained identical values. Swapping their selection could
therefore preserve the image and remain validation-clean. The earlier
per-slot depth checks did not establish uniform selection either.

The preserved association and call order support this split. A stronger
behavioural test would vary the view between successive slots and check which
view each frame used. The existing reference image cannot make that claim for
us.

## Give the recorder a job, not access to the renderer

With attachment ownership and uniform updates accounted for, recording can
receive their results rather than their owners. This extends the [0.9
recording-boundary argument][boundary-post]: immutable packets are useful only
if the operation consuming them is also given appropriately limited access.

The released [`ForwardRecorder` interface][source-recorder] is deliberately
concrete:

```cpp
void record(const RecordingContext& primary, std::span<const RecordingContext> secondaries,
            const ForwardRecordingInput& input, const ForwardPassTarget& target,
            ForwardPassCpuTimings* timings);
```

The recording contexts supply command pools and buffers. The immutable input
supplies resolved state and ordered draws. `ForwardPassTarget` supplies plain
colour/depth image and view handles, formats and extent. The optional timing
pointer supplies somewhere to report the work.

There is no renderer pointer, queue, allocator, mutable scene, presentation
owner or compiled-resource owner in that interface. This is not a claim that
`const` prevents Vulkan commands—the contexts exist precisely to record them.
It is a restriction on which operations the recorder has been supplied.

The [call site][source-orchestration] shows where the restriction falls:

```text
Renderer::Impl
  record shadow pass                         (released 0.10)
  reset and begin forward primary
  |
  +-- ForwardRecorder::record()
  |     choose forward participants
  |     record and join secondary chunks      (production path)
  |     transition forward attachments
  |     begin rendering, execute draws, end rendering
  |
  append capture-or-present output work
  end forward primary
  submit and present
```

The primary is already recording when the forward recorder receives it.
Beginning a command buffer and beginning a dynamic-rendering instance are
different operations. The coordinator owns the former; the recorder owns
the latter and the matching `endRendering()`. The diagnostic direct-primary
path records draws directly instead of executing secondaries, but does not
gain submission authority.

This also explains the naming changes. `ForwardPipeline`, `forward.slang`
and `ForwardRecordingInput` say which pass they serve. The [command-line
parser][source-options] rejects the old ambiguous options rather than keeping
them as aliases:

| At 0.9 | At 0.10 | What it controls |
| --- | --- | --- |
| `--direct-primary` | `--forward-direct-primary` | diagnostic forward recording directly into the primary |
| `--recording-threads` | `--forward-recording-participants` | forced forward participant count: `1` or `2`, including the coordinator |

Without an override, automatic selection uses the forward draw count. It does
not choose how many passes run concurrently. The released shadow recorder
remains serial. Two concrete recorders and explicit calls express that design
without a pass list or virtual recorder interface.

## A borrowed job must finish before its storage can disappear

The narrow signature creates a lifetime obligation. A helper receives a
copied job, but that job still borrows a recording context, draw storage and a
timing block. Copying the job does not extend those lifetimes.

The [fork-and-join scope][source-join] handles the ordinary and exceptional
paths together. After dispatch, a [`ForwardChunkJoin` guard][source-join-guard]
waits for the helper when the scope ends, including if the coordinator's own
recording throws.
Only after that join does the recorder rethrow a stored helper exception or
merge participant timings. Returning from `record()` must not leave a helper
reading storage that the caller is about to reuse.

Destruction needs the same ordering at a larger scale. The [renderer member
declarations][source-owner-order] put `ForwardRecorder` last, after the frame
resources and input compiler. C++ reverse member destruction therefore stops
and joins its helper before destroying the recording contexts and input
storage it could borrow. Presentation replacement and the renderer's idle
wait also assert that no forward helper job remains outstanding.

This is why extracting the draw loop alone would have been incomplete. The
recorder owns its helper's lifetime and completion protocol as well as the
commands. The coordinator retains the resource lifetimes that extend beyond
CPU recording into GPU execution.

## Make preservation failures observable before trusting a green run

The structure now tells us what the recorder may touch and when its borrowed
input can be released. It does not tell us whether the extraction preserved
the image, capture path or concurrent execution. Those need different checks.

First, a test must expose the failure it claims to detect. The [capture
wrapper][source-capture-wrapper] captures the child application's output,
prints it for CTest, and independently rejects `Vulkan validation error:` even
when the child exits successfully. The [test registration
helper][source-capture-registration] applies the same rejection at CTest
level, along with the Vulkan-device label, resource lock and timeout.

That matters for the constructor argument identified earlier. Initial capture
can pass even if presentation replacement forgets to request capture-capable
swapchain images. The recorded positive control changed only the replacement
constructor call to pass `false` for `captureEnabled`; initial construction
still received the real capture request.

On the reference Mac, that fault made
`fireEngineTutorialFrameCaptureRecreationCorrectness` and
`fireEngineTutorialFrameCaptureRecreationSyncValidation` fail with
transfer-source usage and layout errors. The ordinary
`fireEngineTutorialFrameCaptureCorrectness` and
`fireEngineTutorialFrameCaptureSyncValidation` cases stayed green. Restoring
the argument restored the passing suite. The [capture-recreation change and
its recorded outcome][capture-control] survive in the release history; the
temporary fault does not. The retained account identifies those error
categories, not an exact validation-message transcript.

This control distinguishes the replacement path from initial construction.
The recreation tests require capture after at least two replacements and
check the PNG's structure and reported dimensions. Because that path advances
animation using wall-clock time, it does not assert a fixed image digest.

Image preservation had a separate reference. The [committed pre-shadow
capture and its provenance][source-image-record] identify an Apple M2 Pro,
macOS 26.6, a Release/Xcode 26.6 build and the KosmicKrisp Vulkan implementation
reported as `vulkan-sdk-1.4.357.0 (git-6e2f85ffe3)`. The capture is frame three
of fixed-step AnimatedCube, at 1600 by 1200, using `B8G8R8A8Srgb` and FIFO.
The pinned vcpkg revision and PNG encoder are recorded alongside the image.

The shader rename [preserved the generated SPIR-V and reference
capture][shader-rename]. After recorder extraction, the same reference-host
capture again had SHA-256:

```text
a8fff0f2a9ea5ba650cd41c73ab7df85dd15b28b73eee5ae26a9875b41a0297e
```

That is a local preservation result, not a portable image oracle. Different
framebuffer sizes or encoder dependencies can change the file. The final 0.10
release also deliberately changes the animation pose through SLERP, so running
today's basic scenario is not a reproduction of that old digest. Capture
adds readback and a host wait; it is not timing evidence.

Portable execution supplies another, narrower check. [Catch2
registrations][source-device-free] and the [CLI rejection
tests][source-cli-tests] carry positive `device-free` labels. The macOS and
Windows [CI jobs][source-ci] select that label with `--no-tests=error`.
They execute checks instead of merely building, without claiming Vulkan
device coverage on those runners.

Nor should the early green Linux run be promoted into proof that
synchronization validation ran. Later work found that validation activation
was missing from that environment. The [release map's validation
account][map-validation] separates the eventual gate from those earlier
results. A requested validation mode and an active validator are not the
same evidence.

## An unchanged image does not establish retained overlap

The recorder extraction made one deliberate host-order change: the
coordinator begins the forward primary before dispatching the helper, rather
than after secondary recording. The [source comment at that
boundary][source-orchestration] records it. The commands and timing-category
membership were preserved; the claim is not that every host operation stayed
in its original position.

The reporting boundary follows the same separation. Forward work is reported
through `ForwardPassCpuTimings`, rather than treating all recording as the
renderer's only pass. A category can accumulate several regions:
`primaryCommandRecording` includes work around the recorder call as well as
inside it, while encoding secondary execution has its own timer. Moving code
between functions must not silently change which work a measurement counts.

That makes “two participants were selected” too weak a concurrency check.
Both could run one after the other and still produce identical commands.
Before accepting the extraction, the recorded rule required:

```text
elapsed span covering both participants' reset-and-record intervals
    < sum of their individual reset-and-record durations
```

The [timestamp merger][source-timing-merge] defines the span from the earliest
participant reset start to the latest recording end. Each participant's work
duration runs from its own reset start to its own recording end. If their
combined span is shorter than the sum, their intervals overlapped. It is not
a comparison against a one-participant control.

A narrower comparison asks whether the pool resets themselves overlap. That
was diagnostic, not the acceptance rule: scheduling can delay one short reset
until the other has finished while the larger recording intervals still
overlap.

The retained extraction-checkpoint report records a Release run with two
forced participants and 10,000 draws in the then-single-pass renderer:

| Comparison | Elapsed span | Sum of participant durations | Recorded outcome |
| --- | ---: | ---: | --- |
| Reset plus recording | 454.484 µs | 889.344 µs | intervals overlap |
| Reset alone | 135.333 µs | 238.901 µs | resets overlap in this acquisition |

Other local acquisitions did not always satisfy the reset-only comparison;
the complete-participant comparison remained satisfied. That is the reason
to keep the two rules separate rather than treating any failed reset overlap
as a failed extraction.

These are historical summary values retained from the work notebook, not a
new benchmark of tag 0.10. The summary does not explicitly identify the timing
run's host or preserve the complete raw report, per-acquisition driver
metadata, sample count or spread. It supports the recorded overlap observation,
not a general performance estimate. In particular, dividing 889.344 by 454.484
would not produce an application speedup: the numerator sums concurrent work,
not a control frame's duration.

## Check that the race detector reaches the helper

Overlap is desirable only if the two participants are safe to run together.
The join scope and separate contexts explain why they should be.
ThreadSanitizer instruments CPU memory accesses to look for data races between
threads on the paths actually exercised. It does not replace Vulkan validation
or prove that every possible execution is safe.

The extraction record reports clean one- and two-participant
`--smoke prepare-twice` runs in an ad-hoc Clang ThreadSanitizer build. The
positive control then temporarily incremented one shared non-atomic sentinel
from both participants inside `recordForwardSecondaryChunk()`, the real
chunk-recording path. The required outcome was a first-party data-race report,
not merely an application failure.

The recorded run produced that report with coordinator and helper stacks.
The sentinel was removed, the target rebuilt, and the two-participant path
ran clean again. No suppressions were used. This establishes that the
instrument could detect the deliberately introduced race on the extracted
path; it does not turn a clean production run into a proof of race freedom.

The [extraction itself][recorder-extraction] is in the release ancestry. The
temporary sentinel is not. Its exact patch, raw diagnostic and complete
sanitizer-run environment were not retained with the summary, so this remains
an author-reported control rather than a fully recoverable experiment. The
configuration and exercised commands are retained below, allowing the clean
paths to be checked independently without pretending to recreate the missing
diagnostic.

## Run the released descendants of those checks

Use the released tree rather than a moving development branch. Building needs
a C++23 compiler, CMake, Ninja and the project's vcpkg setup, with `VCPKG_ROOT`
set. Device scenarios also need a supported Vulkan implementation and window
system; the Debug validation checks require the Khronos validation layer.
The [release README][source-readme] records the platform setup.

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.10
cmake --preset vcpkg
cmake --build --preset default

ctest --preset default -L device-free --no-tests=error
ctest --preset default --no-tests=error \
  -R '^fireEngineTutorialFrameCapture(Recreation)?(Correctness|SyncValidation)$'
ctest --preset default --no-tests=error \
  -R '^fireEngineTutorialForwardSplitRecordingMixedResource(Smoke|SyncValidation)$'
```

The capture expression selects the four named capture registrations in a
Debug build. The mixed-resource expression selects the standard and
synchronization-validation versions of forced two-participant recording with
repeated preparation. These exercise the released two-pass system, not the
historical forward-only checkpoint.

For the recorded sanitizer method, use a separate Clang build:

```shell
cmake -S . -B build-tsan -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DCMAKE_CXX_FLAGS="-fsanitize=thread -fno-omit-frame-pointer" \
  -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=thread"
cmake --build build-tsan

TSAN_OPTIONS=halt_on_error=1:abort_on_error=0:exitcode=66 \
  ./build-tsan/fireEngineTutorial --smoke prepare-twice \
  --forward-recording-participants 1
TSAN_OPTIONS=halt_on_error=1:abort_on_error=0:exitcode=66 \
  ./build-tsan/fireEngineTutorial --smoke prepare-twice \
  --forward-recording-participants 2
```

These commands include the later 0.10 verification correction
`abort_on_error=0`, so Darwin's default abort does not override the requested
error exit code. [LLVM's own test setup][source-sanitizer-options] also disables
that default; it was not part of the original extraction commands.

This build does not instrument every external driver component. Record the
environment and any external reports rather than silently suppressing them.
If suppressions are necessary, a repeated sentinel control must still detect
the first-party race.

For the overlap fields, use a separate uninstrumented Release build, without
capture or validation instrumentation:

```shell
cmake --preset vcpkg -B build-benchmark -DCMAKE_BUILD_TYPE=Release
cmake --build build-benchmark --target fireEngineTutorial
./build-benchmark/fireEngineTutorial --benchmark 10000 \
  --forward-recording-participants 2
```

At 0.10 this requests 10,000 synthetic instances, each contributing a shadow
and a forward draw. Compare the forward participant span with the sum of
forward reset and recording durations in that report. Do not compare its
absolute values with the historical table as if the workload and environment
were unchanged, or use this single run to decide whether the helper earns its
cost. That is a separate controlled measurement.

## The second pass gets a place, not a general-purpose framework

The useful result is not that `renderer.cpp` became shorter. Presentation
replacement has an explicit owner. Synchronization no longer owns shader
layout. The forward recorder can encode its pass and manage its helper without
being able to replace the resources it borrows or submit the commands it
produces.

Those boundaries explain where the released shadow map and recorder belong.
They do not make the second pass free of shared changes: the uniform payload,
frame description, input compilation and submission still have to describe a
two-pass frame. The [0.10 architecture][architecture-0-10] records that final
structure.

The next question in the [release map][map-inputs] is therefore narrower and
answerable: can one scene snapshot produce two restricted recording inputs,
without each pass independently resolving the scene? The ownership work gives
that question a stable place to start. The preservation checks give us
specific reasons to trust the move—and explicit limits on what that trust
covers.

## Recommended reading

- [C++ Software Design][reading-design] — managing dependencies and reasons
  for change without treating more abstraction as an end in itself.
- [Refactoring][reading-refactoring] — behaviour-preserving structural
  changes, and the checks needed to distinguish them from feature changes.
- [Vulkan specification: Command Buffers][reading-command-buffers] — command
  buffer lifecycles and the distinction between primary and secondary
  recording underlying the recorder boundary.

These references are also on the [Reading page][reading-page].

[release-0-10]: {{ page.release_url }}
[architecture-0-10]: {% link _architecture/0.10.md %}
[map-responsibilities]: {% post_url 2026-10-15-mapping-fireengines-path-to-directional-shadows %}#which-responsibilities-must-be-separate-before-adding-another-pass
[map-inputs]: {% post_url 2026-10-15-mapping-fireengines-path-to-directional-shadows %}#can-one-scene-produce-two-restricted-views-without-a-second-lookup
[map-validation]: {% post_url 2026-10-15-mapping-fireengines-path-to-directional-shadows %}#how-can-we-tell-an-image-limitation-from-an-animation-or-lifetime-defect
[boundary-post]: {% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-old-presentation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L112-L175>
[source-presentation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/presentation_state.hpp#L27-L92>
[source-presentation-constructor]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/presentation_state.cpp#L15-L44>
[source-recreation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/renderer.cpp#L674-L693>
[source-old-slot]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/frame_slot.hpp#L18-L68>
[source-slot]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/frame_slot.hpp#L14-L54>
[source-uniform]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/frame_uniform_buffer.hpp#L17-L53>
[source-frame-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/frame_resources.hpp#L17-L42>
[source-slot-update]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/renderer.cpp#L438-L492>
[source-recorder]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/forward_recorder.hpp#L19-L92>
[source-orchestration]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/renderer.cpp#L516-L591>
[source-options]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/app/main.cpp#L666-L725>
[source-join]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/forward_recorder.cpp#L453-L538>
[source-join-guard]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/forward_recorder.cpp#L104-L127>
[source-owner-order]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/renderer.cpp#L208-L228>
[source-capture-wrapper]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tests/cmake/run_frame_capture.cmake#L41-L61>
[source-capture-registration]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/CMakeLists.txt#L544-L620>
[source-image-record]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/docs/images/README.md#010-step-0-animated-cubepng>
[capture-control]: <https://github.com/nnewson/fireEngine-tutorial/commit/5c0f516c9d6cc433d5f2e85fc45b6908f5307751>
[shader-rename]: <https://github.com/nnewson/fireEngine-tutorial/commit/10677c118ab767f79b5f0c7c4b27f639f3d4855f>
[recorder-extraction]: <https://github.com/nnewson/fireEngine-tutorial/commit/7634758e27bd2b267db208aeff7a0ec4a25615fb>
[source-device-free]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/CMakeLists.txt#L358-L362>
[source-cli-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/CMakeLists.txt#L812-L833>
[source-ci]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/.github/workflows/ci.yml#L396-L451>
[source-timing-merge]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/forward_recorder.cpp#L272-L323>
[source-readme]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.10/README.md>
[source-sanitizer-options]: <https://github.com/llvm/llvm-project/blob/d85b869314501fd446ff50b8a937eaa017d0ea62/compiler-rt/test/lit.common.cfg.py#L932-L936>
[reading-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-refactoring]: <https://martinfowler.com/books/refactoring.html>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
