---
title: "Preparing fireEngine's first frame in flight"
date: 2026-08-04 11:30:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, synchronization, command-buffers, frame-in-flight, cpp]
description: >-
  Create fireEngine's first graphics command pool, primary command buffer,
  binary semaphores, and fence, then group them into one frame-in-flight owner.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.5"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.4"
---

Release 0.4 gave fireEngine a compiled shader and a graphics pipeline, but no
way to send work through that pipeline. Release 0.5 prepares the objects that
will carry the first frame from the CPU to the graphics queue and, eventually,
to the presentation engine.

The new `FrameInFlight` owner creates a graphics command pool, one primary
command buffer, an image-available semaphore, and a frame-completion fence. The
swapchain also gains one render-finished semaphore per image. That split is the
important design choice in this release: most resources follow the frame slot,
but presentation completion follows the acquired swapchain image.

Nothing is recorded or submitted yet. No image is acquired and no presentation
request is made. Keeping this as a construction-only checkpoint lets the
ownership and synchronization model stand on its own before the render loop
starts changing object state every frame.

This post follows the changes from [release 0.4][release-0-4] to
[release 0.5][release-0-5]. Code links are pinned to 0.5 so the walkthrough
continues to match the published source as fireEngine evolves.

> Source: [fireEngine 0.5]({{ page.release_url }})
>
> Start with the [0.4 graphics-pipeline post][pipeline-post] if you want the
> Slang interface, push-descriptor layout, inline SPIR-V, and dynamic-rendering
> pipeline setup. This post concentrates on command ownership and the
> synchronization state needed for one frame in flight.
{: .prompt-info }

## Introducing commands, synchronization, and a frame in flight

Release 0.5 introduces five connected concepts:

- a **command pool** supplies and recycles the driver-managed memory behind
  command buffers. It belongs to one queue family and must be externally
  synchronized by the application;
- a **command buffer** stores Vulkan commands for later execution. This release
  allocates one primary buffer that can be submitted directly to the graphics
  queue;
- a **semaphore** orders device work without making the CPU wait. Binary
  semaphores will connect image acquisition, graphics submission, and
  presentation;
- a **fence** carries completion in the other direction, from a queue submission
  back to the host. The CPU can wait for it before recycling a frame's command
  and resource state; and
- a **frame in flight** is one reusable slot whose previous GPU submission may
  still be executing while the CPU prepares other work. This release creates a
  single slot, so the CPU will eventually wait for every frame before reusing
  it. More slots can later allow CPU and GPU work to overlap.

Once submission arrives in the next release, the three synchronization objects
will gate different actors:

| Object | Blocks | Until |
| --- | --- | --- |
| Frame-finished fence | The CPU, before it reuses this frame slot | The GPU has finished the slot's previous submission |
| Image-available semaphore | Graphics, before it writes into the acquired image | The presentation engine has released that image |
| Render-finished semaphore | Presentation, before it displays the image | Graphics has finished rendering into it |

Waiting for the fence prevents the CPU from recycling this frame slot's state
while the GPU may still be using it. Once the previous GPU submission signals
the fence, the CPU can prepare the next graphics submission with that slot.

The mechanisms are not interchangeable. The host waits on the fence, while
acquisition, graphics, and presentation use the binary semaphores to order
device work. A fence cannot replace those semaphores, and the frame loop cannot
use a binary semaphore as its CPU-side completion signal.

The class is named `FrameInFlight` even though this checkpoint never submits
its command buffer. The name describes the lifetime the owner is preparing:
once submission arrives, everything inside it will remain reserved until its
fence says that frame has finished.

## Separate frame state from image state

There are two indices in a conventional swapchain loop, even when the first
version uses only one frame slot:

| Index | Owner | Resources in release 0.5 |
| --- | --- | --- |
| Frame slot | `FrameInFlight` | Command pool, command buffer, image-available semaphore, frame-finished fence |
| Acquired image | `Swapchain` | Swapchain image, image view, render-finished semaphore |

The distinction becomes easier to see as two indexed groups:

```text
frame slot 0
    -> graphics command pool
        -> primary command buffer
    -> image-available semaphore
    -> frame-finished fence

swapchain
    -> image 0 -> image view 0
    -> image 1 -> image view 1
    -> image 2 -> image view 2
    -> render-finished semaphores 0..2
       (paired with images by index, not owned by them)
```

The frame index is chosen by the engine. The image index is returned by the
presentation system when an image is acquired, and it does not have to match
the frame index. Treating them as interchangeable is a subtle synchronization
bug that often remains hidden until more than one frame is allowed to overlap.

Release 0.5 establishes the correct boundary before that overlap exists. Going
from one frame in flight to two or three will mean creating more
`FrameInFlight` instances and cycling through them. The number of
render-finished semaphores will continue to follow the number of swapchain
images instead.

## Extend the source tree without changing the shader

The source tree gains one class split across a header and implementation file:

```text
fireEngine-tutorial/
├── include/fire_engine/render/
│   ├── frame_in_flight.hpp    # Per-frame command and synchronization owner
│   └── swapchain.hpp          # Adds per-image presentation semaphores
└── src/
    ├── main.cpp               # Creates and validates the first frame slot
    └── render/
        ├── frame_in_flight.cpp
        └── swapchain.cpp      # Creates one semaphore per swapchain image
```

There is no new dependency and no shader change. `CMakeLists.txt` advances the
project to 0.5.0, adds `frame_in_flight.cpp` to the existing executable, and
updates the CTest description. `vcpkg.json` advances its matching version and
nothing else. The Slang command and generated SPIR-V remain exactly as they
were in release 0.4.

The release also removes `plan.md` and `planoutline.md`, two internal planning
artefacts left in the 0.4 checkpoint. They were not build inputs and their
removal has no effect on the executable or published API documentation.

## Use release, checkpoint, and stage precisely

The 0.5 diff replaces the overloaded word *milestone* across comments and
documentation. From here onwards, a **release** or **version** names the
published tag, a **checkpoint** names its exact buildable source state, and a
**tutorial stage** names one step in the continuing implementation.

This is a vocabulary change rather than a functional one. It explains the
otherwise unrelated edits in `main.cpp`, `pipeline.hpp`, `vertex.hpp`,
`allocator.cpp`, `device.cpp`, `pipeline.cpp`, and `README.md` without turning
them into new rendering work.

## Give one frame a single RAII owner

The public surface of `FrameInFlight` exposes the objects a future frame loop
will need without transferring their ownership:

```cpp
class FrameInFlight final
{
public:
    explicit FrameInFlight(const Device& device);
    ~FrameInFlight() = default;

    FrameInFlight(const FrameInFlight&) = delete;
    FrameInFlight& operator=(const FrameInFlight&) = delete;
    FrameInFlight(FrameInFlight&&) = delete;
    FrameInFlight& operator=(FrameInFlight&&) = delete;

    void resetCommands() const;

    [[nodiscard]] const vk::raii::CommandBuffer& commandBuffer() const noexcept;
    [[nodiscard]] const vk::raii::Semaphore& imageAvailable() const noexcept;
    [[nodiscard]] const vk::raii::Fence& frameFinished() const noexcept;

private:
    vk::raii::CommandPool commandPool_{nullptr};
    vk::raii::CommandBuffers commandBuffers_{nullptr};
    vk::raii::Semaphore imageAvailable_{nullptr};
    vk::raii::Fence frameFinished_{nullptr};
};
```

The default destructor delegates cleanup to the Vulkan-Hpp RAII members. Their
declaration order, covered below, preserves the one parent-child lifetime that
needs to be expressed inside the class.

Copying is invalid because every member has unique Vulkan ownership. Moving is
also disabled deliberately. A frame slot is a stable bundle whose command
buffer, synchronization objects, and future resources should keep one identity
while the engine cycles through slots.

That does not prevent a later renderer from storing several frames. With a
compile-time frame count, a `std::array<FrameInFlight, N>` can construct each
element directly in place through guaranteed copy elision. The class does not
need to become movable merely to live in a fixed collection.

The accessors return `const` references to Vulkan-Hpp RAII handles. They let the
future frame loop name the underlying Vulkan objects while `FrameInFlight`
retains responsibility for releasing them.

See the complete [`frame_in_flight.hpp`][source-frame-header].

## Create a pool for graphics commands

The pool construction comes from [`frame_in_flight.cpp`][source-frame].

Command buffers are allocated from a command pool associated with a queue
family. The frame uses the family already selected for graphics work:

```cpp
const vk::CommandPoolCreateInfo commandPoolInfo{
    .queueFamilyIndex = device.graphicsQueueFamily(),
};
commandPool_ =
    vk::raii::CommandPool{device.logicalDevice(), commandPoolInfo};
```

That association is a capability boundary. A command buffer from this pool can
record commands supported by the graphics family and can be submitted to a
queue from that family. The pool does not itself choose a queue or submit
anything.

The create info has no flags. In particular, it omits
`vk::CommandPoolCreateFlagBits::eResetCommandBuffer`. That flag would allow an
individual command buffer to be reset independently. fireEngine instead gives
each frame its own pool and plans to recycle the whole pool at once, leaving the
driver free to manage its command storage as one arena rather than supporting
independent buffer resets that this design does not need.

Command pools are [externally synchronized][vulkan-command-buffers]. Vulkan
does not put a lock around allocation, reset, destruction, or recording through
buffers from the same pool. A future multi-threaded renderer must ensure that
only one host thread uses a frame's pool at a time.

## Allocate one primary command buffer

The allocation and accessor excerpts come from
[`frame_in_flight.cpp`][source-frame].

Once the pool exists, the constructor allocates exactly one command buffer:

```cpp
const vk::CommandBufferAllocateInfo commandBufferInfo{
    .commandPool = *commandPool_,
    .level = vk::CommandBufferLevel::ePrimary,
    .commandBufferCount = 1,
};
commandBuffers_ =
    vk::raii::CommandBuffers{device.logicalDevice(), commandBufferInfo};
```

A primary command buffer can be submitted directly to a queue. Secondary
command buffers are instead executed from a primary command buffer. They can be
useful for dividing recording across systems or threads, but would add another
layer to a renderer that currently needs one short sequence of commands.

Vulkan-Hpp represents an allocation of command buffers with the
`vk::raii::CommandBuffers` container, even when the request count is one. The
accessor returns the first element:

```cpp
const vk::raii::CommandBuffer& FrameInFlight::commandBuffer() const noexcept
{
    return commandBuffers_.front();
}
```

Successful allocation returns the requested number of handles, so `front()` is
valid after the constructor completes. If Vulkan cannot allocate the buffer,
the RAII constructor throws and no incomplete `FrameInFlight` escapes.

The newly allocated buffer begins in the **initial** state. It contains no
commands and cannot be submitted until a later release begins recording and
ends it successfully.

## Recycle commands through the whole pool

`resetCommands()` is deliberately small:

```cpp
void FrameInFlight::resetCommands() const
{
    commandPool_.reset();
}
```

Resetting the pool returns every command buffer allocated from it to the
initial state. Because the pool was not created with `eResetCommandBuffer`, this
whole-pool operation is the legal recycling path. Neither resetting the
individual buffer nor letting `begin()` reset it implicitly is available
without that flag.

The eventual lifecycle will be:

```text
allocate
    -> initial
        -> begin recording
            -> recording
                -> end recording
                    -> executable
                        -> submit
                            -> pending
                                -> frame fence signals
                                    -> reset pool
                                        -> initial
```

The pending state is the critical boundary. Resetting a pool while the GPU is
still executing any command buffer allocated from it is invalid. The frame loop
will first wait for `frameFinished()`, proving that the previous submission has
completed, and only then recycle the command pool.

The method is `const` because Vulkan-Hpp's pool reset changes driver-managed
state rather than the C++ handle stored by `FrameInFlight`. That says nothing
about thread safety: the external-synchronization requirement still applies to
the pool and its command buffer.

Release 0.5 does not call `resetCommands()`. Adding the operation now records
the intended reuse policy beside the pool creation flags, where the two choices
can be reviewed together.

See the complete [`frame_in_flight.cpp`][source-frame].

## Create the frame's acquisition semaphore

The semaphore construction comes from [`frame_in_flight.cpp`][source-frame].

The frame owns the semaphore that will announce that a swapchain image is
available:

```cpp
constexpr vk::SemaphoreCreateInfo semaphoreInfo{};
imageAvailable_ =
    vk::raii::Semaphore{device.logicalDevice(), semaphoreInfo};
```

There is no `vk::SemaphoreTypeCreateInfo` in the `pNext` chain, so Vulkan
creates a binary semaphore. It has two logical states: unsignaled and signaled.
The application does not set or clear those states directly on the host. They
change as part of the device operations that signal and wait on the semaphore.

In the future frame loop, swapchain acquisition will signal
`imageAvailable()`. The graphics submission will wait on it before touching
the acquired image. That wait both orders rendering after acquisition and
consumes the binary signal so the frame can reuse the same semaphore on its
next turn.

This semaphore follows the frame slot because the corresponding graphics
submission consumes it before that frame's fence signals. Once the CPU has
waited for the fence, both the command buffer and acquisition semaphore are
ready to be used by that slot again.

## Start the completion fence in the signaled state

The fence construction comes from [`frame_in_flight.cpp`][source-frame].

The other synchronization object owned by the frame connects GPU completion
back to the CPU:

```cpp
const vk::FenceCreateInfo fenceInfo{
    .flags = vk::FenceCreateFlagBits::eSignaled,
};
frameFinished_ = vk::raii::Fence{device.logicalDevice(), fenceInfo};
```

A queue submission can associate work with an unsignaled fence. The device
signals it after that submission finishes, and the host can wait for the signal
before modifying resources used by the submitted work.

The frame loop will wait at the start of every reuse. On the first iteration,
however, no previous submission exists to signal the fence. Creating it already
signaled lets the first wait complete immediately without a separate
first-frame branch.

After the wait, the host will reset the fence to unsignaled before associating
it with a new submission. The ordering around that reset matters. Swapchain
acquisition can report that the swapchain is out of date and cause the frame to
be abandoned. Resetting the fence before acquisition would then leave an
unsignaled fence with no future submission to signal it, so the next iteration
could wait forever.

The intended shape is therefore:

```text
wait for frame-finished fence
    -> acquire a swapchain image
        -> if acquisition cannot continue, leave the fence signaled and return
        -> reset the fence
        -> reset and record the command buffer
        -> submit work with the fence
```

Release 0.5 only creates and checks the fence. Writing this ordering into the
class documentation now makes the future render loop's deadlock boundary
explicit before an out-of-date swapchain path exists.

## Keep presentation semaphores with swapchain images

The semaphore waited on by presentation has a different reuse rule. The
swapchain creates one for every image it reports:

```cpp
[[nodiscard]] std::vector<vk::raii::Semaphore>
createRenderFinishedSemaphores(const vk::raii::Device& device,
                               std::size_t imageCount)
{
    constexpr vk::SemaphoreCreateInfo createInfo{};

    std::vector<vk::raii::Semaphore> semaphores;
    semaphores.reserve(imageCount);
    for (std::size_t imageIndex = 0; imageIndex < imageCount; ++imageIndex)
    {
        semaphores.emplace_back(device, createInfo);
    }
    return semaphores;
}
```

The helper again creates binary semaphores. Construction happens after the
swapchain images and their views have been retrieved:

```cpp
swapchain_ = vk::raii::SwapchainKHR{device.logicalDevice(), createInfo};
images_ = swapchain_.getImages();
imageViews_ =
    createImageViews(device.logicalDevice(), images_, surfaceFormat.format);
renderFinished_ =
    createRenderFinishedSemaphores(device.logicalDevice(), images_.size());
```

The future submission will signal the entry selected by the acquired image
index. Presentation of that same image will wait on the same entry:

```text
acquire image k
    -> signal frame.imageAvailable
        -> graphics submission waits for frame.imageAvailable
        -> graphics submission signals swapchain.renderFinished[k]
        -> graphics submission signals frame.frameFinished fence on completion
            -> presentation waits for swapchain.renderFinished[k]
```

It is tempting to put `renderFinished` in `FrameInFlight` beside
`imageAvailable`, but the frame fence does not prove that presentation has
finished waiting on a semaphore. The fence belongs to the graphics submission;
presentation is a later queue operation with its own lifetime. Re-signaling a
binary semaphore while an earlier presentation may still be waiting on it is
invalid.

The Vulkan Guide's
[swapchain semaphore reuse][vulkan-swapchain-semaphore-reuse] guidance uses the
same solution: index presentation wait semaphores by swapchain image rather
than frame in flight. Acquiring image `k` and waiting for the acquisition
signal guarantees that its earlier presentation has released that image,
including its wait on the corresponding semaphore. Only then can
`renderFinished[k]` be used again.

This arrangement also makes swapchain recreation easier to reason about. A new
swapchain may contain a different number of images, so its per-image
semaphores should be created and replaced with those images. Frame slots can
remain a separate collection with a count chosen by the engine.

Release 0.5 never signals or waits on these semaphores, so shutdown has no
pending presentation state yet. Once presentation is introduced, the 0.5
design requires a device wait before the old swapchain goes away. That
precondition applies both at shutdown and during recreation, because replacing
the swapchain also destroys its old presentation semaphores. It complements
the safe per-image reuse scheme; indexing alone does not make an in-use
semaphore safe to destroy.

See the complete [`swapchain.hpp`][source-swapchain-header] and
[`swapchain.cpp`][source-swapchain].

## Encode destruction order in the owners

The member-order excerpts come from
[`frame_in_flight.hpp`][source-frame-header],
[`swapchain.hpp`][source-swapchain-header], and [`main.cpp`][source-main].

Vulkan-Hpp releases RAII members automatically, but C++ still destroys class
members in reverse declaration order. `FrameInFlight` uses that rule to encode
the command-buffer dependency:

```cpp
vk::raii::CommandPool commandPool_{nullptr};
vk::raii::CommandBuffers commandBuffers_{nullptr};
vk::raii::Semaphore imageAvailable_{nullptr};
vk::raii::Fence frameFinished_{nullptr};
```

Destruction therefore proceeds as:

```text
frame-finished fence
    -> image-available semaphore
        -> command buffer
            -> command pool
```

The command buffer is freed before the pool that supplied its storage. The
semaphore and fence have no parent-child relationship with the pool; all four
objects instead depend on the logical device outliving them.

`Swapchain` uses the same language rule for the dependency it does have:

```cpp
vk::raii::SwapchainKHR swapchain_{nullptr};
std::vector<vk::Image> images_;
std::vector<vk::raii::ImageView> imageViews_;
std::vector<vk::raii::Semaphore> renderFinished_;
// Format, present mode, and extent members omitted here.
```

Reverse destruction releases the render-finished semaphores and image views
before the swapchain. Views must die before the parent swapchain that supplied
their images. The semaphores are owned by the logical device instead, so their
position relative to the views and swapchain carries no parent-child meaning;
their safety comes from the completion precondition described above.

`main()` preserves that wider lifetime:

```cpp
fire_engine::Glfw glfw;
const fire_engine::Window window{800, 600, applicationName};
const fire_engine::Device device{glfw, window, applicationName};
const fire_engine::MemoryAllocator allocator{device};
const fire_engine::Swapchain swapchain{device, window};
const fire_engine::Pipeline pipeline{device, swapchain.imageFormat()};
const fire_engine::FrameInFlight frame{device};
```

Because local variables also die in reverse declaration order, the frame is
released before the pipeline, swapchain, allocator, device, window, and GLFW
library. No destructor needs a manual cleanup sequence.

## Make the smoke test check relationships, not handles

Every Vulkan-Hpp RAII constructor throws if object creation fails. Reaching the
validation block already proves that the command pool, command buffer,
semaphores, and fence have valid handles. `main()` instead checks properties
that construction alone does not prove.

First, the swapchain must contain one presentation semaphore per image:

```cpp
if (swapchain.imageCount() == 0 ||
    swapchain.imageViews().size() != swapchain.images().size() ||
    swapchain.renderFinished().size() != swapchain.imageCount())
{
    throw std::runtime_error("Vulkan returned an incomplete swapchain");
}
```

Then the fence must reflect the state requested at creation:

```cpp
if (frame.frameFinished().getStatus() != vk::Result::eSuccess)
{
    throw std::runtime_error(
        "The frame-finished fence was not initially signaled");
}
```

`vk::Result::eSuccess` means the fence is signaled. An unsignaled fence reports
`eNotReady`, which would expose a mismatch before the first frame loop turns it
into a hang.

The command pool and buffer do not need equivalent handle checks. Their RAII
construction guarantees valid handles, while recording and submission are
outside this release. The smoke test concentrates on the new invariants it can
meaningfully observe.

See the complete [`main.cpp`][source-main].

## Keep the build changes mechanical

Release 0.5 does not introduce a build-system technique. The existing CMake
target receives `src/render/frame_in_flight.cpp`, and both project manifests
advance from 0.4.0 to 0.5.0. The dependency list, imported targets, shader
custom command, warning policy, and platform configuration do not change.

CTest still runs the executable as a startup smoke test. Its comment now states
the larger contract: success reaches the Vulkan device, allocator, swapchain,
pipeline, command buffer, and both per-frame and per-image synchronization
objects.

This is the useful result of the earlier target-based setup. Adding ordinary
C++ source to the same executable automatically carries forward include paths,
language requirements, compile definitions, warnings, linked Vulkan targets,
and CI coverage without giving this release another build-system story.

See the complete [`CMakeLists.txt`][source-cmake] and
[`vcpkg.json`][source-vcpkg].

## Configure, build, and run release 0.5

The compiler, build-tool, vcpkg, and Vulkan prerequisites remain the same as in
the [foundation post][foundation-post]. Clone the checkpoint directly with:

```shell
git clone --branch 0.5 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

Configure and build through the existing presets:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

Run it on macOS or Linux with:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

The release 0.5 run was captured on an Apple M2 Pro running macOS 26, using the
KosmicKrisp driver from the LunarG Vulkan SDK:

```text
Selected Vulkan 1.4 device: Apple M2 Pro
Graphics queue family: 0
Present queue family: 0
Logical device and queues created.
VMA allocator created.
Swapchain created: 3 images at 1600x1200 (B8G8R8A8Srgb, Fifo), 3 presentation semaphores.
Pipeline layout and dynamic-rendering pipeline created.
Primary command buffer and one-frame synchronization created.
```

The matching image and semaphore counts make the ownership split visible in
the output. The final line proves that construction reached the primary command
buffer, acquisition semaphore, and initially signaled fence.

The window still closes immediately. That is expected: no event loop acquires
an image or records, submits, and presents a command buffer yet.

The same path remains registered as a CTest smoke test:

```shell
ctest --preset default
```

## Extend CI without changing the workflow

`ci.yml` does not change. Its existing discovery rules and target build already
cover the new code:

- `clang-format` checks every C and C++ source below `src/` and `include/`, so
  both `frame_in_flight` files join the formatting gate automatically;
- `clang-tidy` discovers every `.cpp` below `src/`, while the executable target
  supplies the compile command for the new implementation;
- macOS and Windows build the expanded executable with their existing
  toolchains; and
- Linux still runs CTest with Lavapipe inside Xvfb.

That Linux smoke test now creates a command pool and command buffer for the
selected graphics family, one acquisition semaphore, one signaled fence, and a
presentation semaphore for every image returned by its virtual swapchain. It
does not yet exercise synchronization transitions because no queue submission
or presentation occurs.

See the complete [`ci.yml`][source-ci].

## Diagnose the new failure boundaries

Release 0.5 adds a small number of construction failures and records several
lifecycle rules that become important when the frame loop arrives.

### Command or synchronization creation throws `vk::SystemError`

The logical device and graphics family have already been validated by earlier
startup stages. A failure while creating the command pool, allocating its
buffer, or creating a semaphore or fence therefore points to an invalid create
contract, exhausted host or device resources, or a driver failure. Validation
output in a Debug build should identify the object and invalid field when the
problem is contractual.

### The swapchain is reported as incomplete

The smoke test now requires a non-empty image list, one view per image, and one
render-finished semaphore per image. A mismatch indicates that construction did
not preserve the per-image relationship on which later presentation
synchronization depends.

The RAII constructors already make a partial semaphore-creation failure
exception-safe: any entries created before the exception are released as the
vector unwinds, and no incomplete `Swapchain` escapes.

### The frame-finished fence is not initially signaled

The requested `eSignaled` state did not take effect. Release 0.5 reports this
immediately rather than letting the first future fence wait block with no prior
submission capable of satisfying it.

### Validation reports command-pool synchronization errors later

No such error should appear in this checkpoint because the pool is never reset
or recorded from multiple threads. When recording arrives, wait for the frame's
submission to complete before calling `resetCommands()`, and prevent concurrent
host access to both the pool and its command buffer.

### A later frame hangs after swapchain acquisition fails

This checkpoint cannot enter that path yet, but the class documentation records
the prevention: do not reset the frame fence until image acquisition has
succeeded and the frame is certain to submit. An abandoned frame must leave its
fence signaled so the next reuse can pass the wait.

### Validation reports a presentation semaphore being re-signaled

Select `renderFinished` with the acquired swapchain image index, not the current
frame index. The per-image vector exists specifically to avoid re-signaling a
binary semaphore that presentation may still be waiting on.

## What release 0.5 gives us

Release 0.4 established a graphics pipeline. Release 0.5 establishes the
command and synchronization ownership needed to put work through it:

- one `FrameInFlight` class owns per-frame command and synchronization state;
- its command pool targets the selected graphics queue family;
- omitting per-buffer reset support chooses whole-pool recycling;
- one primary command buffer is allocated directly from that pool;
- `resetCommands()` returns the buffer to its initial state after prior work
  completes;
- the class records Vulkan's external-synchronization requirement without
  pretending that a `const` method is thread-safe;
- one binary image-available semaphore follows the frame slot;
- one initially signaled fence gives the CPU a completion boundary and lets the
  first future frame begin without a special case;
- fence documentation preserves the acquisition-before-reset rule needed to
  avoid an out-of-date-swapchain deadlock;
- one binary render-finished semaphore follows every swapchain image;
- frame-indexed and image-indexed state remain distinct before multiple frames
  can overlap;
- destroying or recreating a swapchain requires a device wait before its
  presentation semaphores go away;
- RAII declaration order frees the command buffer before its pool and the frame
  before its device; and
- the startup smoke test verifies the per-image counts and initial fence state.

There is still no recorded command, acquired swapchain image, queue submission,
draw call, or presentation request. The vertex and uniform resources described
by the pipeline are also still unallocated.

That makes 0.5 a useful boundary. The next stage can wait for the frame slot,
acquire an image, reset and record the primary command buffer, submit it with
Synchronization 2, and present the completed image without first deciding who
owns each synchronization object.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan] — a detailed treatment of command
  pools, command buffers, queue submission, semaphores, fences, and
  presentation. Its examples predate current Vulkan, but the ownership and
  synchronization model remains valuable.
- [How to Vulkan][reading-how-to-vulkan] — a compact, code-first modern Vulkan
  guide whose command-buffer and synchronization sections provide a useful
  comparison with this tutorial's Vulkan-Hpp RAII design.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-4]: {{ page.previous_release_url }}
[release-0-5]: {{ page.release_url }}
[pipeline-post]: {% post_url 2026-08-03-creating-fireengines-first-graphics-pipeline %}
[foundation-post]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[source-cmake]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/CMakeLists.txt
[source-vcpkg]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/vcpkg.json
[source-frame-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/include/fire_engine/render/frame_in_flight.hpp
[source-frame]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/src/render/frame_in_flight.cpp
[source-swapchain-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/include/fire_engine/render/swapchain.hpp
[source-swapchain]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/src/render/swapchain.cpp
[source-main]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/src/main.cpp
[source-ci]: https://github.com/nnewson/fireEngine-tutorial/blob/0.5/.github/workflows/ci.yml
[vulkan-command-buffers]: https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html
[vulkan-swapchain-semaphore-reuse]: https://docs.vulkan.org/guide/latest/swapchain_semaphore_reuse.html
[reading-page]: {% link _tabs/reading.md %}
[reading-vulkan]: https://www.vulkanprogrammingguide.com
[reading-how-to-vulkan]: https://howtovulkan.com
