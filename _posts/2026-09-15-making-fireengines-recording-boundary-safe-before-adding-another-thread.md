---
title: "Making fireEngine's recording boundary safe before adding another thread"
date: 2026-09-15 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, ownership, vulkan, cpp]
description: >-
  Freeze one frame into immutable recording input while keeping resource
  ownership, submission, and presentation on the coordinating thread.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

The [CPU-measurement post][cpu-measurement-post] locates the region another
recording participant might shorten: reset that participant's command pool,
then record its share of the secondary commands. A timing result cannot show
whether that work is safe to hand elsewhere. It cannot prove that the input
will remain valid, that a supposedly read-only value lacks owner operations,
or that another thread has no route to submit incomplete work.

fireEngine therefore turns the measured phase boundary into an authority and
lifetime boundary before it introduces concurrent recording. Resource
construction is separated from stable resource ownership. Submission slots
are separated from recording contexts. The scene produces an immutable view
over explicitly owned storage, and a compiler resolves that view into the only
handles and values command recording needs.

The result is `RecordingInput`: a compiler-produced, non-copyable value that
exists inside one `drawFrame()` transaction. It contains no queue, allocator,
command pool, fence, live scene, renderer implementation, or Vulkan RAII owner.
Those absences are the point. A recording participant receives enough
authority to encode its range and nothing that lets it replace resources,
submit commands, or present an image.

This post answers the boundary question in the [0.9 release map][map-post]. The
[0.9 architecture page][architecture-0-9] records the resulting ownership
tree; the argument here is why those particular cuts make the later worker
experiment possible.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Measurement prerequisite: [the CPU-measurement post][cpu-measurement-post]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
{: .prompt-info }

## Introducing the ownership and lifetime vocabulary

Four terms keep distinct questions from collapsing into “make it `const`”:

- a **recording participant** is one CPU thread that resets its own command
  pool and records one range of secondary commands;
- the **coordinator** is the main rendering thread. It records the primary
  command buffer and retains submission and presentation authority;
- a **capability boundary** gives a consumer only the data and operations its
  role requires, rather than a read-only view of a more powerful owner; and
- a **frozen frame** has completed scene mutation, transform resolution, and
  resource lookup. Recording consumes an immutable representation of that
  state rather than revisiting the live scene.

A **frame slot** is different from a recording participant and from a
swapchain image. It owns synchronization and uniform storage for one submitted
frame. The final renderer has two frame slots, one or two recording
participants, and a driver-selected number of swapchain images. None of those
counts determines either of the others.

The [Terminology page][terminology-page] collects these definitions for the
rest of the 0.9 series.

## Turn the measured region into an authority boundary

The phase measurement identifies work, but the ownership design starts by
listing authority:

| Recording participant may | Coordinator alone may |
|---|---|
| read immutable frame and draw packets | compile or replace GPU resources |
| reset its own command pool | record the primary command buffer |
| record its own secondary command buffer | submit work and own submission fences |
| bind supplied handles and encode draws | acquire and present swapchain images |

That division is narrower than “the worker receives the renderer.” Passing a
`Renderer::Impl&`, a device wrapper, or a compiled-resource owner would make
the desired behaviour a convention imposed on a type that permits much more.
The later recording function should not need a comment warning it away from
submission or destruction APIs; those APIs should be unreachable from its
inputs.

`RecordingContext` makes the recording half concrete. It owns one externally
synchronized command pool and, when requested, one primary or secondary
command buffer. It owns no queue, allocator, submission fence, or frame-slot
state. Resetting the pool is therefore the participant's first recording
operation, while the coordinator retains everything required to submit the
finished primary. See the [`RecordingContext` boundary][source-recording-context].

```text
coordinator
├── primary RecordingContext
├── submission FrameSlot
├── queues and presentation
└── recording-input compiler
              |
              v
recording participant
├── secondary RecordingContext
└── immutable RecordingInput
```

This is an ownership claim, not a performance claim. No timing can establish
that the participant lacks a queue; the type's members and the function
signatures can.

## Keep construction separate from stable ownership

The next dependency runs in the other direction. Recording packets can borrow
plain Vulkan handles only if some stable graph continues to own the buffers,
images, views, and samplers behind them.

`ResourceCompiler` owns the temporary machinery needed to build that graph: an
upload command pool, command buffer, fence, and staging allocations. Its
`compile()` operation constructs a complete candidate
`CompiledResourceGraph`. `CompiledResources` owns the accepted graph and can
replace it only as a whole after earlier GPU work has retired.

That separates three roles which would otherwise be easy to conflate:

| Role | Type | Lifetime |
|---|---|---|
| build and upload a candidate | `ResourceCompiler` | renderer lifetime, reused between preparations |
| retain the accepted Vulkan owners | `CompiledResources` | until safe replacement or renderer destruction |
| look up compiled draw packets | `CompiledResourcesView` | only while the current graph is stable |

The restricted view is privately constructed by `CompiledResources`. Its one
operation, `find(RenderObjectId)`, returns a `CompiledDraw` by value. That
packet contains plain handles and draw values, not the RAII objects that own
them. The input compiler can resolve IDs without acquiring resource replacement
or destruction authority. See the [compiler's upload ownership][source-resource-compiler]
and the [stable owner and restricted view][source-compiled-resources].

```text
RenderAssets + RenderPreparationPlan
                 |
                 v
          ResourceCompiler
                 |
                 v
     candidate CompiledResourceGraph
                 |
                 v
       CompiledResources owner
                 |
                 v
       CompiledResourcesView
        packet lookup only
```

Moving a plain handle into a packet does not extend the Vulkan resource's
lifetime. The owner graph still has to survive until submitted GPU work is
finished. The view narrows authority; the renderer's retirement protocol
supplies lifetime.

## Pay the ownership debts that measurement did not create

Not every ownership change follows from the phase report. The
[0.8 architecture][architecture-0-8] already records two limitations: setup
uploads borrow the sole frame slot, and the renderer has only one frame in
flight. Both need attention even if another recording thread is never added.

The dedicated `ResourceCompiler` removes setup uploads from submission-frame
state. Separately, the renderer cycles through two `FrameResources` groups.
Each group contains one `FrameSlot`, the coordinator's primary
`RecordingContext`, and the secondary recording contexts. The frame slot owns
its uniform buffer, image-available semaphore, submission fence, and
pending-work state; presentation owns one extent-matched depth attachment per
slot.

```text
renderer
├── ResourceCompiler
│   └── upload pool + buffer + fence
├── FrameResources 0
│   ├── FrameSlot 0
│   ├── coordinator RecordingContext 0
│   └── secondary RecordingContexts 0
└── FrameResources 1
    ├── FrameSlot 1
    ├── coordinator RecordingContext 1
    └── secondary RecordingContexts 1
```

The renderer can now let one submitted frame remain on the GPU while preparing
the next slot, without constructing two CPU scene snapshots concurrently.
Cycling the submission slot is independent of whichever swapchain image the
driver returns. The final [`FrameResources` grouping][source-frame-resources]
and [`FrameSlot` owner][source-frame-slot] encode those independent identities.

These changes are a parallel branch of the argument, not evidence that the
phase measurements demanded two frames. They matter to the worker experiment
because they change the one-participant production path. Once they land, an
earlier timing baseline no longer describes the code that a second participant
would join. A rebaseline becomes necessary rather than merely desirable.

## Give the scene snapshot an explicit owner

The scene previously returned an owning vector of draw items to the renderer.
That representation was safe but encouraged each frame to allocate and transfer
ownership for data used only during CPU preparation and recording.

`SceneDrawListArena` instead owns reusable contiguous storage. A
`SceneDrawList` is a small value containing a read-only span over that storage
and the dependency hash used by preparation. Building another list clears the
logical contents while retaining the allocation, so the arena cannot be copied
or moved while a view may refer into it.

The lifetime rule is explicit: a draw-list span remains valid until its arena
builds another list or is destroyed. Copying the span does not extend that
lifetime. The application therefore owns the arena, updates transforms, builds
one snapshot, and passes its view into `prepare()` or `drawFrame()`. The
renderer no longer needs access to the mutable `Scene`. See the
[`SceneDrawList` and its arena][source-scene-draw-list].

The crucial question is whether the GPU later reads that CPU span. It does not.
The span supplies render-object IDs and world transforms while the recording
input is compiled. The next stage copies the transform and resolved handles
into its own packet arena. Command recording then copies push-constant values
into the command buffer and records references to separately owned GPU
resources. No submitted command contains an address into the scene arena.

That distinction permits the application to rebuild the arena after
`drawFrame()` returns even while an earlier submitted frame is still executing.
The CPU view may expire; the GPU resources named by the recorded handles may
not.

## Compile the only input recording can see

An immutable span is still not proof that its contents are prepared. A caller
could assemble `DrawItem` values containing unknown render-object IDs, and a
recording function that accepted the span would still need access to the
compiled-resource lookup and compatibility rules.

`RecordingInputCompiler` closes that gap before acquisition and recording. For
every draw item it resolves the render-object ID through
`CompiledResourcesView`, rejects an absent object, proves that the compiled
vertex layout matches the active pipeline, and copies a complete
`RecordingDraw` into reusable storage:

```cpp
draws_.clear();
for (const DrawItem& item : drawList.drawItems)
{
    const std::optional<CompiledDraw> compiledDraw = resources.find(item.renderObject);
    if (!compiledDraw.has_value())
    {
        throw std::logic_error("Scene refers to an object not compiled by prepare");
    }
    const CompiledDraw& draw = compiledDraw.value();
    if (draw.vertexLayout != state.vertexLayout)
    {
        throw std::logic_error("Compiled draw is incompatible with the recording pipeline");
    }
    draws_.push_back({
        .vertexBuffer = draw.vertexBuffer,
        .indexBuffer = draw.indexBuffer,
        .indexCount = draw.indexCount,
        .sampler = draw.sampler,
        .imageView = draw.imageView,
        .constants =
            {
                .model = item.world,
                .baseColor = draw.baseColor,
            },
    });
}
return RecordingInput{state, draws_};
```

The renderer constructs `RecordingState` from the pipeline, layout, slot-local
uniform-buffer handle, camera-derived frame uniforms, viewport, scissor,
attachment formats, and vertex-layout proof. The compiler freezes that state
beside its resolved draws. See the [compiler implementation][source-recording-compile]
and the state construction inside the [`drawFrame()` transaction][source-frame-transaction].
Command recording no longer performs resource-ID lookup or pipeline
compatibility checks.

The produced type makes its provenance visible:

```cpp
class RecordingInput final
{
public:
    ~RecordingInput() = default;

    RecordingInput(const RecordingInput&) = delete;
    RecordingInput& operator=(const RecordingInput&) = delete;
    RecordingInput(RecordingInput&&) = delete;
    RecordingInput& operator=(RecordingInput&&) = delete;

    [[nodiscard]] const RecordingState& state() const noexcept;
    [[nodiscard]] std::span<const RecordingDraw> draws() const noexcept;

private:
    friend class RecordingInputCompiler;

    RecordingInput(RecordingState state, std::span<const RecordingDraw> draws) noexcept;

    RecordingState state_;
    std::span<const RecordingDraw> draws_;
};
```

Only `RecordingInputCompiler` can call the private constructor. The value is
neither default-constructible, copyable, nor movable, so it is materialized
directly as the local result of compilation instead of being passed around as
general renderer state. Its [complete declaration][source-recording-input]
contains plain handles and trivially copyable values rather than RAII owners.

## Close the lifetime chain inside one frame transaction

The restricted types matter only if their borrowers cannot outlive their
owners. fireEngine supplies that guarantee through the ordering of one
serialized `drawFrame()` call:

```text
build SceneDrawList in its arena
                 |
                 v
compile IDs + state into RecordingInput
                 |
                 v
record every secondary command range
                 |
                 v
join every CPU recording participant
                 |
                 +--> packet and scene arenas may be reused
                 v
submit the primary command buffer
                 |
                 v
retain GPU owners until slot retirement
```

Public operations on one `Renderer` are not concurrent. `drawFrame()` creates
the input after selecting a frame slot and consumes it before that transaction
continues. The final worker joins before the input compiler can be reused.
Neither `prepare()` nor presentation replacement can interleave and invalidate
the compiled-resource or pipeline handles during recording.

The [secondary recording path][source-participant-join] makes the join part of
the scope that consumes `RecordingInput`, including exception unwinding from
the coordinator's own recording range.

After submission, the `RecordingInput` itself may disappear. Slot fences and
the renderer's wait-before-replacement rule keep the actual buffers, images,
views, samplers, pipeline, and uniform storage alive until GPU work has
finished. This gives the three borrowed layers different, deliberate endpoints:

| Borrowed value | Needed until | Owner that remains |
|---|---|---|
| `SceneDrawList` span | recording-input compilation finishes | application `SceneDrawListArena` |
| `RecordingInput` draw span | all CPU recording participants finish | renderer `RecordingInputCompiler` |
| Vulkan handles recorded into commands | submitted GPU work retires | compiled graph, presentation, and frame slot |

The [`drawFrame()` transaction][source-frame-transaction] puts compilation
before image acquisition, waits for the selected slot before rewriting its
uniforms, records every participant, and submits only after recording is
complete. Lifetime is supplied by that complete sequence, not by a generation
number attached to an otherwise stale packet.

## Use structural evidence for a structural claim

The boundary does not need a speedup to be correct. Its strongest checks ask
whether invalid authority and lifetime arrangements are representable:

- compile-time assertions establish that `RecordingInput` cannot be defaulted,
  copied, or moved, while its fixed state and draw packets remain trivially
  copyable;
- device-free tests compile fake plain handles into ordered packets, preserve
  transforms and material values, reuse packet storage, and reject missing or
  pipeline-incompatible draws;
- scene tests establish that the arena is immovable, its view is read-only,
  order is stable, and rebuilding can reuse its allocation; and
- device scenarios exercise preparation replacement, presentation recreation,
  mixed resources, one- and two-participant recording, and synchronization
  validation against the final ownership path.

The [recording-input tests][source-recording-tests] and
[scene-arena tests][source-scene-tests] need no Vulkan device because they
check provenance, values, and storage rules rather than driver behaviour. The
device scenarios then cover the point where those values become submitted
commands.

This is what it means to justify the boundary without timing it. A faster run
could coexist with a dangling span or excess authority. The type restrictions,
transaction order, focused tests, and validation address those uncertainties
directly.

## Keep the nearby optimization question separate

Introducing the draw-list arena exposed a different question: would replacing
recursive transform traversal with one flat pass over parent IDs make snapshot
construction faster? That question does require measurement, but its answer
does not determine whether the arena lifetime is safe.

The bracketed Lavapipe experiment found no resolved change at 1,000 draws and a
resolved 18.80% regression at 10,000. The flat pass took 371.670 us against a
312.858 us mean recursive control, with 19.040 us of control drift. The parent
registry, flat traversal, command-line control, and dedicated test were removed;
the immutable arena remained.

The [flat-transform implementation][flat-transform-source] remains reachable
through the release ancestry. The [removal commit][flat-transform-removal]
records the decision taken after the [CI run][flat-transform-ci]. The narrow
conclusion is that removing recursion did not help the existing pointer-based
scene layout. It says nothing about a future contiguous transform layout, and
nothing about the correctness of the recording boundary.

Keeping the two decisions separate is important. Measurement rejected an
optimization. Lifetime and capability reasoning retained the ownership change
that made the experiment possible.

## Rebaseline only after the boundary is real

The candidate recording region now has an explicit owner, immutable input, and
a transaction that ends every CPU borrow before its storage is reused. The
inherited upload and frame-slot changes have also altered the production path.
Only now can the one-participant renderer be measured as the denominator for a
two-participant prediction.

That later rebaseline does not retroactively justify these types. It answers a
new question: after paying for the serial recording-input compiler and the
final ownership structure, is enough reset and recording work still available
to make another participant plausible?

The distinction closes this part of the chain:

```text
phase measurements locate candidate work
                 |
                 v
ownership + lifetime make it safe to hand off
                 |
                 v
new production baseline prices the final boundary
                 |
                 v
worker experiment may begin
```

fireEngine has not assumed that immutable data is automatically safe, or that
a safe boundary is automatically fast. It has used different evidence for
each claim. The [rebaseline post][rebaseline-post] measures the completed
one-participant path and decides whether the worker experiment is worth
attempting.

## Run the boundary checks

The final 0.9 tree contains the retained arena, recording-input compiler,
separate owners, and the device scenarios that compose them:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg
cmake --build --preset default

./build/fireEngineTutorialTests "Recording input*"
./build/fireEngineTutorialTests \
  "Scene resolves transforms and emits draw items depth first"

ctest --test-dir build -R \
  "^(fireEngineTutorialPrepareTwiceSmoke|fireEngineTutorialRecreationSmoke|fireEngineTutorialSplitRecordingMixedResourceSmoke)$" \
  --output-on-failure

ctest --test-dir build -R \
  "(PrepareTwice|Recreation|SplitRecordingMixedResource)SyncValidation$" \
  --output-on-failure
```

The focused tests establish the device-free type and arena contracts. The
bounded scenarios require a working Vulkan device and exercise the ownership
chain through submission, resource replacement, and presentation recreation.
The synchronization-validation registrations are present in Debug builds and
set `VK_LAYER_VALIDATE_SYNC=1` themselves.

## Recommended reading

- [C++ `std::span` reference][reading-span] — the non-owning view used by both
  scene draw lists and compiled recording packets, including the lifetime
  obligations it deliberately does not solve.
- [C++ Software Design][reading-cpp-design] — the dependency and interface
  background for giving a consumer a narrow capability instead of an entire
  owner.
- [Vulkan specification: Command Buffers][reading-command-buffers] — the pool,
  recording, execution, and external-synchronization rules behind each
  `RecordingContext`.
- [Vulkan specification: Push Descriptors][reading-push-descriptors] — the
  descriptor commands recorded from the frozen packets and the resource
  lifetimes that continue after their CPU descriptions expire.

The [Reading page][reading-page] keeps the site-wide list in one place, and the
[Terminology page][terminology-page] collects the project-specific vocabulary
used here.

[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[cpu-measurement-post]: {% post_url 2026-09-13-measuring-fireengines-cpu-work-before-adding-another-thread %}
[rebaseline-post]: {% post_url 2026-09-18-rebaselining-fireengine-before-adding-another-recording-thread %}
[architecture-0-8]: {% link _architecture/0.8.md %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-recording-context]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/recording_context.hpp#L26-L77>
[source-resource-compiler]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/resource_compiler.hpp#L21-L71>
[source-compiled-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/compiled_resources.hpp#L16-L73>
[source-frame-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L100-L110>
[source-frame-slot]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/frame_slot.hpp#L18-L68>
[source-scene-draw-list]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/scene/scene_draw_list.hpp#L13-L52>
[source-recording-compile]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/recording_input.cpp#L29-L60>
[source-recording-input]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/include/fire_engine/render/detail/recording_input.hpp#L23-L120>
[source-frame-transaction]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L579-L692>
[source-recording-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/tests/render/test_recording_input.cpp#L65-L160>
[source-scene-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/tests/scene/test_scene.cpp#L27-L80>
[source-participant-join]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L834-L910>
[flat-transform-source]: <https://github.com/nnewson/fireEngine-tutorial/blob/8ac5ea5/src/scene/scene.cpp#L105-L117>
[flat-transform-removal]: <https://github.com/nnewson/fireEngine-tutorial/commit/e1456e3>
[flat-transform-ci]: <https://github.com/nnewson/fireEngine-tutorial/actions/runs/33218321920>
[reading-span]: <https://en.cppreference.com/w/cpp/container/span>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
[reading-push-descriptors]: <https://docs.vulkan.org/spec/latest/chapters/descriptorsets.html>
