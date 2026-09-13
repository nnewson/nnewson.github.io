---
title: "Proving fireEngine's secondary command path before measuring it"
date: 2026-09-12 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.9", 3d-engine, architecture, multithreading, vulkan, validation, command-buffers, cpp]
description: >-
  Prove that fireEngine can record geometry into secondary command buffers
  under dynamic rendering before treating that structure as a performance
  opportunity.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
---

Moving draw commands into a second command buffer is not yet multithreading.
That is exactly why it is a useful first experiment. It asks whether the Vulkan
command structure works before thread ownership, coordination cost, and
performance are allowed to complicate the answer.

Release 0.8 records a complete frame into one primary command buffer. Release
0.9 keeps a primary buffer around the frame but records geometry into one or
two secondary buffers. Before deciding how many CPU threads should participate,
fireEngine first had to establish that a secondary can inherit the active
dynamic-rendering state, contain the draw commands, and execute cleanly from
the primary on the available Vulkan implementations.

The result is deliberately narrower than a speed claim. The structure passed
standard and synchronization validation on Mesa Lavapipe and the KosmicKrisp
technical preview. The two implementations then placed its host cost in very
different phases. Validity made the structure eligible for further work;
measurement still had to decide whether another thread would earn its cost.

This detailed post is based on release 0.9. The [release map][map-post]
introduces the questions, measurement language, and limits for the complete
series. The [0.9 architecture page][architecture-0-9] records only the design
that survived those investigations.

> Code for this article: [fireEngine 0.9][release-0-9]
>
> Starting point: [fireEngine 0.8][release-0-8]
>
> Architecture: [fireEngine 0.9 architecture][architecture-0-9]
>
> This post isolates the functional question. It does not yet justify a worker,
> choose a workload threshold, or claim that secondary command buffers are
> faster than recording directly into a primary command buffer.
{: .prompt-info }

## Introducing the validation environments and control

Four terms distinguish the evidence used in this post:

- **Lavapipe** is Mesa's CPU implementation of Vulkan. It lets Ubuntu CI run
  the real Vulkan path on a machine without a GPU;
- **KosmicKrisp** is the Apple Silicon Vulkan implementation distributed as a
  technical preview in the LunarG SDK;
- **synchronization validation** extends standard validation with checks for
  incorrectly ordered resource accesses and synchronization hazards; and
- the **direct-primary control** records the same draws directly into the
  primary command buffer. It later lets fireEngine distinguish costs associated
  with secondary commands from the cost of the draws themselves.

The [Terminology page][terminology-page] collects these definitions with the
measurement vocabulary used across the 0.9 series.

## Separate the command structure from the thread

A Vulkan queue accepts primary command buffers for submission. A secondary
command buffer cannot be submitted on its own; a primary records an
`executeCommands()` operation that incorporates it into the submitted work.

That gives the two levels different jobs in fireEngine:

```text
primary command buffer
├── transition colour and depth attachments
├── begin dynamic rendering
├── execute secondary command buffer
├── end dynamic rendering
└── transition the colour image for presentation

secondary command buffer
├── establish pipeline and dynamic state
├── bind geometry and sampled images
├── push per-draw constants
└── issue indexed draws
```

The primary owns the frame boundary. It knows the acquired swapchain image and
the depth attachment, performs their layout transitions, opens and closes the
rendering instance, and later reaches queue submission and presentation. The
secondary owns only commands recorded inside that rendering instance.

This split is useful for concurrency because independent secondary buffers can
eventually be recorded by different CPU threads. The first experiment does not
do that. One thread records one secondary and then records the primary that
executes it:

```text
one CPU thread
     |
     +--> record secondary draws
     |
     +--> record primary frame boundary
              |
              +--> execute the secondary
              |
              +--> submit and present
```

Keeping the experiment single-threaded removes data races, hand-off lifetimes,
and completion waits from the question. If this form fails validation, adding a
worker cannot make it valid. If it succeeds, threading remains a separate
architectural and performance decision.

The [minimal experiment][source-experiment] changes only this command shape.
The [released implementation][source-released-secondary] preserves the same
primary/secondary division after the later ownership and worker work has been
added.

## Tell the secondary which rendering state it inherits

A secondary recorded for dynamic rendering does not begin its own rendering
instance and does not receive the primary's state implicitly. Its begin
information must describe the attachment formats and sample count with which
it will execute.

The released recorder constructs that inheritance immediately before recording
each secondary chunk:

```cpp
const vk::CommandBufferInheritanceRenderingInfo renderingInheritance{
    .colorAttachmentCount = 1,
    .pColorAttachmentFormats = &job.state.colorAttachmentFormat,
    .depthAttachmentFormat = job.state.depthAttachmentFormat,
    .rasterizationSamples = vk::SampleCountFlagBits::e1,
};
const vk::CommandBufferInheritanceInfo inheritanceInfo{
    .pNext = &renderingInheritance,
};
const vk::CommandBufferBeginInfo secondaryBeginInfo{
    .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit |
             vk::CommandBufferUsageFlagBits::eRenderPassContinue,
    .pInheritanceInfo = &inheritanceInfo,
};

commandBuffer.begin(secondaryBeginInfo);
```

The [`VkCommandBufferInheritanceRenderingInfo` reference][vulkan-inheritance]
defines the dynamic-rendering information chained to the ordinary inheritance
structure.
The colour and depth formats must agree with the active rendering instance and
with the graphics pipeline used by the secondary. The sample count must agree
too. FireEngine renders one colour attachment, one depth attachment, and one
sample per pixel, so those values form its complete format contract.

The inheritance data does not contain the actual swapchain image or depth-image
view. Those remain primary-buffer concerns. This is an important restriction:
the secondary knows the compatibility information required to record its draws,
but it does not acquire presentation resources or decide where the frame will
be presented.

`eOneTimeSubmit` describes the buffer's intended reuse, while
`eRenderPassContinue` says that its commands execute inside a rendering
instance begun elsewhere. Neither flag starts rendering or provides
synchronization. They state the circumstances in which Vulkan will consume the
recorded commands.

See [`recordSecondaryChunk()`][source-released-inheritance] for the complete
released recording path around this excerpt.

## Mark the primary rendering instance for secondary contents

The matching half of the contract lives in the primary. Its dynamic-rendering
declaration must say that the rendering instance will contain commands executed
from secondary buffers:

```cpp
beginPrimaryRecording(
    primaryCommandBuffer,
    frameSlotIndex,
    imageIndex,
    vk::RenderingFlagBits::eContentsSecondaryCommandBuffers);

const std::array secondaryCommands{
    *frame.secondaries.front().commandBuffer(),
};
primaryCommandBuffer.executeCommands(secondaryCommands);
```

`beginPrimaryRecording()` performs the colour and depth transitions before it
opens dynamic rendering with that flag. After the secondary executes,
`endPrimaryRecording()` closes rendering and transitions the colour image for
presentation. The ordering is therefore unchanged from the direct path; only
the location of the geometry commands changes.

```text
attachment transitions
        |
        v
begin dynamic rendering
        |
        v
execute inherited secondary draws
        |
        v
end dynamic rendering
        |
        v
transition for presentation
```

The [released primary path][source-released-primary] may execute one or two
secondaries, but it preserves their original draw order. The first experiment
used exactly one. Proving that smallest case avoids confusing Vulkan
inheritance with workload splitting.

## Keep the first ownership choice temporary

The functional experiment allocates its primary and secondary buffers from the
existing frame command pool. That is sufficient while one CPU thread records
both buffers in sequence and the frame fence prevents the pool from being reset
while the GPU may still use its allocations.

It is not a suitable final ownership model for concurrent recording. Vulkan
command pools are externally synchronized: callers must prevent simultaneous
access to one pool themselves. Giving two recording threads buffers from the
same pool would therefore require a lock or would violate that rule. Either
outcome would defeat the intended independent recording contexts.

The experiment consequently proves no ownership claim beyond its single-thread
scope:

| Question | Answer from this experiment |
|---|---|
| Can one secondary inherit fireEngine's dynamic-rendering formats? | yes |
| Can the primary execute it inside the existing frame protocol? | yes |
| Can both buffers temporarily share a pool on one recording thread? | yes |
| May two threads access that pool concurrently? | not established, and not the released design |
| Will a second recording thread improve elapsed CPU time? | not established |

Release 0.9 later gives every recording context its own pool, but that is a
different argument about ownership and attribution. Folding it into this first
experiment would make a validation failure harder to locate: inheritance, pool
ownership, thread hand-off, and completion would all change at once.

## Ask validation the functional question

The success criterion is not that an image appeared. A driver may tolerate an
invalid command relationship, and a familiar scene may still look correct when
the attachment formats, usage flags, or inheritance chain are wrong.

The experiment therefore runs the complete application path under both
standard and synchronization validation. The existing CTest scenarios already
turn a message beginning `Vulkan validation error:` into a failed test, share
one Vulkan resource lock, and apply a 30-second timeout. The earlier
[scenario post][scenario-post] explains how a temporary fault confirmed that
this gate can fail rather than merely recording a run that happened to remain
green.

At this experimental checkpoint the complete Debug suite registered 53 tests:
47 device-free Catch2 cases, four standard Vulkan scenarios, and two
synchronization-validation variants.

The inherited command structure completed cleanly in both available
environments:

| Environment | Implementation kind | Validation evidence |
|---|---|---|
| Apple M2 Pro through KosmicKrisp | Apple Silicon technical preview | all 53 registrations passed locally |
| Ubuntu CI through Mesa Lavapipe | CPU Vulkan implementation | the same 53 registrations passed in CI |

That is useful coverage, but it is not every Vulkan implementation fireEngine
might encounter. The hosted macOS and Windows jobs build the project without
running the device scenarios on their target drivers. No real Windows or Linux
hardware driver participated in this first functional experiment.

The conclusion must remain proportional to that evidence: secondary inheritance
is validation-clean on the implementations exercised. It is not a proof that
every driver accepts the path, and validation cannot say whether the path is
fast.

The [scenario registrations][source-scenarios] show the validation-error gate,
resource lock, timeout, and synchronization-validation variants used by the
experiment. The final 0.9 suite expands that coverage to the surviving
one-participant and split-recording paths.

## Treat opposite phase shapes as a reason to measure

Once phase timing was placed around the valid command structure, the two
implementations appeared to handle secondary execution very differently. These
are within-environment observations, not absolute timings to compare between
machines:

| Environment and workload | Record the secondary | Execute it from the primary | Relationship |
|---|---:|---:|---:|
| KosmicKrisp, 10,000 draws | 590.634 us | 6,984.228 us | execution was 11.8 times recording |
| Lavapipe, 1,000 draws | 265.098 us | 0.378 us | execution was 0.14% of recording |
| Lavapipe, 10,000 draws | 3,435.351 us | 1.400 us | execution was 0.04% of recording |

The measurements do not reveal what either driver does internally. KosmicKrisp
might replay or flatten substantial secondary work while the primary executes
it, but host timestamps cannot prove that explanation. Lavapipe's much smaller
execution phase does not prove that a hardware driver will behave the same way.

Nor are these values a primary-versus-secondary speed comparison. The coarse
baseline already used this secondary-plus-primary structure, so it cannot say
what recording every draw directly into the primary would have cost. That
requires a direct-primary control in the same executable and a paired
measurement protocol.

The disagreement is therefore the useful result. A legal Vulkan structure can
place cost in different observable phases on different implementations. The
engine must measure recording, secondary execution, submission, and command-pool
reset separately before it can identify work another CPU thread might shorten.

## Keep the answer narrower than the ambition

This experiment answers one question:

> A primary command buffer can open fireEngine's dynamic-rendering instance,
> execute geometry recorded in a correctly inherited secondary command buffer,
> close the instance, and present without validation errors on the Vulkan
> implementations exercised.

It does not establish that secondary command buffers reduce CPU time. It does
not establish that recording can safely move to another thread. It does not
decide how command pools, frozen inputs, or completion are owned. Most
importantly, it does not treat opposite driver observations as noise that can
be averaged into one portable answer.

The secondary command path is now viable enough to measure. The
[CPU-measurement post][cpu-measurement-post] asks where its CPU time occurs and
how much of that time could actually overlap with another recording participant.
Answering that requires a phase-level benchmark, a direct-primary control, and
comparison rules written before the candidate is measured.

## Run the surviving validation paths

The released code includes the later ownership and worker changes, so these
commands exercise the secondary inheritance contract as part of its final
form rather than recreating the deliberately temporary one-pool experiment:

```shell
git clone https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
git checkout 0.9
cmake --preset vcpkg -DCMAKE_BUILD_TYPE=Debug
cmake --build --preset default

ctest --preset default \
  -R '^fireEngineTutorialSplitRecordingBenchmarkCorrectness$' \
  --output-on-failure

ctest --preset default \
  -R '^fireEngineTutorialSplitRecordingSyncValidation$' \
  --output-on-failure
```

The first registration runs the split path through the normal validation
configuration. The second enables synchronization validation through
`VK_LAYER_VALIDATE_SYNC=1`. Both force two non-empty draw ranges, so the
primary executes two inherited secondary command buffers. They are correctness
checks, not performance measurements.

See the [released CTest registrations][source-released-tests] for those commands
and the validation environment applied to the synchronization variant.

## Recommended reading

- [Vulkan specification: Command Buffers][reading-command-buffers] — the
  normative distinction between primary and secondary levels, execution, usage
  flags, inheritance, and external synchronization.
- [`VkCommandBufferInheritanceRenderingInfo` reference][vulkan-inheritance] —
  the attachment and sample information inherited by a secondary executing
  inside dynamic rendering.
- [Vulkan Validation Overview][reading-validation] — what the validation layer
  checks, how valid-usage identifiers describe findings, and why a clean run is
  evidence about correctness rather than speed.
- [Vulkan Programming Guide][reading-vulkan-guide] — broader command-buffer,
  queue, synchronization, and rendering context around this experiment.

The [Reading page][reading-page] keeps the site-wide list in one place, and the
[Terminology page][terminology-page] collects the project-specific measurement
and recording terms used across the 0.9 series.

[release-0-8]: {{ page.previous_release_url }}
[release-0-9]: {{ page.release_url }}
[map-post]: {% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}
[cpu-measurement-post]: {% post_url 2026-09-13-measuring-fireengines-cpu-work-before-adding-another-thread %}
[scenario-post]: {% post_url 2026-09-02-closing-fireengine-08-with-focused-ownership-and-executable-scenarios %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[terminology-page]: {% link _tabs/terminology.md %}
[reading-page]: {% link _tabs/reading.md %}
[source-experiment]: <https://github.com/nnewson/fireEngine-tutorial/blob/5e7f36e/src/render/renderer.cpp#L483-L520>
[source-released-secondary]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L834-L910>
[source-released-inheritance]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L1245-L1281>
[source-released-primary]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/src/render/renderer.cpp#L885-L909>
[source-scenarios]: <https://github.com/nnewson/fireEngine-tutorial/blob/5e7f36e/CMakeLists.txt#L243-L295>
[source-released-tests]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.9/CMakeLists.txt#L272-L359>
[vulkan-inheritance]: <https://docs.vulkan.org/refpages/latest/refpages/source/VkCommandBufferInheritanceRenderingInfo.html>
[reading-command-buffers]: <https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html>
[reading-validation]: <https://docs.vulkan.org/guide/latest/validation_overview.html>
[reading-vulkan-guide]: <https://www.vulkanprogrammingguide.com>
