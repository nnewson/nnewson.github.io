---
title: Mapping fireEngine's path to directional shadows
date: 2026-10-15 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.10", 3d-engine, architecture, rendering, synchronization, performance, benchmarking, vulkan, cpp]
description: >-
  A map of the ownership, image, lifetime and measurement questions behind
  fireEngine 0.10's two-pass directional-shadow renderer, including the limits
  its evidence leaves unresolved.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.10"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
---

Version 0.9 asked whether fireEngine could divide command recording between
two CPU threads without giving either thread more authority than it needed.
Version 0.10 asks a different question: can that renderer support a pass that
produces an image for another pass to consume?

The visible result is a directional shadow. AnimatedCube casts onto a
procedural ground plane; the plane receives shadows but does not cast them.
The renderer first draws depth from the light's view, then samples that image
while drawing the camera view. The feature is deliberately small: one light
view, one fixed-resolution map per frame slot, and two explicit passes.

That description leaves the difficult parts open. Which resources belong to a
frame slot rather than a window size? What may each recorder read? What makes
the depth writes safe to sample? And when the image looks wrong, how do we
distinguish an animation problem, a sampling limitation and an image being
overwritten while another frame still reads it?

The work exposed all three kinds of uncertainty. Rotation interpolation needed
correction. Removing slope-scaled depth bias failed to fix the visual defect
it was meant to explain. A green Linux suite turned out not to establish that
validation was active. The new performance measurements also left one policy
result unresolved rather than confirming the old answer on both drivers.

Version 0.10 is already released. This is a map of the questions and evidence
that delivered it, and of the posts still to come—not a prospective promise
that the implementation will follow a tidy plan. The useful architectural
claim is that two restricted pass inputs and explicit resource lifetimes make
the dependency understandable and testable. It is not that another pass
required no shared changes, or that it should immediately get another thread.

> Starting point: [fireEngine 0.9 architecture][architecture-0-9]
>
> Released source: [fireEngine 0.10][release-0-10]
>
> Released architecture: [fireEngine 0.10 architecture][architecture-0-10]
>
> The upcoming posts will follow the methods used to answer these questions.
> Five questions here do not prescribe five posts: a distinct investigation
> may need its own explanation, while related decisions can share one.
{: .prompt-info }

## Introducing the shadow and evidence vocabulary

The [Terminology page][terminology-page] collects the full definitions. These
are the distinctions the release depends on.

A **shadow map** is a depth image rendered from the light's view. It records
the nearest surfaces seen along that view's rays. The camera-view shader
projects a surface into the light's view and compares its depth with the map
to decide whether something blocks the light.

A **caster** contributes geometry to that depth rendering. A **receiver** uses
the resulting map when it is shaded. Those are independent roles: the cube
does both, while the ground plane only receives. In fireEngine 0.10 every
forward draw receives shadows; `castsShadow` controls inclusion in the shadow
pass, not visibility in the camera view.

The light's **frustum** is the volume its projection covers. Here the light
uses an orthographic projection, so that volume is a box rather than a
perspective camera's widening volume. A fixed box cannot cover every possible
scene. Positions outside it are treated as lit by this shadow lookup.

**Depth bias** adjusts the depths being compared to reduce incorrect
self-shadowing caused by finite precision and sampling. **Slope-scaled depth
bias** grows with a primitive's depth slope across framebuffer pixels. The
release applies constant and slope-scaled bias when rendering the map, plus a
separate small offset to the receiver's comparison depth. They affect the
comparison at different places; neither supplies a normal-based lighting model.

A **pass input** is the immutable set of values and borrowed handles supplied
to one recorder. It gives the recorder enough information to issue commands
without exposing a mutable scene, allocator, submission queue or resource
owner. Its CPU storage must remain valid until recording finishes; the GPU
resources it names must survive the submitted work.

**Publication** is the name used here for the GPU dependency that makes shadow
depth writes available and visible to later sampling. It is not publication
of a C++ object, an ownership transfer, or a replacement for waiting before
reusing an image.

Two other counts remain separate. A **frame slot** holds resources reused
after an earlier submission finishes. A recording **participant** is a CPU
thread recording forward draws: the coordinating thread, optionally joined by
one helper. Two slots do not imply two passes record concurrently. In 0.10 the
CPU records shadow commands first, then forward commands; only forward
recording may be divided between participants.

## Why these questions follow this order

Before asking whether an image is safe to sample, we need to know who owns it,
when that owner may reuse it, and which recorder receives its handle. Before
claiming a test detected a broken dependency, we need a way to observe the
access and turn its violation into a failure. Performance then evaluates that
qualified two-pass path, not the earlier one-pass renderer.

```text
separate responsibilities
           |
           v
compile restricted pass inputs
           |
           v
establish write-to-sample and reuse rules
           |
           v
test images, dependencies and replacement
           |
           v
measure the completed two-pass path
```

This is a reading dependency, not a commit itinerary. The ownership work does
not become correct because a picture looks plausible. A clean run cannot
establish a synchronization rule if the validator never ran. And the old
one-pass baseline cannot price the new workload merely because both reports
contain a row called command recording.

Within the fourth question, image comparison and deliberate faults are
complementary methods, not stages that must always follow each other. Their
results meet when deciding what the released renderer actually establishes.

## Which responsibilities must be separate before adding another pass?

The [0.9 architecture][architecture-0-9] already separates compiled assets,
uploads, frame submission and immutable recording input. It does not yet give
every responsibility that 0.10 needs its own owner. Presentation-dependent
state, per-slot uniform storage and forward recording still need clearer
boundaries before shadow resources can fit alongside them.

The useful distinction is why each group changes:

| Responsibility | What changes it | Released boundary |
| --- | --- | --- |
| Swapchain-compatible resources | presentation replacement | `PresentationState` |
| Submission synchronization | reuse of a frame slot | `FrameSlot` |
| Camera and light matrices | the current application's views | per-slot `FrameUniformBuffer` storing `FrameUniforms` |
| Forward command recording | the selected forward draws and participant count | `ForwardRecorder` |
| Shadow depth and recording | the selected slot and caster input | slot-local maps and `ShadowRecorder` |

The [renderer][source-renderer] still coordinates those groups. Extracting a
recorder does not give it permission to submit work or replace resources.
Likewise, moving uniform storage out of submission synchronization lets both
passes share camera/light data without making `FrameSlot` responsible for
shader layout.

This produces a concrete replacement rule. Resizing the window replaces
surface-compatible state, but not fixed-size shadow maps. Changing the scene's
compiled resources is another operation again. The maps survive presentation
replacement because their owner and dimensions are independent of it—not
because a resize test happened to leave them untouched once.

The supporting post will explain how the responsibility audit was checked
against preserved behaviour. That includes diagnostic names: the old
`--direct-primary` and `--recording-threads` options become explicitly
forward-scoped options, rather than ambiguously describing the whole renderer.

It also includes the portable test gate. Positive `device-free` labels let
macOS and Windows execute the engine and CLI checks without claiming device
coverage on their CI runners. A refactor that merely still builds on those
platforms would provide weaker preservation evidence than running the same
device-free suite.

This is not a story in which the old boundaries absorb every change unchanged.
Frame descriptions, uniform layout, cast participation and submission all
change. Separating their responsibilities makes those shared changes visible
before asking what each pass is allowed to consume.

## Can one scene produce two restricted views without a second lookup?

Once the owners are distinct, the next question is how to feed the recorders
without making each independently traverse the scene and resolve resources.
Two consumers need different data, but they must describe the same frame.

The application supplies a [frame description][source-frame] containing its
camera and directional-light views. The light uses an orthographic matrix;
the renderer does not invent the light's position or fit its bounds to the
scene. Camera and light view-projection matrices share one uniform contract,
with storage for each frame slot.

The [frame-input compiler][source-input] walks the scene draw list once. For
each item it resolves the prepared render object once, appends a forward
packet, and appends a shadow packet only if that object casts shadows. The
forward packet includes geometry, material handles and colour data. The shadow
packet contains geometry and the model transform, with no material dependency.

The distinction can be tested without a device. With a non-caster between two
casters, the expected sequences are:

```text
scene draw list:   caster A, receiver B, caster C
forward packets:  A, B, C
shadow packets:   A, C
```

That example checks identity and order, not merely a smaller shadow count.
Filtering the wrong object could still produce two shadow packets. The
[frame-input tests][source-input-tests] exercise the selection and the shared
geometry-layout requirements, while the input types restrict what each
recorder can access.

The compiler finishes growing both packet arrays before creating their spans.
Those spans borrow compiler storage for CPU recording; they do not extend its
lifetime. They also do not own the buffers or images named by their handles.
The renderer must keep both kinds of storage alive for their respective users.

This work builds on the [0.9 recording-boundary post][boundary-post], but the
new argument is not just “the input is const”. A shadow recorder cannot obtain
material state through its packet type, and neither pass input exposes the
mutable scene or submission authority. Restricted data and explicit lifetime
rules do different jobs.

These tests and restrictions establish what the two passes record. They cannot
establish that the GPU sees the map's new contents when the forward shader
samples it.

## What makes the shadow map safe for the forward pass to sample?

The released renderer has two frame slots and one 1024-by-1024 shadow map per
slot. A slot's map must survive both the depth writes that populate it and the
forward reads that consume it. Completing only the shadow pass would not make
that image safe to overwrite.

The [shadow recorder][source-shadow] therefore starts from a specific
precondition: the selected slot's submission fence has retired all earlier
use, including sampled reads. It can then discard the old contents and
transition the image for depth attachment access.

```text
slot fence retires previous writes AND sampled reads
                         |
                         v
discard old contents; render new shadow depth
                         |
                         v
publish depth writes for fragment-shader sampling
                         |
                         v
forward pass samples the selected slot's map
```

After depth rendering, a barrier connects early/late depth-attachment writes
to fragment-shader sampled reads and transitions the image to a read-only
depth layout. The renderer submits the shadow and forward primary command
buffers together, in that order. Submission order alone is not the memory
dependency; the barrier supplies the required access scopes.

The forward side has its own obligation. Every command buffer that issues
forward draws must establish the shadow descriptor, including both
participants' secondary command buffers. Binding it only in the primary would
not supply the secondaries with their required state. The
[forward recorder's fixed bindings][source-bindings] include the selected
slot's map alongside the shared uniform buffer.

Other choices make the image contract explicit. [Format selection][source-policy]
requires both sampled-image and depth-attachment support, preferring D32Sfloat
and falling back to D16Unorm. The [comparison sampler][source-sampler] uses
nearest filtering, less-or-equal comparison and an opaque-white border. Outside
the light volume, the lookup treats the receiver as lit.

The two passes also agree on coordinates. Both use negative-height viewports;
the [forward shader][source-shader] maps projected light X/Y to texture
coordinates with `(0.5*x + 0.5, 0.5 - 0.5*y)`. Changing that mapping independently
of the viewport would change which part of the map a surface samples.

The upcoming explanation will follow this specific dependency rather than
introduce a general render graph. Two concrete recorders, an ordered submission
and an image barrier are enough for this release. There is no inter-pass
semaphore or simultaneous CPU recording of the two passes. Those are possible
future design choices, not requirements inferred from having two passes.

## How can we tell an image limitation from an animation or lifetime defect?

A good-looking frame, a quiet validation log and a passing process exit answer
different questions. The investigations need to establish their observation
mechanisms before using any of those results as evidence.

Deterministic capture makes selected poses repeatable. Validation needs an
active layer, the relevant access tracking, visible diagnostics and a test
gate that rejects errors. Neither mechanism replaces the other: a wrong but
valid image descriptor can produce incorrect content without violating Vulkan.

### First make the observation trustworthy

Image comparison exposed a build prerequisite. Selecting a pinned Vulkan
package in CMake did not establish that the compiler consumed its headers;
an installed SDK could take precedence. The retained [header-selection
repair][source-build] makes the selected headers effective and compiles a
version guard with the consuming targets' flags. Include traces identify the
actual files; a version assertion alone cannot distinguish two files reporting
the same version.

Validation had two separate gaps. The [capture-wrapper repair][wrapper-commit]
made child validation errors affect the enclosing test. Later, during Linux
close-out, a green suite lacked evidence that the Khronos layer had been
loaded at all. The [merged Linux gate][validation-commit] now checks activation
for each device test and exercises missing-layer and restored-layer controls.
The [released runner][source-validation] is inspectable code, not a promise
that setting an environment variable must have enabled validation.

There is a separate, temporary experiment: [PR #84][probe-pr] removed the
publication barrier's destination scope. It was closed without merging and
is not in the release ancestry. The recorded Linux run reported `READ_AFTER_WRITE`
hazards: all 13 synchronization cases failed, while all 23 ordinary device
cases and 111 device-free cases passed. That is an author-reported experiment,
not a result recoverable by checking out the tag. Its detailed post needs the
exact patch, commands, environment, diagnostics and restoration record; the PR
is supplemental context, not the permanent substitute for those details.

### Hold the pose before blaming the shadow

Rotation initially used normalised linear quaternion interpolation. The move
to spherical interpolation corrected its pacing, but also changed which pose
appeared at a given capture ordinal. Comparing the same numbered frames across
that change could falsely attribute a pose difference to shadow rendering.
The [released playback code][source-animation] and [accepted image notes][source-images]
provide the resulting implementation and reference provenance.

Same-binary captures still had to repeat byte-for-byte. A semantically neutral
shader edit had a different, explicit acceptance rule: changes of at most one
value per RGB channel, unchanged alpha, changes confined to textured surfaces
with plane/background unchanged, and neutral load-order variants reproducing
both images in one executable. A small changed-pixel count alone was not a pass.

The investigation therefore compared held orientations before judging the
shadow. Removing slope-scaled bias did not remove the bright intrusion near
a grazing face and introduced substantial incorrect self-shadowing on the lit
side. The retained bias was not declared perfect; the proposed explanation
failed its test. Limited shadow-map coverage near grazing remained a supported
interpretation, not directly traced proof of which texel caused each pixel.

This is material for an image-investigation post: controlled poses, a rejected
hypothesis and an explicitly accepted visual limitation. It should not become
a story in which every artifact was fixed by finding the right constant.

### Exercise reuse without accidentally serialising it

Capture waits for its submission on the host. That makes it useful for image
inspection but unsuitable as the only evidence for ordinary frame-slot reuse:
the extra wait can remove the overlap a lifetime test needs to exercise.

Sustained receiver scenarios therefore run without capture. Publication,
shared-map and wrong-slot faults test different assumptions about the barrier
and the slot fence. The broader fault campaign was performed on the Mac
configuration; the Linux destination-scope control does not duplicate all of
that platform-specific coverage.

Resource replacement needs another distinction. The [changed-caster scenario][source-caster]
modifies the geometry and removes the base-colour texture, so replacement does
not introduce an image upload whose wait could hide a missing retirement wait.
It tests the scene-resource transition while keeping the shadow-map ownership
separate. Presentation recreation has a different expected outcome: maps
remain alive while surface-compatible resources are replaced.

The posts will also distinguish candidate-construction rollback, joining a
failed helper, retry before image acquisition, and terminal cleanup after
acquisition. “Exception safety” is too broad to stand in for those contracts.
Manual resize, restore and close observations add window-lifecycle evidence,
but not a promise of zero rendering while a window is hidden.

## Under what measured conditions should the forward helper remain in use?

Adding a serial shadow pass changes the workload beneath 0.9's recording
policy. Every synthetic instance now generates one shadow draw and one forward
draw. At 1,000 instances that is 2,000 draws across both passes, not the old
one-pass workload with an extra timing label.

The measurement separates common work, shadow work and forward work. Shared
input/uniform work is counted once; overlapping participant diagnostics are
not added to the coordinator-observed forward region. The resulting
**[total active work][total-active-work]** is a sum of named CPU phases, excluding
frame-fence, image-acquisition and presentation-fence waits and the presentation
call. It is neither GPU time nor frame rate, and it does not include every
application or pass-call bookkeeping operation.

Two laptop implementations were eligible to inform the policy:

| Implementation | Recorded environment | Role |
| --- | --- | --- |
| NVIDIA GTX 1050, driver 580.173.02 | Intel i5-8300H, Ubuntu 24.04.4; FIFO presentation | hardware measurement |
| Mesa Lavapipe 25.2.8, LLVM 20.1.2 | the same laptop and OS; Mailbox presentation | software Vulkan measurement on the CPU |

The October 11 sessions used the same GCC 14.2 Release executable and shaders,
an 800-by-600 extent, two frame slots and two 1024-square D32 shadow maps. Each
invocation used 16 warm-up and 64 measured frames. Power and governor settings
were recorded, with both sessions on AC and the performance governor. The
different presentation modes remain part of the environment; absolute times
do not rank driver efficiency. Hosted Lavapipe and the Apple Silicon
KosmicKrisp preview supplied observations, not substitutes for either laptop
policy result.

### Set the selection rule before reading the result

The comparison runs one forward participant, then two, then one again:
`A₁/X/A₂`. The tooling names the two controls A and B; they select the same
configuration. Their mean `C = (A₁ + A₂) / 2` is the baseline, and their gap
`D = abs(A₂ - A₁)` is control drift. A direction resolves only when
`abs(C - X) > D`.

The primary comparison is total active work. If it is unresolved, the protocol
permits exactly one replacement triplet after the initial matrix completes.
That replacement supplies every derived comparison for the workload, even if
it remains unresolved. A resolved regression is not retried. The original
unresolved acquisition stays visible as context, not an alternative result to
select later. Forward-only improvement cannot override the primary verdict.

Invalid sessions are a different case: they retain their partial evidence and
need review before another session. A later complete session supplies all its
cells; results cannot be assembled from favourable fragments of several runs.
The [released acquisition and replay tooling][source-benchmark] implements the
within-session ordering, provenance checks and replacement rule. This is a
descriptive drift rule, not a statistical confidence interval.

These are historical, author-reported acquisitions, not new runs of the final
tag performed for this post. The local evidence archive was replayed against
its raw reports, but that archive is not yet a public download. The detailed
measurement post must give the selected and original acquisitions, conditions
and component tables a permanent home rather than rely on disposable notes.

With that rule and evidence scope established, the recorded total-active-work
results are:

| Implementation / instances | One-participant control C (µs) | Two-participant X (µs) | Drift D (µs) | Result |
| --- | ---: | ---: | ---: | --- |
| NVIDIA / 1,000 | 277.288 | 307.511 | 4.789 | 10.90% increase; regression |
| Lavapipe / 1,000 | 753.663 | 633.867 | 3.097 | 15.90% reduction; improvement |
| NVIDIA / 10,000, original | 1780.997 | 1759.151 | 33.673 | 1.23% nominal reduction; unresolved, superseded |
| NVIDIA / 10,000, replacement | 1790.999 | 1725.257 | 98.593 | 3.67% nominal reduction; unresolved |
| Lavapipe / 10,000 | 6251.511 | 5253.352 | 5.398 | 15.97% reduction; improvement |

At 1,000 instances the results resolve in opposite directions. At 10,000,
NVIDIA's replacement saves a nominal 65.742 microseconds against 98.593
microseconds of drift. Its forward-only comparison improves by 28.93%, but
that answers a narrower question; it cannot turn the total into a resolved
benefit.

The released policy retains at least 5,000 forward draws per participant:
two participants from 10,000 forward draws. It does not lower the threshold,
locate the unmeasured crossover, or renew a two-driver total-work speedup claim.
The 0.9 attempt and retention thresholds are not silently reapplied as a new
experiment that this release has passed.

The phase measurements also bound a possible future overlap of the two passes.
Perfect overlap could remove at most the smaller of their measured mean costs,
before new coordination. Even that is a loose model: the minimum of two means
need not equal the mean per-frame minimum. Untimed bookkeeping, dispatch,
joining and contention prevent it from being a measured parallel speedup.

## What the evidence does not establish

The remaining feature scope and the limits of current evidence are different
things. Deferring filtering does not excuse an unsupported lifetime claim;
having a clean validation run does not establish image quality.

| Evidence | Limit on the claim |
| --- | --- |
| Selected two-pass measurements | NVIDIA's large-workload total remains unresolved; forward-only gains do not resolve it. |
| Named CPU phase sums | They are not net shadow-feature cost, complete host time, GPU time or FPS. Historical one-pass totals are not a matched off/on control. |
| Accepted images and held-pose comparisons | Their environment and interpolation matter. Mac reference pixels are not portable output requirements. |
| Grazing-angle investigation | Limited texel coverage is an inference, not traced provenance or a universal bound on affected pixels. |
| Clean runs and deliberate faults | They establish the exercised detection paths, not exhaustive synchronization correctness on every driver. |
| Depth-format selection tests | D16 fallback has device-free coverage, not the device-quality evidence gathered for D32. |
| Capture and window observations | Capture adds a wait; minimised-window observations included continued rendering and did not exercise every zero-extent path. |

There is also a publication boundary. The released validation gate and wrapper
repair have immutable implementation links. The unmerged destination-scope
probe needs a reproduction record; a branch or expiring CI artifact is not
enough. Other temporary image and lifetime experiments need the same treatment.
That requirement is part of the upcoming posts, not satisfied merely by
including their conclusions in this overview.

## Run the released paths

The [build instructions][source-readme] require a C++23 compiler/library,
CMake, Ninja and vcpkg, with `VCPKG_ROOT` set to the vcpkg installation. The
full suite additionally needs a compatible Vulkan driver and display. The
`vcpkg` preset already selects Debug:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.10
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default
./build/fireEngineTutorial --smoke shadow
```

The Debug suite has 147 registrations: 94 Catch2 cases, 17 device-free CLI
checks and 36 device scenarios. Without usable Vulkan, run the 111 device-free
checks with `ctest --preset default -L device-free --no-tests=error`. Ordinary
Debug runs request validation when installed; the stricter Linux gate separately
establishes activation. Adapt executable paths for the platform.

For measurements, use a separate Release build. Two options were renamed and
the old spellings are rejected, not accepted as aliases:

| 0.9 | 0.10 |
| --- | --- |
| `--recording-threads` | `--forward-recording-participants` |
| `--direct-primary` | `--forward-direct-primary` |

The participant argument is `1` or `2`, including the coordinator. Both
options affect forward recording only; the shadow pass still runs. These
commands expose the comparison structure, not a replacement for the recorded
acquisition procedure:

```shell
cmake --preset vcpkg -B build-benchmark -DCMAKE_BUILD_TYPE=Release
cmake --build build-benchmark --target fireEngineTutorial

# A₁, X, A₂ at 1,000 instances
./build-benchmark/fireEngineTutorial --benchmark 1000 \
  --forward-recording-participants 1
./build-benchmark/fireEngineTutorial --benchmark 1000 \
  --forward-recording-participants 2
./build-benchmark/fireEngineTutorial --benchmark 1000 \
  --forward-recording-participants 1

# A₁, X, A₂ at 10,000 instances
./build-benchmark/fireEngineTutorial --benchmark 10000 \
  --forward-recording-participants 1
./build-benchmark/fireEngineTutorial --benchmark 10000 \
  --forward-recording-participants 2
./build-benchmark/fireEngineTutorial --benchmark 10000 \
  --forward-recording-participants 1

# Direct-primary attribution controls, not candidate arms
./build-benchmark/fireEngineTutorial --benchmark 1000 --forward-direct-primary
./build-benchmark/fireEngineTutorial --benchmark 10000 --forward-direct-primary
```

Keep one unchanged executable, driver and environment, without validation,
tracing or sanitizer instrumentation. The [matrix runner][source-benchmark]
adds automatic-policy qualification and a one-instance reset estimate, records
provenance, and applies the replacement rule. It requires Python 3.10+, a clean
tracked checkout, a matching Release build and an edited conditions file.
For example, on the NVIDIA laptop:

```shell
mkdir -p build-evidence
cp tools/benchmark/conditions.example.json build-evidence/nvidia-conditions.json
# Edit the copy to record actual power, governor, load and cooldown conditions.
python3 tools/benchmark/run_matrix.py \
  --role laptop-nvidia \
  --icd /usr/share/vulkan/icd.d/nvidia_icd.json \
  --build-dir build-benchmark \
  --conditions build-evidence/nvidia-conditions.json
```

Select the installed manifest rather than assuming that example path exists.
Use `laptop-lavapipe` with its installed ICD and a separate conditions file for
the software session, retaining the same binary. The runner rejects an
unedited template and inherited instrumentation; it does not configure power
or governor policy. The tooling guide documents observational Mac/hosted roles
and offline replay. This reproduces the method, not the published numbers.

## Where this leaves the architecture

The [0.10 architecture][architecture-0-10] stands independently of this series.
It describes one compiled frame supplying two restricted inputs, maps owned
by frame slot rather than presentation, and a coordinator that submits shadow
then forward work. The existing helper remains a bounded forward-recording
choice, not a general scheduler.

That is also where possible 0.11 work begins. Normal-aware lighting and shadow
treatment, filtering, and an experiment in overlapping CPU pass recording
address different limits. None follows automatically from adding another pass,
and the overlap bound is not a promise that another thread will pay.

The upcoming posts will explain how the release separated those questions and
what evidence each answer required. The point is not that the second pass was
isolated from the rest of the engine. It is that its shared changes, lifetime
rules, visual compromises and conditional policy can be examined separately
without losing the dependency that connects them.

## Recommended reading

- [Real-Time Rendering][reading-real-time-rendering] — the broader shadow-map,
  sampling and image-quality context behind the deliberately small feature.
- [Vulkan Guide: Synchronization Examples][reading-synchronization] — concrete
  access dependencies and image transitions, including depth writes consumed
  by later shader sampling.
- [Vulkan Validation Overview][reading-validation] — the role of valid usage
  and development-time validation, distinct from judging whether an image is
  the one the application intended.
- [glTF 2.0: Animations][reading-animation] — the source-format interpolation
  contract behind the rotation-pacing correction and matched-pose comparisons.

The [Reading page][reading-page] keeps these references alongside the wider
series bibliography. The [Terminology page][terminology-page] collects the
shadow, recording and measurement vocabulary used here.

[release-0-10]: {{ page.release_url }}
[architecture-0-9]: {% link _architecture/0.9.md %}
[architecture-0-10]: {% link _architecture/0.10.md %}
[boundary-post]: {% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %}
[terminology-page]: {% link _tabs/terminology.md %}
[total-active-work]: {% link _tabs/terminology.md %}#total-active-work
[reading-page]: {% link _tabs/reading.md %}
[source-readme]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/README.md
[source-renderer]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/renderer.cpp
[source-frame]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/frame_description.hpp
[source-input]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/frame_recording_input.cpp
[source-input-tests]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tests/render/test_frame_recording_input.cpp
[source-caster]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tests/app/test_shadow_caster_replacement.cpp
[source-shadow]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/shadow_recorder.cpp
[source-bindings]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/forward_recorder.cpp#L154-L190
[source-policy]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/render/shadow_map_policy.cpp
[source-sampler]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/include/fire_engine/render/detail/shadow_map_policy.hpp
[source-shader]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/shaders/forward.slang
[source-animation]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/src/animation/animation_playback.cpp
[source-images]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/docs/images/README.md
[source-build]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/CMakeLists.txt
[source-validation]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tools/ci/run_validation_tests.py
[source-benchmark]: https://github.com/nnewson/fireEngine-tutorial/blob/0.10/tools/benchmark/README.md
[wrapper-commit]: https://github.com/nnewson/fireEngine-tutorial/commit/38a36f9fe4d130bcbc10ad232b08dd1d770f3115
[validation-commit]: https://github.com/nnewson/fireEngine-tutorial/commit/21f8abdbd182b7f01e8b0b76291280b830ca176d
[probe-pr]: https://github.com/nnewson/fireEngine-tutorial/pull/84
[reading-real-time-rendering]: https://www.realtimerendering.com/
[reading-synchronization]: https://docs.vulkan.org/guide/latest/synchronization_examples.html
[reading-validation]: https://docs.vulkan.org/guide/latest/validation_overview.html
[reading-animation]: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations
