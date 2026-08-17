---
title: "Rendering fireEngine's first triangle"
date: 2026-08-05 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, rendering, triangle, buffers, synchronization, dynamic-rendering, cpp]
description: >-
  Upload vertex and uniform data, record a Vulkan 1.4 dynamic-rendering draw,
  submit it with Synchronization 2, and present fireEngine's first triangle.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.5"
---

Release 0.5 prepared one frame in flight: a command pool, primary command
buffer, acquisition semaphore, completion fence, and one presentation
semaphore per swapchain image. Release 0.6 puts every one of those objects to
work and renders fireEngine's first triangle.

The application now uploads three coloured vertices and a per-frame transform,
records a dynamic-rendering draw, submits it to the graphics queue with
Synchronization 2, and sends the completed swapchain image to the presentation
queue. The GLFW window stays open until the user closes it, while a bounded
`--frames` mode lets CTest render one complete frame and exit automatically.

This is the first release where successful startup is no longer the visible
result. A pixel reaches the screen only when buffer ownership, shader
interfaces, command state, image layouts, synchronization scopes, queue
capabilities, and presentation lifetime all agree.

This post follows the changes from [release 0.5][release-0-5] to
[release 0.6][release-0-6]. Code links are pinned to 0.6 so the walkthrough
continues to match the published source as fireEngine evolves.

> Source: [fireEngine 0.6]({{ page.release_url }})
>
> Start with the [0.5 frame-in-flight post][frame-post] for the command and
> synchronization ownership prepared by the previous checkpoint. This post
> concentrates on buffer data, command recording, queue submission, and the
> first presented frame.
{: .prompt-info }

## Introducing the first complete rendering path

Release 0.6 introduces six connected pieces:

- an **allocated buffer** owns a Vulkan buffer and the VMA allocation bound to
  it, providing one reusable path for host-written vertex and uniform data;
- a **vertex buffer** stores the three positions and colours consumed by the
  pipeline's vertex-input interface;
- a **uniform buffer** stores one 4×4 transform for each frame slot and reaches
  the vertex shader through a push descriptor;
- a **renderer** owns the triangle and frame state, then hides the acquire,
  record, submit, and present sequence behind `renderFrame()`;
- **dynamic rendering commands** describe the colour attachment directly,
  without creating a render pass or framebuffer; and
- **[Synchronization 2][vulkan-synchronization2]** gives image barriers and
  queue submission explicit stage and access scopes.

Traditional Vulkan rendering uses a render-pass object to describe attachment
use and a `VkFramebuffer` object to associate specific attachment image views
with that description. These objects remain supported and useful. They are
different from GLFW's framebuffer size, which is simply the drawable window
size in pixels.

The vertex buffer and uniform buffer solve different shader inputs. The vertex
buffer is an array: three `Vertex` values are fetched once per vertex. The
uniform buffer is shared draw state: one `FrameUniforms` value supplies the
same transform to all three vertices. A uniform buffer is therefore not "for"
the vertex buffer, even though both are read by the vertex stage.

There is also still no allocated descriptor set. The pipeline has a
descriptor-set layout, but Vulkan 1.4 push descriptors copy one descriptor
write directly into the command buffer. That distinction keeps this first draw
free from descriptor-pool and descriptor-set allocation while preserving the
same shader-visible set and binding model.

## Extend the ownership and execution chains

The new C++ ownership relationships are:

```text
main
    -> GLFW
    -> Window
    -> Device
    -> MemoryAllocator
    -> Swapchain
    -> Pipeline
    -> Renderer
        -> triangle AllocatedBuffer
        -> FrameInFlight
            -> uniform AllocatedBuffer
            -> command pool
                -> primary command buffer
            -> image-available semaphore
            -> frame-finished fence
```

`Renderer` borrows `Device`, `Swapchain`, and `Pipeline`. Its two
`AllocatedBuffer` objects borrow the VMA allocator. Declaration order in
`main()` makes the renderer die before every owner it depends on.

One call to `renderFrame()` follows a different, execution-time chain:

```text
wait for the frame fence
    -> acquire a swapchain image
        -> reset the command pool
            -> record commands for the acquired image
                -> reset the frame fence
                    -> submit to the graphics queue
                        -> present through the presentation queue
```

The two diagrams answer different questions. Ownership says which objects must
outlive others. Execution says which operations must be ordered before the
next frame can safely reuse those objects.

The source tree gains two new rendering classes and extends the owners prepared
by earlier releases:

```text
fireEngine-tutorial/
├── include/fire_engine/render/
│   ├── buffer.hpp             # Vulkan buffer plus VMA allocation
│   ├── frame_in_flight.hpp    # Adds one uniform buffer per frame slot
│   └── renderer.hpp           # Owns and executes the triangle render path
└── src/
    ├── main.cpp               # Persistent event loop and bounded test mode
    ├── platform/window.cpp    # Event polling and close-state accessors
    └── render/
        ├── buffer.cpp
        ├── frame_in_flight.cpp
        └── renderer.cpp
```

The [`triangle.slang` shader][source-shader] is unchanged. Release 0.4 already
defined its vertex attributes and set-zero uniform binding; release 0.6
supplies the data that those interfaces were waiting for.

## Give Vulkan buffers one VMA-backed owner

`MemoryAllocator` established VMA in release 0.3, but no allocation used it.
`AllocatedBuffer` now groups a Vulkan buffer with the allocation bound to it:

```cpp
class AllocatedBuffer final
{
public:
    AllocatedBuffer(const MemoryAllocator& allocator,
                    vk::DeviceSize size,
                    vk::BufferUsageFlags usage);
    ~AllocatedBuffer();

    AllocatedBuffer(const AllocatedBuffer&) = delete;
    AllocatedBuffer& operator=(const AllocatedBuffer&) = delete;
    AllocatedBuffer(AllocatedBuffer&&) = delete;
    AllocatedBuffer& operator=(AllocatedBuffer&&) = delete;

    void write(std::span<const std::byte> bytes,
               vk::DeviceSize offset = 0) const;

    [[nodiscard]] vk::Buffer handle() const noexcept;
    [[nodiscard]] vk::DeviceSize size() const noexcept;

private:
    VmaAllocator_T* allocator_ = nullptr;
    VmaAllocation_T* allocation_ = nullptr;
    vk::Buffer buffer_{};
    vk::DeviceSize size_ = 0;
};
```

The allocator pointer is borrowed. It must outlive the buffer, which is why
`MemoryAllocator` appears before `Renderer` in `main()`. Copy and move are both
disabled so that allocation ownership and the borrowed allocator lifetime stay
explicit.

Construction first rejects an empty resource:

```cpp
if (size == 0)
{
    throw std::invalid_argument("A Vulkan buffer cannot have zero size");
}
```

It then describes one exclusive buffer and asks VMA to select host-visible
memory suitable for sequential writes:

```cpp
VkBufferCreateInfo bufferInfo{};
bufferInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
bufferInfo.size = size;
bufferInfo.usage = static_cast<VkBufferUsageFlags>(usage);
bufferInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

VmaAllocationCreateInfo allocationInfo{};
allocationInfo.flags =
    VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT;
allocationInfo.usage = VMA_MEMORY_USAGE_AUTO;
```

The usage flag differs between instances: vertex data requests
`eVertexBuffer`, while frame data requests `eUniformBuffer`. Exclusive sharing
is sufficient because only the graphics queue reads either resource. The
presentation queue operates on swapchain images, not these buffers.

`VMA_MEMORY_USAGE_AUTO` leaves memory-type selection to VMA. The host-access
flag constrains that choice so the CPU can write directly. This is a pragmatic
first-triangle path; larger static meshes would normally be staged into
device-local memory instead of remaining host-visible.

VMA creates the buffer and allocation together:

```cpp
VkBuffer buffer = VK_NULL_HANDLE;
const VkResult result = vmaCreateBuffer(
    allocator_, &bufferInfo, &allocationInfo,
    &buffer, &allocation_, nullptr);
if (result != VK_SUCCESS)
{
    throw std::runtime_error(
        "VMA buffer creation failed: " +
        vk::to_string(static_cast<vk::Result>(result)));
}
buffer_ = buffer;
```

The matching destructor releases the same pair through VMA:

```cpp
AllocatedBuffer::~AllocatedBuffer()
{
    vmaDestroyBuffer(allocator_, static_cast<VkBuffer>(buffer_), allocation_);
}
```

This class uses a custom owner rather than Vulkan-Hpp RAII because VMA, not
`vkDestroyBuffer` and `vkFreeMemory` separately, must undo the combined
creation.

See the complete [`buffer.hpp`][source-buffer-header] and
[`buffer.cpp`][source-buffer].

## Make uploads bounded and coherent

`write()` accepts bytes so the same buffer owner can upload any trivially
represented resource:

```cpp
void AllocatedBuffer::write(std::span<const std::byte> bytes,
                            vk::DeviceSize offset) const
{
    const vk::DeviceSize byteCount = bytes.size();
    if (offset > size_ || byteCount > size_ - offset)
    {
        throw std::out_of_range("Buffer upload exceeds the allocation");
    }
    if (bytes.empty())
    {
        return;
    }

    const VkResult result = vmaCopyMemoryToAllocation(
        allocator_, bytes.data(), allocation_, offset, byteCount);
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(
            "VMA buffer upload failed: " +
            vk::to_string(static_cast<vk::Result>(result)));
    }
}
```

The bounds check uses subtraction only after proving that `offset` is inside
the allocation, avoiding overflow in an `offset + byteCount` comparison. An
empty write is a valid no-op.

Host-coherent memory makes CPU writes visible to the device without an explicit
cache flush. Other host-visible memory requires a flush before the GPU can
reliably read those writes. `vmaCopyMemoryToAllocation()` temporarily maps the
allocation, copies the bytes, and handles that distinction for the caller.

Both release 0.6 uploads happen during construction, before any queue
submission can read the buffers. Future per-frame animation can reuse the same
method after waiting for that frame slot's fence.

## Upload three vertices once

The renderer defines a triangle directly in normalized device coordinates:

```cpp
constexpr std::array kTriangleVertices = {
    Vertex{.position = {0.0F, -0.6F},
           .color = {1.0F, 0.2F, 0.1F}},
    Vertex{.position = {0.6F, 0.6F},
           .color = {0.1F, 1.0F, 0.2F}},
    Vertex{.position = {-0.6F, 0.6F},
           .color = {0.2F, 0.3F, 1.0F}},
};
```

With the positive viewport height used later, negative Y appears towards the
top of the framebuffer and positive Y towards the bottom, so the first vertex
forms the triangle's upper point. Culling remains disabled, so this release does
not depend on a front-face winding convention.

`Renderer` uploads values of the same `Vertex` type that `Pipeline` uses to
calculate the binding stride and attribute offsets. That shared type keeps the
uploaded byte layout and those calculations tied together. The Vulkan formats
and locations are still stated separately, so they must be kept in agreement
with the shader's location-zero `float2` position and location-one `float3`
colour.

`Renderer` creates and populates the vertex buffer in its constructor:

```cpp
Renderer::Renderer(const Device& device,
                   const MemoryAllocator& allocator,
                   const Swapchain& swapchain,
                   const Pipeline& pipeline)
    : device_{device},
      swapchain_{swapchain},
      pipeline_{pipeline},
      vertexBuffer_{allocator,
                    sizeof(kTriangleVertices),
                    vk::BufferUsageFlagBits::eVertexBuffer},
      frame_{device, allocator}
{
    vertexBuffer_.write(
        std::as_bytes(std::span{kTriangleVertices}));
}
```

The upload occurs once. Every frame binds the same immutable buffer and issues
one non-indexed draw, so there is no index buffer or per-frame vertex copy yet.

## Give each frame its own uniform buffer

The shader's `FrameUniforms` contains one column-major `float4x4`. C++ mirrors
that contract explicitly:

```cpp
struct alignas(16) FrameUniforms
{
    std::array<float, 16> transform;
};

static_assert(sizeof(FrameUniforms) == 16 * sizeof(float));
static_assert(alignof(FrameUniforms) == 16);
```

The 16-byte alignment and 64-byte size match the shader's
`Std140DataLayout`. Compile-time assertions turn an accidental representation
change into a build failure instead of distorted geometry.

`FrameInFlight` now creates one uniform buffer alongside its commands and
synchronization:

```cpp
FrameInFlight::FrameInFlight(const Device& device,
                             const MemoryAllocator& allocator)
    : uniformBuffer_{allocator,
                     sizeof(FrameUniforms),
                     vk::BufferUsageFlagBits::eUniformBuffer}
{
    constexpr FrameUniforms initialUniforms{
        .transform = {
            1.0F, 0.0F, 0.0F, 0.0F,
            0.0F, 1.0F, 0.0F, 0.0F,
            0.0F, 0.0F, 1.0F, 0.0F,
            0.0F, 0.0F, 0.0F, 1.0F,
        },
    };
    uniformBuffer_.write(
        std::as_bytes(std::span{&initialUniforms, 1}));

    // Command and synchronization creation follows.
}
```

Identity leaves the clip-space positions unchanged. Its values look the same in
row-major and column-major order, so this initializer cannot establish the
matrix convention by itself. The `-matrix-layout-column-major` option in
[`CMakeLists.txt`][source-cmake] makes Slang's expected layout explicit.

The buffer follows the frame slot because its contents may eventually change
every frame. With multiple frames in flight, each slot can update its own
transform after waiting for its fence without racing a previous submission
that still reads another slot's data.

See the complete [`frame_in_flight.hpp`][source-frame-header] and
[`frame_in_flight.cpp`][source-frame].

## Give the frame loop one renderer owner

`Renderer` groups the resources it owns and borrows the stable objects that
define the device and rendering target:

```cpp
class Renderer final
{
public:
    Renderer(const Device& device,
             const MemoryAllocator& allocator,
             const Swapchain& swapchain,
             const Pipeline& pipeline);
    ~Renderer() noexcept;

    [[nodiscard]] RenderResult renderFrame();
    void waitIdle();

private:
    void recordCommands(std::uint32_t imageIndex) const;

    const Device& device_;
    const Swapchain& swapchain_;
    const Pipeline& pipeline_;
    AllocatedBuffer vertexBuffer_;
    FrameInFlight frame_;
    bool workMayBePending_ = false;
};
```

`main()` retains the platform event loop and high-level policy. `Renderer`
handles the Vulkan sequence for one frame. This keeps window-close behaviour,
the `--frames` limit used by the automated smoke test, and
swapchain-recreation policy out of the command-recording implementation.

The class is immovable because its borrowed references and owned resources form
one stable lifetime. A later multi-frame renderer can extend its frame storage
without changing that external boundary.

See the complete [`renderer.hpp`][source-renderer-header].

## Wait before reusing the frame slot

`renderFrame()` starts on the host by waiting indefinitely for the previous
submission associated with this frame:

```cpp
const vk::Result fenceResult = logicalDevice.waitForFences(
    *frame_.frameFinished(),
    vk::True,
    std::numeric_limits<std::uint64_t>::max());
if (fenceResult != vk::Result::eSuccess)
{
    throw vk::SystemError{
        vk::make_error_code(fenceResult),
        "Waiting for the frame fence"};
}
```

Release 0.5 created the fence signaled, so the first wait returns immediately.
After a successful submission, the fence signals only when that graphics work
has completed. The wait therefore makes it safe to reset the command pool and,
in future releases, rewrite the uniform buffer belonging to this frame slot.

One frame in flight deliberately serializes CPU reuse behind every submitted
frame. It is simple and correct, but does not let the CPU prepare frame N+1
while the GPU executes frame N. The ownership model can later add more frame
slots without changing the per-image presentation semaphores.

## Acquire an image before resetting the fence

Surface conditions can change while a swapchain is in use. The most familiar
cause is resizing the window, although the exact response is platform
dependent. Moving the window to a display with a different scale factor, or a
change in the display's resolution, orientation, or colour space, can have the
same effect.

Vulkan reports a swapchain as **suboptimal** when it can still provide and
present images but no longer matches the surface as well as possible. It
reports the swapchain as **out of date** when the surface has changed enough
that the operation cannot continue with those images. Both conditions mean the
swapchain should eventually be replaced, but only the suboptimal path still
produces a usable frame.

The renderer next asks the swapchain for an available image, using the frame's
binary semaphore for the device-side signal:

```cpp
std::uint32_t imageIndex = 0;
bool swapchainIsSuboptimal = false;
try
{
    const auto [result, acquiredImageIndex] =
        swapchain_.handle().acquireNextImage(
            std::numeric_limits<std::uint64_t>::max(),
            *frame_.imageAvailable());
    imageIndex = acquiredImageIndex;
    swapchainIsSuboptimal =
        result == vk::Result::eSuboptimalKHR;
}
catch (const vk::OutOfDateKHRError&)
{
    return RenderResult::eNotPresented;
}
```

The infinite timeout may block this host call until an image can be returned.
Success provides its index and arranges for `imageAvailable` to be signaled;
the later graphics submission waits on that device-side signal before using
the image. A signal records that a prerequisite has completed, while a wait
prevents dependent work from passing until that signal exists.

A suboptimal result still provides a usable image, so the renderer remembers
the condition and continues. An out-of-date swapchain provides no image to
render and returns immediately.

The fence is still signaled at this point. That ordering is deliberate. If it
had been reset before acquisition and the out-of-date path returned, no queue
submission would exist to signal it again; the next frame could wait forever.

After successful acquisition, the renderer recycles the pool and records for
the selected image:

```cpp
frame_.resetCommands();
recordCommands(imageIndex);
```

If recording throws, the fence also remains signaled and no submission is
pending. Only after a complete command buffer exists does the renderer reset
the fence and commit to submission.

`Swapchain` adds singular `image()`, `imageView()`, and `renderFinished()`
accessors for this path. Each uses the same acquired index and bounds-checks its
vector access, keeping the presentable image, attachment view, and semaphore
paired without exposing indexing policy throughout the renderer. See the
updated [`swapchain.hpp`][source-swapchain-header] and
[`swapchain.cpp`][source-swapchain].

## Begin a one-use command recording

`recordCommands()` retrieves the primary buffer returned to its initial state
by the pool reset:

```cpp
const vk::raii::CommandBuffer& commandBuffer =
    frame_.commandBuffer();
const vk::CommandBufferBeginInfo beginInfo{
    .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit,
};
commandBuffer.begin(beginInfo);
```

`eOneTimeSubmit` promises that this recording will be submitted at most once
before being reset. The command buffer object itself persists, but its recorded
contents are rebuilt for each acquired swapchain image.

Resetting the pool first remains essential. The pool does not have
`eResetCommandBuffer`, so `begin()` cannot implicitly reset an executable
buffer from the previous frame.

## Transition the image into attachment layout

Acquiring an image identifies which swapchain image this frame may use, but it
does not put that image into the layout required for rendering. Vulkan images
have layouts associated with different kinds of access. An image barrier can
order those accesses and transition an image from one layout to another.

Each side of the barrier has a stage mask and an access mask. The stage
identifies where in the graphics pipeline the dependency applies; the access
mask identifies the kind of memory operation involved. The source pair
describes earlier work, while the destination pair describes the later work
that must wait and the access it will perform.

Before rendering can begin, two conditions must be satisfied. The
`imageAvailable` semaphore handles the presentation-to-graphics handoff. The
first `vk::ImageMemoryBarrier2` then transitions the acquired image into the
layout required for colour-attachment writes and describes the access that
follows:

```cpp
const vk::ImageMemoryBarrier2 toAttachment{
    .srcStageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
    .srcAccessMask = vk::AccessFlagBits2::eNone,
    .dstStageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
    .dstAccessMask =
        vk::AccessFlagBits2::eColorAttachmentWrite,
    .oldLayout = vk::ImageLayout::eUndefined,
    .newLayout = vk::ImageLayout::eAttachmentOptimal,
    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .image = swapchain_.image(imageIndex),
    .subresourceRange = kColorSubresourceRange,
};
```

This frame does not need the image's previous pixels, so `eUndefined` discards
them and leaves no earlier image access to preserve. The barrier transitions
the image to `eAttachmentOptimal` and identifies colour-attachment writes as
its first graphics access. After the barrier, dynamic rendering can use the
corresponding image view as a colour attachment.

The subresource range covers the image's sole colour mip level and array layer.

Both queue-family indices are ignored. If graphics and presentation use
different families, the swapchain was created with concurrent sharing; if they
use the same family, no ownership transfer exists. The barrier only changes
layout and synchronizes access.

`vk::DependencyInfo` carries the barrier into the Synchronization 2 command:

```cpp
const vk::DependencyInfo beginDependency{
    .imageMemoryBarrierCount = 1,
    .pImageMemoryBarriers = &toAttachment,
};
commandBuffer.pipelineBarrier2(beginDependency);
```

`pipelineBarrier2()` replaces the parallel stage-mask parameters of the older
barrier API with stage and access scopes stored directly in each barrier. That
makes the relationship between this image, its layouts, and its intended use
visible in one structure. The Vulkan Guide's
[synchronization examples][vulkan-synchronization-examples] use the same
barrier vocabulary for swapchain layout transitions.

The barrier is recorded outside dynamic rendering, as required for this layout
transition.

## Describe one dynamic-rendering colour attachment

An attachment is the image view that a rendering operation reads, writes,
resolves, clears, or preserves. Release 0.6 uses the view associated with the
acquired swapchain image.

Release 0.4 created a pipeline compatible with the swapchain format. Release
0.6 supplies the acquired image view as its actual attachment:

```cpp
const vk::ClearValue clearValue{
    .color = {.float32 =
        std::array{0.015F, 0.02F, 0.03F, 1.0F}},
};

const vk::RenderingAttachmentInfo colorAttachment{
    .imageView = *swapchain_.imageView(imageIndex),
    .imageLayout = vk::ImageLayout::eAttachmentOptimal,
    .loadOp = vk::AttachmentLoadOp::eClear,
    .storeOp = vk::AttachmentStoreOp::eStore,
    .clearValue = clearValue,
};
```

The load operation clears every pixel to a dark opaque colour instead of
loading old contents. The store operation preserves the triangle and
background for presentation after rendering ends.

Because fireEngine uses dynamic rendering, it does not create render-pass or
framebuffer objects for this path. `vk::RenderingInfo` instead supplies the
render area and attachment list directly while recording the command buffer:

```cpp
const vk::RenderingInfo renderingInfo{
    .renderArea =
        {
            .offset = {.x = 0, .y = 0},
            .extent = swapchain_.extent(),
        },
    .layerCount = 1,
    .colorAttachmentCount = 1,
    .pColorAttachments = &colorAttachment,
};
commandBuffer.beginRendering(renderingInfo);
```

The render area covers the full swapchain image and only one array layer. There
is no depth, stencil, resolve, or multisampled attachment in this first path.

## Set the viewport and scissor dynamically

The graphics pipeline declared viewport and scissor as dynamic state, so the
command buffer must provide both before drawing:

```cpp
const vk::Viewport viewport{
    .x = 0.0F,
    .y = 0.0F,
    .width = static_cast<float>(swapchain_.extent().width),
    .height = static_cast<float>(swapchain_.extent().height),
    .minDepth = 0.0F,
    .maxDepth = 1.0F,
};
const vk::Rect2D scissor{
    .offset = {.x = 0, .y = 0},
    .extent = swapchain_.extent(),
};
commandBuffer.setViewport(0, viewport);
commandBuffer.setScissor(0, scissor);
```

The viewport maps normalized device coordinates into framebuffer
coordinates—the pixel coordinate system of the current render target—and maps
depth into the full zero-to-one range. The scissor discards fragments outside
its integer rectangle. Both cover the complete current swapchain extent.

Keeping these values dynamic avoids creating a new graphics pipeline merely
because the presentation extent changes. Swapchain recreation still needs to
replace other format-dependent state, but width and height are no longer baked
into the pipeline.

## Bind vertex data and push the uniform descriptor

After beginning rendering, the command buffer binds the graphics pipeline and
the triangle buffer:

```cpp
commandBuffer.bindPipeline(
    vk::PipelineBindPoint::eGraphics,
    *pipeline_.pipeline());

constexpr vk::DeviceSize vertexOffset = 0;
const vk::Buffer vertexBuffer = vertexBuffer_.handle();
commandBuffer.bindVertexBuffers(0, vertexBuffer, vertexOffset);
```

Binding zero matches the vertex binding description created with the pipeline.
The offset is zero because the allocation contains only this vertex array.

The uniform takes a descriptor-shaped path. First, a buffer descriptor names
the frame's allocation and exact shader-visible range:

```cpp
const vk::DescriptorBufferInfo uniformInfo{
    .buffer = frame_.uniformBuffer().handle(),
    .offset = 0,
    .range = sizeof(FrameUniforms),
};
const vk::WriteDescriptorSet uniformWrite{
    .dstBinding = 0,
    .descriptorCount = 1,
    .descriptorType = vk::DescriptorType::eUniformBuffer,
    .pBufferInfo = &uniformInfo,
};
```

The write targets binding zero, matching the Slang declaration at set zero,
binding zero. There is no `dstSet` because this structure is consumed by a push
command rather than an update to allocated descriptor-set storage:

```cpp
commandBuffer.pushDescriptorSet(
    vk::PipelineBindPoint::eGraphics,
    *pipeline_.pipelineLayout(),
    0,
    uniformWrite);
```

The `0` selects descriptor set zero in the pipeline layout. Vulkan records the
descriptor contents into the command buffer, so the draw sees this frame's
uniform buffer without a descriptor pool or persistent descriptor set.

The release retains the push `DescriptorSetLayout` as a `Pipeline` member. The
Vulkan lifetime rules permit releasing the original layout after pipeline
layout creation, but retaining it keeps the construction relationship explicit
and avoids a validation-layer lifetime diagnostic when the push command is
recorded. Reverse member order releases the graphics pipeline, pipeline layout,
and descriptor-set layout in sequence.

See the updated [`pipeline.hpp`][source-pipeline-header] and
[`pipeline.cpp`][source-pipeline].

## Draw and prepare the image for presentation

The draw itself is the shortest command in the path:

```cpp
commandBuffer.draw(
    static_cast<std::uint32_t>(kTriangleVertices.size()),
    1,
    0,
    0);
```

It emits three vertices, one instance, starting at vertex and instance zero.
There is no index buffer. The pipeline assembles one triangle from the three
vertex-buffer entries.

Dynamic rendering ends before the image changes layout again:

```cpp
commandBuffer.endRendering();
```

The second image barrier makes the colour writes available and transitions the
image for the presentation engine:

```cpp
const vk::ImageMemoryBarrier2 toPresent{
    .srcStageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
    .srcAccessMask =
        vk::AccessFlagBits2::eColorAttachmentWrite,
    .dstStageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
    .dstAccessMask = vk::AccessFlagBits2::eNone,
    .oldLayout = vk::ImageLayout::eAttachmentOptimal,
    .newLayout = vk::ImageLayout::ePresentSrcKHR,
    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .image = swapchain_.image(imageIndex),
    .subresourceRange = kColorSubresourceRange,
};
const vk::DependencyInfo endDependency{
    .imageMemoryBarrierCount = 1,
    .pImageMemoryBarriers = &toPresent,
};
commandBuffer.pipelineBarrier2(endDependency);
commandBuffer.end();
```

The source scope names the colour-attachment writes that must finish. There is
no Vulkan destination access because presentation is not another shader or
attachment access described by this command buffer. The new layout is the
contract the presentation operation expects.

Ending the command buffer moves it from recording to executable state, ready
for one submission.

See the complete [`renderer.cpp`][source-renderer].

## Submit with Synchronization 2

Once recording has succeeded, the renderer resets the signaled frame fence:

```cpp
logicalDevice.resetFences(*frame_.frameFinished());
```

There is no intentional early-return path after this point. Submission will
associate the fence with real work, or an exception will leave through the
renderer's defensive cleanup path.

`vk::SubmitInfo2` names one semaphore wait, one command buffer, and one
semaphore signal:

```cpp
const vk::SemaphoreSubmitInfo waitInfo{
    .semaphore = *frame_.imageAvailable(),
    .stageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
};
const vk::CommandBufferSubmitInfo commandInfo{
    .commandBuffer = *frame_.commandBuffer(),
};
const vk::SemaphoreSubmitInfo signalInfo{
    .semaphore = *swapchain_.renderFinished(imageIndex),
    .stageMask =
        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
};
const vk::SubmitInfo2 submitInfo{
    .waitSemaphoreInfoCount = 1,
    .pWaitSemaphoreInfos = &waitInfo,
    .commandBufferInfoCount = 1,
    .pCommandBufferInfos = &commandInfo,
    .signalSemaphoreInfoCount = 1,
    .pSignalSemaphoreInfos = &signalInfo,
};
device_.graphicsQueue().submit2(
    submitInfo,
    *frame_.frameFinished());
```

`imageAvailable` is the acquisition-to-graphics handoff. The submission may be
queued immediately, but it cannot reach colour-attachment output—the first
stage that uses the acquired image—until that semaphore is signaled. The layout
transition and colour writes therefore wait, while unrelated earlier stages do
not have to stall.

The signal uses the same stage so the per-image `renderFinished` semaphore is
not signaled before the colour output and transition to presentation layout
complete. Presentation will wait on that semaphore before using the image.

The fence is separate from both semaphores. It tells the CPU when the submitted
graphics work has completed so the frame slot can be recycled. It does not tell
the CPU when the later presentation operation has released its semaphore or
swapchain resources.

The complete handoff is:

```text
acquisition -> imageAvailable -> graphics submission
graphics submission -> renderFinished -> presentation
graphics submission completion -> frameFinished fence -> CPU slot reuse
```

`submit2()` is the queue-submission half of Synchronization 2. Its semaphore
stage masks live beside the semaphore handles instead of in a parallel array,
matching the explicit style used by `ImageMemoryBarrier2` and
`pipelineBarrier2()`.

## Give graphics and presentation queues different jobs

Vulkan exposes queue capabilities separately. A graphics-capable queue can
execute the recorded draw, but that does not guarantee that its family can
present to this particular window surface. Conversely, a presentation-capable
queue is not necessarily where graphics commands should be submitted.

`Device` therefore selected both capabilities in release 0.2. They may resolve
to the same family and even the same queue handle, as they do in the captured
Apple M2 Pro run, but the renderer does not assume that they will:

- `graphicsQueue().submit2()` waits on the frame's image-available semaphore,
  executes the command buffer, signals the acquired image's render-finished
  semaphore, and associates completion with the frame fence;
- `presentQueue().presentKHR()` submits a presentation request that waits for
  that render-finished semaphore.

When the families differ, the swapchain uses concurrent sharing across both.
That is why the two image barriers can leave their queue-family indices ignored
instead of recording explicit ownership transfers. When one family supports
both jobs, the swapchain uses the more efficient exclusive mode.

The binary semaphore forms the cross-queue dependency. Host call order alone
would not prove that graphics finished before presentation begins.

## Present the acquired image and preserve its outcome

The presentation request selects the semaphore paired with the acquired image,
not the current frame slot:

```cpp
const vk::Semaphore renderFinished =
    *swapchain_.renderFinished(imageIndex);
const vk::SwapchainKHR swapchain = *swapchain_.handle();
const vk::PresentInfoKHR presentInfo{
    .waitSemaphoreCount = 1,
    .pWaitSemaphores = &renderFinished,
    .swapchainCount = 1,
    .pSwapchains = &swapchain,
    .pImageIndices = &imageIndex,
};
```

That continues the per-image semaphore strategy from release 0.5. Reusing a
presentation wait semaphore by frame index could re-signal it while the
presentation engine still holds an earlier wait. The Vulkan Guide's
[swapchain semaphore reuse guidance][vulkan-swapchain-semaphore-reuse]
documents this exact distinction.

The renderer combines acquisition and presentation status into three outcomes:

```cpp
enum class RenderResult : std::uint8_t
{
    ePresented,
    ePresentedSuboptimal,
    eNotPresented,
};
```

Three values exist because `main()` needs two independent answers from one
call: whether a frame reached the screen and whether the loop should continue.
`ePresented` answers yes to both. `eNotPresented` answers no to both: in release
0.6 it maps an out-of-date result from either acquisition or presentation, so
nothing is counted and the loop stops. `ePresentedSuboptimal` is the case where
the answers differ: the image was shown and counts towards the `--frames`
limit, but the swapchain should be replaced and the loop stops. A Boolean could
not represent that middle case, which is why the renderer returns an
enumeration.

Presentation can report the latter two conditions independently of acquisition:

```cpp
try
{
    const vk::Result presentResult =
        device_.presentQueue().presentKHR(presentInfo);
    if (presentResult == vk::Result::eSuboptimalKHR)
    {
        swapchainIsSuboptimal = true;
    }
}
catch (const vk::OutOfDateKHRError&)
{
    return RenderResult::eNotPresented;
}

return swapchainIsSuboptimal
    ? RenderResult::ePresentedSuboptimal
    : RenderResult::ePresented;
```

Release 0.6 reports both surface-change outcomes to `main()` instead of
recreating the swapchain. A suboptimal result still counts as a presented frame
before the loop stops; an out-of-date result does not. The application then
performs its shutdown wait and exits cleanly. A later checkpoint can replace
the old swapchain, per-image semaphores, and format-dependent pipeline without
obscuring the first complete render loop.

## Keep the renderer exception-safe after submission

Once `submit2()` succeeds, GPU work may outlive the C++ stack frame. The
renderer records that fact:

```cpp
workMayBePending_ = true;
```

Normal shutdown uses the throwing RAII path so errors remain reportable:

```cpp
void Renderer::waitIdle()
{
    device_.logicalDevice().waitIdle();
    workMayBePending_ = false;
}
```

If an exception leaves the event loop first, the `noexcept` destructor cannot
allow another exception to escape. It falls back to the raw Vulkan call and
logs a numeric failure:

```cpp
Renderer::~Renderer() noexcept
{
    if (!workMayBePending_)
    {
        return;
    }

    const VkResult result = vkDeviceWaitIdle(
        static_cast<VkDevice>(*device_.logicalDevice()));
    if (result != VK_SUCCESS)
    {
        fire_engine::log(
            "Vulkan cleanup wait failed with result code {}.",
            static_cast<std::int32_t>(result));
    }
}
```

The wait protects renderer-owned vertex, uniform, command, and synchronization
resources from destruction while submitted graphics work may still use them.

Presentation-resource lifetime remains more subtle. An unextended presentation
request supplies no fence, so a device wait is the conventional shutdown
fallback rather than a specification guarantee that the presentation engine
has released every reference. Safe recreation will need retired swapchains or
presentation fences from `VK_KHR_swapchain_maintenance1`, as the updated
`Swapchain` documentation records.

## Leave `main()` with the application loop

`Window` gains two narrow GLFW wrappers:

```cpp
bool Window::shouldClose() const noexcept
{
    return glfwWindowShouldClose(window_) == GLFW_TRUE;
}

void Window::pollEvents() const noexcept
{
    glfwPollEvents();
}
```

GLFW's event queue is process-wide, but keeping the call on `Window` prevents
the C API and native handle from leaking into application code.

`main()` creates `Renderer` last so it is destroyed first, then runs until the
window closes, the `--frames` limit used by the automated smoke test is reached,
or the swapchain needs replacement:

```cpp
std::uint64_t renderedFrameCount = 0;
bool swapchainNeedsRecreation = false;
while (!window.shouldClose() &&
       (!frameLimit.has_value() ||
        renderedFrameCount < *frameLimit))
{
    window.pollEvents();
    if (window.shouldClose())
    {
        break;
    }

    const fire_engine::RenderResult result = renderer.renderFrame();
    if (result != fire_engine::RenderResult::eNotPresented)
    {
        ++renderedFrameCount;
    }
    if (result != fire_engine::RenderResult::ePresented)
    {
        swapchainNeedsRecreation = true;
        break;
    }
}
```

Checking close state again after polling avoids rendering an extra frame after
processing a close event. The result handling counts both clean and suboptimal
presentations, then stops on any condition that requires recreation.

After `renderer.waitIdle()`, the application reports the deferred recreation
and verifies that a bounded run presented every requested frame. This makes an
early surface change a test failure instead of a false pass.

See the complete [`window.cpp`][source-window] and
[`main.cpp`][source-main].

## Keep build changes focused on the new C++ path

No package or shader work is added in release 0.6. `CMakeLists.txt` advances the
project to 0.6.0 and adds `buffer.cpp` and `renderer.cpp` to the existing
target. `vcpkg.json` advances its matching version without changing the
dependency list.

CTest now supplies a positive frame limit:

```cmake
add_test(
    NAME fireEngineTutorial
    COMMAND fireEngineTutorial --frames 1
)
```

The normal executable remains interactive, while the smoke test has a bounded
success condition: acquire, record, submit, and present exactly one frame.

One unrelated quality fix makes the header checks do what their comment always
intended. clang-tidy reports absolute file paths, so the old anchored
`^include/...` expression silently skipped first-party headers. The corrected
filter accepts the leading path:

```yaml
HeaderFilterRegex: '.*/(include/fire_engine|src)/.*'
```

That matters in a header-heavy release: the new owners and their public
contracts now participate in clang-tidy rather than being checked only through
their implementation files.

See the complete [`CMakeLists.txt`][source-cmake],
[`vcpkg.json`][source-vcpkg], and [`.clang-tidy`][source-clang-tidy].

## Configure, build, and render release 0.6

The compiler, build-tool, vcpkg, and Vulkan prerequisites remain the same as in
the [foundation post][foundation-post]. Clone the checkpoint directly with:

```shell
git clone --branch 0.6 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

Configure and build through the existing presets:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

Run interactively on macOS or Linux with:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

The release 0.6 bounded run was captured on an Apple M2 Pro running macOS 26,
using the KosmicKrisp driver from the LunarG Vulkan SDK:

```text
Selected Vulkan 1.4 device: Apple M2 Pro
Graphics queue family: 0
Present queue family: 0
Logical device and queues created.
VMA allocator created.
Swapchain created: 3 images at 1600x1200 (B8G8R8A8Srgb, Fifo), 3 presentation semaphores.
Pipeline layout and dynamic-rendering pipeline created.
Triangle buffers and one frame in flight created.
Presented 1 frame.
```

![The fireEngine Tutorial window displaying its first interpolated-colour triangle](/assets/img/fireengine/fireEngine-triangle.png)
_fireEngine's first triangle, rendered through the release 0.6 frame loop._

The frame limit used for that capture is useful for a quick local check:

```shell
./build/fireEngineTutorial --frames 1
```

Without `--frames`, the same renderer continues presenting until the window is
closed. The displayed image is a red, green, and blue triangle over the dark
clear colour.

CTest exercises the bounded path directly:

```shell
ctest --preset default
```

## Make CI prove a presented frame

The workflow file does not change, but its Linux test now proves the complete
rendering path. Lavapipe inside Xvfb must create the buffers, acquire a virtual
swapchain image, validate and execute the recorded commands, submit with the
two semaphore scopes, and present one image before the 30-second timeout.

macOS and Windows continue to compile the same renderer without a compatible
hosted-runner Vulkan environment. The platform-independent formatting,
clang-tidy, and Doxygen jobs automatically discover the new source and header
files. The corrected header filter makes that static-analysis claim real for
the first time.

See the complete [`ci.yml`][source-ci].

## Diagnose the new failure boundaries

Release 0.6 moves failures from startup construction into a stateful render
loop. Validation in a Debug build is especially valuable because most mistakes
are relationships between otherwise valid handles.

### Buffer creation or upload fails

`AllocatedBuffer` names whether VMA failed during creation or upload and
includes the Vulkan result. Creation failures point to the requested size,
usage, host-access constraints, insufficient suitable memory, or driver state.
An upload range error is caught before VMA and means the byte span or offset
does not fit the allocation.

### The first frame waits forever

The frame fence must begin signaled. On later frames, every reset fence must be
paired with a successful graphics submission that will signal it. Release 0.6
acquires and records before resetting the fence specifically so the known
early-return and recording-failure paths cannot strand it unsignaled.

### Image acquisition reports an out-of-date swapchain

The window surface changed before an image could be acquired. The renderer
returns `eNotPresented` without resetting the frame fence, `main()` performs its
shutdown wait, and the application reports that recreation belongs to a later
tutorial.

### Validation reports an image-layout or access error

Check both `ImageMemoryBarrier2` structures as a pair. The first must discard or
match the current layout and make the image writable as a colour attachment.
The second must occur after dynamic rendering, make colour writes available,
and leave the image in `ePresentSrcKHR`. The image, view, and per-image semaphore
must all use the same acquired index.

### Validation reports missing dynamic state

The pipeline declares viewport and scissor dynamic, so both commands must be
recorded after binding the pipeline and before drawing. Their extents should
match the render area and current swapchain image.

### Validation reports a descriptor mismatch

The push write must use set zero, binding zero, descriptor type uniform buffer,
and a range covering exactly `FrameUniforms`. The pipeline layout and shader
must retain the matching set, binding, type, stage visibility, and std140 memory
layout.

### Submission fails

The command buffer must be executable, the frame fence unsignaled, and the
binary image-available semaphore waiting on exactly one acquisition signal.
The wait stage must cover the first swapchain-image use, while the signal stage
must not release presentation before colour output and the final layout
transition complete.

### Presentation is suboptimal or out of date

This is a surface-lifecycle result rather than a triangle-draw failure.
Suboptimal presentation still increments the frame count before the loop stops;
an out-of-date attempt does not. Release 0.6 exits cleanly instead of trying to
replace swapchain images, per-image semaphores, and the format-dependent
pipeline in place.

### `--frames` is rejected

The option accepts one positive integer and no other arguments. Zero, negative
text, trailing characters, missing values, extra arguments, and integer
overflow all produce the usage error before Vulkan startup.

## What release 0.6 gives us

Release 0.5 established frame ownership. Release 0.6 turns it into the first
complete rendering and presentation path:

- one `AllocatedBuffer` owner pairs a Vulkan buffer with its VMA allocation;
- host-visible sequential-write memory supports a simple first upload path;
- bounds-checked writes handle mapping and non-coherent flushes through VMA;
- one immutable vertex buffer stores three coloured vertices;
- each frame slot owns a std140-compatible 4×4 transform uniform;
- identity transform data is uploaded before the first submission;
- `Renderer` owns triangle and frame resources while borrowing stable device,
  swapchain, and pipeline owners;
- each frame waits for safe reuse before acquiring a swapchain image;
- acquisition happens before fence reset, preserving the out-of-date path;
- the whole command pool is recycled before one-use recording begins;
- `ImageMemoryBarrier2` transitions the acquired image from discarded contents
  to attachment layout;
- one dynamic-rendering colour attachment clears and stores the full image;
- dynamic viewport and scissor state follow the current swapchain extent;
- the pipeline, vertex buffer, and per-frame uniform are bound before drawing;
- a push descriptor supplies set zero without allocating a descriptor set;
- one non-indexed draw emits the three triangle vertices;
- a second image barrier makes colour writes available and transitions the
  image for presentation;
- `SubmitInfo2` scopes acquisition and completion semaphores to colour output;
- graphics submission and presentation use queues selected for their distinct
  capabilities;
- the render-finished semaphore follows the acquired image index;
- clean, suboptimal, and out-of-date outcomes preserve correct frame counts;
- normal and exceptional shutdown paths wait before renderer-owned resources
  are destroyed;
- the GLFW event loop remains application policy rather than renderer detail;
- `--frames` gives automation a bounded success condition; and
- CTest now proves one complete acquired, rendered, submitted, and presented
  frame.

The first triangle is intentionally static. There is still only one frame in
flight, no staging buffer, no index buffer, no depth attachment, and no
swapchain recreation. Those omissions keep the completed frame small enough to
trace from host data to the presented pixels.

The next release can build on a known render loop rather than another startup
checkpoint: animate per-frame data, overlap multiple frames, add depth and
indexed geometry, or retire and replace presentation resources when the surface
changes.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan] — a detailed treatment of buffers,
  descriptors, command recording, image layouts, synchronization, queue
  submission, and presentation. Its examples predate current Vulkan, but the
  explicit resource and execution model remains valuable.
- [How to Vulkan][reading-how-to-vulkan] — a compact, code-first modern Vulkan
  guide whose buffer, dynamic-rendering, synchronization, and frame-loop
  sections provide a useful comparison with this tutorial's Vulkan-Hpp RAII
  design.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-5]: {{ page.previous_release_url }}
[release-0-6]: {{ page.release_url }}
[frame-post]: {% post_url 2026-08-04-preparing-fireengines-first-frame-in-flight %}
[foundation-post]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/CMakeLists.txt>
[source-vcpkg]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/vcpkg.json>
[source-clang-tidy]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/.clang-tidy>
[source-buffer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/include/fire_engine/render/buffer.hpp>
[source-buffer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/render/buffer.cpp>
[source-frame-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/include/fire_engine/render/frame_in_flight.hpp>
[source-frame]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/render/frame_in_flight.cpp>
[source-renderer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/include/fire_engine/render/renderer.hpp>
[source-renderer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/render/renderer.cpp>
[source-swapchain-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/include/fire_engine/render/swapchain.hpp>
[source-swapchain]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/render/swapchain.cpp>
[source-pipeline-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/include/fire_engine/render/pipeline.hpp>
[source-pipeline]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/render/pipeline.cpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/shaders/triangle.slang>
[source-window]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/platform/window.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/src/main.cpp>
[source-ci]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.6/.github/workflows/ci.yml>
[vulkan-synchronization2]: <https://docs.vulkan.org/guide/latest/extensions/VK_KHR_synchronization2.html>
[vulkan-synchronization-examples]: <https://docs.vulkan.org/guide/latest/synchronization_examples.html>
[vulkan-swapchain-semaphore-reuse]: <https://docs.vulkan.org/guide/latest/swapchain_semaphore_reuse.html>
[reading-page]: {% link _tabs/reading.md %}
[reading-vulkan]: <https://www.vulkanprogrammingguide.com>
[reading-how-to-vulkan]: <https://howtovulkan.com>
