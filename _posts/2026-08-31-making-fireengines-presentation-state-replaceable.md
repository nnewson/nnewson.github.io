---
title: "Making fireEngine's presentation state replaceable"
date: 2026-08-31 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", vulkan, swapchain, presentation, synchronization, rendering, glfw, testing]
description: >-
  Replace fireEngine's swapchain-compatible resources as one ownership group,
  retire presentation explicitly, and preserve compiled scene resources.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

A Vulkan window does not keep one presentation configuration forever. Its
framebuffer can change size, become temporarily unavailable while minimised, or
stop matching a swapchain between acquisition and presentation. The surface
may also choose a different image count, format, or presentation mode when it
is queried again.

Release 0.7 reports suboptimal and out-of-date results but stops there. Release
0.8 makes replacement part of the normal renderer contract. The swapchain,
image views, per-image semaphores, depth attachment, compatible pipeline, and
presentation-completion fences become one replaceable ownership group. The
device, allocator, frame slot, preparation cache, and compiled scene resources
remain alive around it.

The difficult part is not constructing a second swapchain. It is proving when
the first group can die. The frame fence and `deviceWaitIdle()` cover submitted
device work, but presentation continues through a separate engine after the
graphics queue has signalled its render-finished semaphore. Release 0.8 uses
the swapchain-maintenance presentation-fence path to establish that second
completion boundary explicitly.

This detailed post is based on release 0.8. The
[architectural overview][planning-post] describes the complete release. The
[camera post][camera-post] introduces the extent-dependent depth, pipeline, and
projection state replaced here, while the
[frame-in-flight post][frame-in-flight-post] explains why presentation
semaphores follow swapchain images rather than frame slots.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> The [camera post][camera-post] establishes one compatible presentation set.
> This post turns that set into a safely replaceable lifetime.
{: .prompt-info }

## Draw the replacement boundary before writing recreation

A resize does not invalidate the complete renderer. It invalidates the values
derived from the presentation surface and framebuffer:

```text
long-lived renderer
├── Device + queues
├── MemoryAllocator
├── FrameInFlight
├── RenderPreparation cache
├── CompiledResources
│   ├── mesh buffers
│   ├── texture images + views
│   ├── samplers
│   └── render-object lookup
└── PresentationState                 replace as one group
    ├── Swapchain
    │   ├── images + image views
    │   └── render-finished semaphores
    ├── DepthBuffer
    ├── compatible Pipeline
    └── presentation fences
```

The split follows dependency rather than convenience:

| State | Why it is replaced or preserved |
| --- | --- |
| Swapchain and image views | surface capabilities, extent, format, and image count can change |
| Per-image render-finished semaphores | their count and reuse follow acquired swapchain images |
| Depth buffer | its image must match the new rendering extent |
| Pipeline | dynamic rendering requires compatible colour and depth formats |
| Presentation fences | one completion fence belongs to each new swapchain image |
| Frame slot | its command pool, acquisition semaphore, submission fence, and uniform buffer remain usable |
| Compiled scene resources | meshes, textures, samplers, and materials do not depend on window size |
| Preparation cache | scene reachability and asset revisions do not change during a resize |

This is the organising decision for the whole feature. If swapchain-derived
objects remain scattered among long-lived members, recreation becomes a list
of assignments whose completeness has to be remembered. Grouping them turns
replacement into one ownership operation.

## Build one internally compatible presentation state

`PresentationState` is file-local to the renderer implementation. Its members
name the replacement lifetime directly:

```cpp
class PresentationState final
{
public:
    PresentationState(
        const detail::Device& device,
        const detail::MemoryAllocator& allocator,
        const Window& window,
        vk::SwapchainKHR oldSwapchain = nullptr);

    void preparePresentFence(std::size_t imageIndex);
    [[nodiscard]] const vk::raii::Fence&
    presentFence(std::size_t imageIndex) const;
    void markPresentSubmitted(std::size_t imageIndex);
    void waitForPresentations();

private:
    const vk::raii::Device* logicalDevice_ = nullptr;
    detail::Swapchain swapchain_;
    detail::DepthBuffer depthBuffer_;
    detail::Pipeline pipeline_;
    std::vector<vk::raii::Fence> presentFences_;
    std::vector<std::uint8_t> presentSubmitted_;
};
```

Construction follows the dependency chain:

```cpp
: logicalDevice_{&device.logicalDevice()},
  swapchain_{device, window, oldSwapchain},
  depthBuffer_{device, allocator, swapchain_.extent()},
  pipeline_{device, swapchain_.imageFormat(), depthBuffer_.format()},
  presentSubmitted_(swapchain_.imageCount(), 0)
```

The swapchain establishes image count, extent, and colour format. The depth
buffer consumes the extent and selects its supported depth format. The pipeline
then consumes both attachment formats. Only after that chain exists does the
constructor create one unsignalled presentation fence per swapchain image.

Member declaration order encodes destruction in reverse. Presentation fences
and pipeline die before their attachments; the depth image dies before the
swapchain. The `Swapchain` owner in turn releases its per-image views before
the swapchain that supplied their images. Declaration order cannot prove that
presentation has stopped using those objects, so `waitForPresentations()` is a
separate lifetime precondition rather than something RAII can infer.

See `PresentationState` in [`renderer.cpp`][source-renderer] and the per-image
ownership in [`swapchain.hpp`][source-swapchain-header].

## Keep the public operation free of Vulkan policy

The renderer facade exposes one operation:

```cpp
[[nodiscard]] bool recreatePresentation(const Window& window);
```

The application supplies the window whose current framebuffer selects the new
extent. A `true` result means replacement succeeded. `false` means the
framebuffer is currently zero-sized, a normal transient state while a window is
minimised rather than a rendering error.

The method does not ask the caller to pass an old swapchain, wait on fences,
rebuild a depth image, or choose a compatible pipeline. Those are Vulkan
lifetime mechanics and stay behind `Renderer`. Conversely, the renderer does
not decide whether the application should block for events, close, or retry.
That recovery policy remains in the event loop.

Prepared resources are explicitly outside the operation's effects. The caller
does not reload glTF, call `prepare()` again, or reconstruct the renderer just
because the presentation surface changed.

See the facade in [`renderer.hpp`][source-renderer-header].

## Turn several signals into the same recovery request

Presentation can become unsuitable at several points. `RenderResult` keeps
those expected outcomes as values rather than turning them into exceptional
failures:

| Signal | Frame outcome | Application response |
| --- | --- | --- |
| framebuffer-size callback | no draw attempted yet | recreate before drawing |
| acquisition throws out-of-date | `eNotPresented` | recreate and retry later |
| acquisition reports suboptimal | frame may still present | if presentation succeeds, return `ePresentedSuboptimal`, then recreate |
| presentation reports suboptimal | image was presented | return `ePresentedSuboptimal`, then recreate |
| presentation throws out-of-date | `eNotPresented` | retire that present, then recreate |

The event loop handles the callback before drawing:

```cpp
if (window.consumeFramebufferResize())
{
    if (!recreateWhenDrawable(renderer, window))
    {
        break;
    }
}

const fire_engine::RenderResult result =
    renderer.drawFrame(content.scene);
```

It handles an acquire or present result afterwards:

```cpp
if (result != fire_engine::RenderResult::ePresented ||
    options.recreateEveryFrame)
{
    static_cast<void>(window.consumeFramebufferResize());
    if (!recreateWhenDrawable(renderer, window))
    {
        break;
    }
}
```

When the frame result already requires replacement, consuming any callback that
arrived during the draw prevents that pending notification from causing another
replacement on the following iteration.

An acquire-side out-of-date result occurs before the frame fence is reset, so
the abandoned frame leaves that fence signalled. Presentation-side out-of-date
is different: graphics was submitted and the presentation operation was still
enqueued. Its presentation fence must therefore be tracked even though the
application counts no presented image.

See the result handling in [`main.cpp`][source-main] and
[`renderer.cpp`][source-renderer].

## Re-query framebuffer size instead of trusting callbacks

GLFW's framebuffer callback records only that something changed:

```cpp
void Window::framebufferSizeCallback(GLFWwindow* window,
                                     int, int) noexcept
{
    auto* const owner = static_cast<Window*>(
        glfwGetWindowUserPointer(window));
    if (owner != nullptr)
    {
        owner->framebufferResized_ = true;
    }
}
```

The reported dimensions are deliberately ignored. Several callbacks may be
coalesced before the event loop responds, so recreation queries the current
framebuffer in physical pixels instead. Physical pixels are the units required
by the Vulkan swapchain and can differ from logical window coordinates on a
high-DPI display.

`consumeFramebufferResize()` returns the flag once and clears it. The callback
therefore communicates an event without putting Vulkan work inside GLFW's C
callback or repeatedly recreating for a notification already handled.

See [`window.hpp`][source-window-header] and
[`window.cpp`][source-window].

## Wait for a minimised window without spinning

A minimised window can report a framebuffer with zero width or height. Vulkan
cannot create a useful swapchain or projection for that extent, and repeatedly
polling it would consume CPU while no drawable image exists.

The application instead waits for window-system events:

```cpp
while (!window.shouldClose())
{
    const vk::Extent2D extent = window.framebufferExtent();
    if (extent.width != 0 && extent.height != 0 &&
        renderer.recreatePresentation(window))
    {
        return true;
    }
    window.waitEvents();
}
return false;
```

The event-loop check avoids an unnecessary renderer call for the common
zero-sized case. `recreatePresentation()` checks again because the window can
be minimised between those two operations. Its `false` result returns control
to the loop, which sleeps again until restoration, another event, or closure.

This division also keeps shutdown responsive. Closing a minimised window wakes
the wait, makes `shouldClose()` true, and exits without requiring a drawable
framebuffer first.

## Retire old work before replacing its state

The renderer's replacement protocol is short enough to read as one sequence:

```cpp
const vk::Extent2D framebufferExtent = window.framebufferExtent();
if (framebufferExtent.width == 0 || framebufferExtent.height == 0)
{
    return false;
}

waitIdle();
const vk::SwapchainKHR oldSwapchain =
    *presentation_->swapchain().handle();
auto replacement = std::make_unique<PresentationState>(
    device_, allocator_, window, oldSwapchain);
frame_.writeUniforms(detail::FrameUniforms{
    .viewProjection =
        createViewProjection(replacement->swapchain().extent()),
});
presentation_ = std::move(replacement);
return true;
```

Read as a lifetime protocol:

```text
confirm a non-zero framebuffer
              |
              v
finish submitted device work
              |
              v
wait for every submitted presentation fence
              |
              v
create complete replacement using oldSwapchain
              |
              v
write projection for replacement extent
              |
              v
swap ownership and destroy retired old state
```

Passing `oldSwapchain` lets the Vulkan implementation reuse resources. It also
retires the old swapchain when `vkCreateSwapchainKHR` is called, even if creation
of the new swapchain fails. The old C++ owner remains alive while the
replacement's swapchain, depth buffer, pipeline, and fences are assembled.
Partial construction is cleaned up by RAII, and the owning pointer changes only
after the replacement and its projection are ready.

There is therefore an important limit to that exception safety. Failure of the
new swapchain call itself, or of a later depth, pipeline, or uniform update,
propagates out of recreation and ends the application; the code does not claim
that it can resume rendering through the retired old state.

## Refresh everything derived from the extent

Recreation updates more than the colour images:

```text
new surface query
        |
        v
swapchain extent + colour format
        |
        +-- extent --> new DepthBuffer --> depth format -----+
        |                                                    |
        +-- colour format -----------------------------------+--> new Pipeline
        |
        +-- extent ---------------------------> new view-projection uniform
```

The new depth image matches the swapchain extent. The new pipeline names the
selected colour and depth formats required by dynamic rendering. The frame
slot's uniform buffer remains alive, but its contents are overwritten with a
view-projection matrix whose aspect ratio uses the replacement extent.

Viewport, scissor, render area, colour view, depth view, and pipeline are read
through the current `presentation_` whenever commands are recorded. No recorded
command sequence survives a recreation: `waitIdle()` finishes its earlier
submission, and the next frame resets the preserved frame slot's command pool
and records its command buffer against the new group.

Compiled scene resources require no corresponding work. Their device buffers,
sampled images, samplers, and render-object lookup remain owned by
`CompiledResources`; their preparation generation is unchanged. The next draw
binds those same resources through the replacement pipeline layout.

The [camera post][camera-post] covers the extent, depth, pipeline, and uniform
relationships in detail.

## Distinguish graphics completion from presentation retirement

One frame crosses two completion domains:

```text
graphics queue
command buffer finishes
        |
        +--> frame-finished fence signals ------> CPU may reuse frame slot
        |
        +--> renderFinished[image] signals
                         |
                         v
presentation engine waits and presents
                         |
                         +--> presentFence[image] signals
                                  CPU may destroy presentation resources
```

The frame-finished fence belongs to the graphics submission. Waiting for it
proves the command buffer, depth attachment, colour image, descriptors, and
other graphics inputs are no longer being used by that submission. It does not
prove that presentation has finished waiting on the binary
`renderFinished[image]` semaphore.

`deviceWaitIdle()` likewise waits for queue work associated with the logical
device, but the presentation engine's use of swapchain resources needs its own
specification-backed completion signal. Destroying an old swapchain or its
render-finished semaphores after only the device wait would leave that lifetime
implicit.

Release 0.8 therefore makes `Renderer::waitIdle()` a two-part operation:

```cpp
device_.logicalDevice().waitIdle();
presentation_->waitForPresentations();
workMayBePending_ = false;
```

The first wait finishes submitted rendering, allowing every presentation wait
to consume its semaphore. The second waits for the presentation fences that
make the old presentation objects safe to retire.

## Require the presentation-fence capability explicitly

Presentation fences come from `VK_KHR_swapchain_maintenance1`, or the
equivalent earlier `VK_EXT_swapchain_maintenance1` path. The renderer does not
silently assume either one exists.

Instance setup requires extended surface capabilities and at least one matching
surface-maintenance variant. Physical-device inspection then requires the
corresponding swapchain-maintenance extension and queries the
`swapchainMaintenance1` feature. Logical-device creation enables the selected
extension and feature. The KHR path is preferred; EXT keeps the same retirement
contract available on implementations from before the KHR promotion.

This is a real increase in fireEngine's minimum device requirements. The
extension is not enabled for an optional convenience: the renderer's destruction
and recreation proof depends on the presentation fences it supplies. A device
without either complete instance-and-device path is rejected with a diagnostic
rather than entering a lifetime protocol it cannot finish.

See capability selection in [`debug.cpp`][source-debug] and
[`device.cpp`][source-device].

## Give each acquired image one reusable presentation fence

`PresentationState` creates an unsignalled fence and a submitted flag for every
swapchain image. Before image `k` reuses its fence, the renderer checks whether
an earlier present was associated with it:

```cpp
if (presentSubmitted_.at(imageIndex) == 0)
{
    return;
}

logicalDevice_->waitForFences(
    *presentFences_.at(imageIndex), vk::True,
    std::numeric_limits<std::uint64_t>::max());
logicalDevice_->resetFences(*presentFences_[imageIndex]);
presentSubmitted_[imageIndex] = 0;
```

The submitted flag matters because a newly created fence starts unsignalled.
Waiting for it before any presentation could ever signal it would block
forever. Once a submitted fence signals, the host waits and resets it before
associating it with another present of the same image.

The next present chains that fence through `VkSwapchainPresentFenceInfoKHR`:

```cpp
const vk::Fence presentFence =
    *presentation_->presentFence(imageIndex);
const vk::SwapchainPresentFenceInfoKHR presentFenceInfo{
    .swapchainCount = 1,
    .pFences = &presentFence,
};
const vk::PresentInfoKHR presentInfo{
    .pNext = &presentFenceInfo,
    // render-finished semaphore, swapchain, and image index...
};
```

After `presentKHR()` returns, the image's submitted flag records that the fence
will need retirement. The out-of-date exception path records it too because an
out-of-date result still enqueues the presentation operation and its fence.

At ordinary image reuse, `preparePresentFence(imageIndex)` waits and resets one
entry. Before replacement or shutdown, `waitForPresentations()` applies the
same operation to every submitted entry. The same bookkeeping therefore covers
steady-state reuse and whole-group destruction.

See the present path and fence owner in
[`renderer.cpp`][source-renderer].

## Keep render-finished semaphores indexed by image

Presentation fences solve destruction and explicit retirement. The binary
semaphore waited on by presentation retains its earlier per-image reuse rule:

```text
acquire image k
        |
        v
graphics signals renderFinished[k]
        |
        v
presentation waits on renderFinished[k]
        |
        v
later acquisition of image k permits its reuse
```

`renderFinished[k]` belongs to `Swapchain`, not `FrameInFlight`, because
presentation follows the acquired image. A replacement swapchain may report a
different image count, so its new semaphore vector is constructed and destroyed
with those images.

The presentation fence has a related but different job. Acquiring an image
provides the ordering needed to reuse that image's render-finished semaphore;
waiting on the present fence explicitly proves that the presentation operation
has released the resources when the whole old ownership group must be
destroyed.

See [`swapchain.cpp`][source-swapchain] and the
[Vulkan Guide's semaphore-reuse guidance][reading-semaphore-reuse].

## Exercise replacement on every test frame

The device-backed recreation scenario presents three frames and replaces
presentation state after each one. That repeatedly exercises:

- waiting for graphics and presentation completion;
- passing `oldSwapchain` into a new swapchain;
- replacing image views, per-image semaphores, depth, pipeline, and fences;
- rewriting the camera uniform; and
- drawing the already compiled AnimatedCube resources through the new state.

The Debug build registers a second version with synchronization validation
enabled through `VK_LAYER_VALIDATE_SYNC=1`. Both scenarios fail when Vulkan
validation reports an error, share the Vulkan CTest resource lock, and have a
30-second timeout:

```shell
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default -R "^(fireEngineTutorialRecreationSmoke|fireEngineTutorialRecreationSyncValidation)$"
```

The scenario deliberately reconstructs presentation at the current size; it
does not ask the operating system to resize or minimise the window. It is a
deterministic lifetime and synchronization test, not proof that a platform
delivered a framebuffer callback or changed the aspect ratio.

Run the normal application and resize, minimise, restore, and close its window
to exercise those event-system boundaries interactively:

```shell
./build/fireEngineTutorial
```

See the scenario in [`main.cpp`][source-main] and its
[`CMakeLists.txt` registration][source-cmake].

## Diagnose presentation replacement failures

### Resizing leaves the old-sized image stretched or clipped

Confirm that the framebuffer-size callback is registered and its flag is
consumed before drawing. Recreation must query the current physical framebuffer
extent, create the new depth image from it, rewrite the view-projection uniform,
and record viewport, scissor, and render area from the replacement swapchain.

### A minimised window consumes a CPU core

Do not poll continuously while either framebuffer dimension is zero. Wait for
window events, then query the current framebuffer again. Keep the closure check
inside that loop so a minimised application can still exit.

### The frame loop hangs after acquisition reports out-of-date

Reset the frame-finished fence only after successful acquisition and command
recording. An acquire-side out-of-date result has no submission that could
signal a freshly reset fence, so the abandoned frame must leave it signalled.

### A presentation fence waits forever on its first use

New presentation fences are unsignalled. Wait only when the corresponding
`presentSubmitted` flag says an earlier `presentKHR()` was associated with that
fence. After the wait succeeds, reset both the Vulkan fence and the bookkeeping
before reuse.

### Validation reports an in-use old swapchain or semaphore

A frame fence or device wait covers graphics submission, not the complete
presentation lifetime. Chain a presentation fence into every present, including
the out-of-date path, and wait for every submitted entry before destroying the
old `PresentationState`.

### Validation reports an incompatible attachment or pipeline

Construct depth and pipeline from the same replacement swapchain. The depth
extent must match its colour extent, and the pipeline's dynamic-rendering
formats must match the colour and depth views supplied during recording.

### Textures or meshes are uploaded again after every resize

The replacement boundary is too broad. `CompiledResources` and
`RenderPreparation` do not depend on presentation extent or format and should
remain outside `PresentationState`. A resize should not call `prepare()` or
advance the asset revision.

### Recreation works until an actual format change

Do not preserve the old pipeline merely because viewport and scissor are
dynamic. Dynamic rendering still requires the pipeline to declare compatible
colour and depth attachment formats. Recreate it from the replacement formats.

### The automated test passes but minimising still fails

The recreation scenario uses the same non-zero framebuffer on each iteration.
It proves replacement and retirement, not callback delivery, zero-extent
waiting, or a changed projection aspect ratio. Exercise those platform events
manually or add a window-system integration harness capable of driving them.

## What this part of release 0.8 gives us

This part of release 0.8 makes presentation replacement an ordinary renderer
operation:

- one `PresentationState` owns the swapchain-compatible replacement lifetime;
- swapchain images, views, render-finished semaphores, depth, pipeline, and
  presentation fences are rebuilt together;
- device, allocator, frame slot, prepared plan, and compiled scene resources
  remain alive;
- the public facade accepts a window and reports zero extent as a transient
  result without exposing Vulkan types;
- resize callbacks, suboptimal results, and out-of-date results converge on one
  application recovery path;
- framebuffer dimensions are re-queried in physical pixels rather than trusted
  from a possibly coalesced callback;
- minimisation waits for events instead of spinning or constructing a zero-area
  swapchain;
- the renderer checks zero extent again to close the event-loop race;
- old device work and presentation operations are both retired before
  replacement;
- `oldSwapchain` is offered to Vulkan while the old C++ owner remains alive;
- depth, attachment-compatible pipeline, viewport state, and camera projection
  follow the replacement extent and formats;
- presentation fences are required through the KHR or equivalent EXT
  swapchain-maintenance path;
- one submitted flag prevents waits on never-submitted unsignalled fences;
- out-of-date presentation is still tracked as enqueued work;
- per-image fence reuse and whole-group retirement share one protocol; and
- bounded recreation and synchronization-validation scenarios exercise three
  consecutive replacements without recompiling the scene.

The renderer can now survive a changing window without confusing presentation
state with scene state. More frames in flight or more sophisticated deferred
retirement can reduce the coarse waits later; the ownership boundary and the
two completion domains remain the foundation those improvements need.

The [closing verification post][verification-post] combines this recreation
path with repeated preparation, fallback texturing, and the renderer's focused
internal ownership boundary to complete the 0.8 walkthrough.

## Recommended reading

- [Vulkan specification: Window System Integration][reading-wsi] — the
  normative surface, swapchain, acquisition, presentation, and retirement
  contracts behind the renderer's recovery path.
- [`VK_KHR_swapchain_maintenance1` reference][reading-maintenance] — the
  extension that adds presentation fences and other swapchain-maintenance
  facilities.
- [`VkSwapchainPresentFenceInfoKHR` reference][reading-present-fence] — the
  structure chained into presentation to report when associated resources may
  be safely recycled.
- [Vulkan Guide: Swapchain Semaphore Reuse][reading-semaphore-reuse] — why the
  binary semaphore waited on by presentation should follow the acquired image.
- [GLFW documentation][reading-glfw] — framebuffer sizing, callbacks, event
  polling, and blocking event waits across supported window systems.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[camera-post]: {% post_url 2026-08-29-adding-camera-depth-and-culling-to-fireengine %}
[frame-in-flight-post]: {% post_url 2026-08-04-preparing-fireengines-first-frame-in-flight %}
[verification-post]: {% post_url 2026-09-02-closing-fireengine-08-with-focused-ownership-and-executable-scenarios %}
[source-renderer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/renderer.hpp>
[source-renderer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/renderer.cpp>
[source-swapchain-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/swapchain.hpp>
[source-swapchain]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/swapchain.cpp>
[source-window-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/platform/window.hpp>
[source-window]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/platform/window.cpp>
[source-debug]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/core/debug.cpp>
[source-device]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/device.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[reading-wsi]: <https://docs.vulkan.org/spec/latest/chapters/VK_KHR_surface/wsi.html>
[reading-maintenance]: <https://docs.vulkan.org/refpages/latest/refpages/source/VK_KHR_swapchain_maintenance1.html>
[reading-present-fence]: <https://docs.vulkan.org/refpages/latest/refpages/source/VkSwapchainPresentFenceInfoKHR.html>
[reading-semaphore-reuse]: <https://docs.vulkan.org/guide/latest/swapchain_semaphore_reuse.html>
[reading-glfw]: <https://www.glfw.org/docs/latest/>
[reading-page]: {% link _tabs/reading.md %}
