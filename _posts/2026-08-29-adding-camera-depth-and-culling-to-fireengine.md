---
title: "Adding a camera, depth, and culling to fireEngine"
date: 2026-08-29 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", vulkan, camera, depth, culling, rendering, matrices, gltf]
description: >-
  Turn fireEngine's textured scene into a coherent opaque 3D path with a
  Vulkan projection, an extent-matched depth attachment, and correct culling.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.8 can load AnimatedCube, compile its selected texture, and issue an
indexed draw. That is enough to put imported geometry through a fragment
shader, but not enough to define a convincing 3D view.

The renderer still needs to say where the viewer is, how view space becomes
Vulkan clip space, which side of a triangle faces the camera, and which of
several fragments at one pixel is visible. Those decisions cannot be made in
isolation. A projection changes winding as well as position; a depth comparison
only makes sense for the projection's depth range; a depth image must match the
rendering extent and the pipeline that writes it.

Release 0.8 therefore adds a fixed perspective camera, depth rendering, and
back-face culling as one visibility contract. A camera at `(0, 0, 4)` looks at
the origin. One extent-matched depth attachment keeps the nearest opaque
surface. Counter-clockwise front faces preserve glTF's convention through the
projection and Vulkan framebuffer transforms.

This detailed post is based on release 0.8. The
[architectural overview][planning-post] describes the complete release, while
the [transforms post][transforms-post] establishes the matrix conventions and
camera operations consumed here.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> The [transforms post][transforms-post] covers `lookAt()`, `perspective()`, and
> the CPU-to-Slang matrix contract. This post follows those values through the
> renderer's camera, depth attachment, pipeline, and frame commands.
{: .prompt-info }

## Treat visibility as one pipeline contract

A textured draw supplies colour, but visibility is decided across several
pipeline stages:

```text
local position
      |
      v
model transform      per draw
      |
      v
view transform       shared camera
      |
      v
projection           Vulkan clip and depth conventions
      |
      v
front-face test ----> discard back faces
      |
      v
rasterization ------> candidate fragments
      |
      v
depth test ---------> keep the nearest fragment
      |
      v
colour attachment
```

Each decision constrains the next one:

| Decision | Contract it establishes |
| --- | --- |
| View matrix | the camera position, direction, and right-handed view space |
| Projection matrix | field of view, aspect ratio, Vulkan depth range, and Y orientation |
| Front-face state | which projected winding is considered exterior |
| Depth format and attachment | where per-pixel depth can be stored |
| Depth comparison | which fragment wins when opaque surfaces overlap |

Changing only one value until AnimatedCube looks plausible would leave these
relationships accidental. Keeping them together makes the result explainable:
the shader produces Vulkan-compatible clip coordinates, culling interprets
their winding consistently, and the depth test compares values in the range
the projection generates.

## Build one fixed view-projection matrix

The tutorial camera is deliberately fixed. It sits four units along positive Z,
looks at the origin, and treats positive Y as up:

```cpp
[[nodiscard]] Mat4 createViewProjection(vk::Extent2D extent)
{
    const std::expected<Mat4, NormalizeError> view = Mat4::lookAt(
        Vec3{.x = 0.0f, .y = 0.0f, .z = 4.0f}, Vec3{},
        Vec3{.x = 0.0f, .y = 1.0f, .z = 0.0f});
    if (!view.has_value())
    {
        throw std::logic_error(
            "The fixed camera produced a degenerate view basis");
    }

    const float aspectRatio =
        static_cast<float>(extent.width) /
        static_cast<float>(extent.height);
    const Mat4 projection = Mat4::perspective(
        std::numbers::pi_v<float> / 3.0f, aspectRatio, 0.1f, 100.0f);
    return projection * *view;
}
```

The parameters form a small, explicit camera policy:

| Property | Value |
| --- | --- |
| Eye | `(0, 0, 4)` |
| Target | `(0, 0, 0)` |
| Up | `(0, 1, 0)` |
| Vertical field of view | 60 degrees |
| Aspect ratio | swapchain width divided by height |
| Near plane | `0.1` |
| Far plane | `100.0` |

`lookAt()` produces a right-handed view where geometry in front of this camera
has negative view-space Z. `perspective()` maps the near plane to normalized
depth zero and the far plane to one. Its negative Y scale keeps positive
view-space Y visually upward when a positive-height Vulkan viewport maps
normalized coordinates into framebuffer coordinates.

The multiplication order follows fireEngine's column-vector convention. The
view acts first, then the projection:

```text
world position -> view -> projection -> clip position

clip = projection * view * world
```

The aspect ratio comes from the swapchain extent in physical pixels, not the
logical window dimensions or a fixed `800 / 600` assumption. The completed
release recomputes the matrix when presentation state receives a new extent;
the recreation protocol itself remains a separate concern.

See the camera factory in [`renderer.cpp`][source-renderer] and the complete
matrix operations in [`mat4.hpp`][source-mat4].

## Keep the camera shared and the model transform local

Every draw in a frame sees the same camera. Each scene node still supplies its
own current world transform. The CPU-to-shader data split reflects those update
rates:

```cpp
struct alignas(16) FrameUniforms
{
    Mat4 viewProjection = Mat4::identity();
};

struct DrawConstants
{
    Mat4 model = Mat4::identity();
    Color4 baseColor{
        .r = 1.0f,
        .g = 1.0f,
        .b = 1.0f,
        .a = 1.0f,
    };
};
```

`FrameUniforms` occupies one frame-owned uniform buffer. `DrawConstants`
continues to use push constants for each render object. The Slang vertex stage
composes them without transposition or repacking:

```cpp
struct FrameUniforms
{
    float4x4 viewProjection;
};

[[vk::binding(0, 0)]]
ConstantBuffer<FrameUniforms, Std140DataLayout> frame;

[[vk::push_constant]]
ConstantBuffer<DrawConstants> draw;

output.position = mul(
    frame.viewProjection,
    mul(draw.model, float4(input.position, 1.0)));
```

The complete position path is therefore:

```text
vertex local position
        |
        | draw.model
        v
world position
        |
        | frame.viewProjection
        v
Vulkan clip position
```

Camera setup does not belong in the scene hierarchy for this release. The
fixed viewer is renderer policy, while scene transforms describe the imported
content. A later movable camera can change that policy without changing the
model-transform contract used by every draw.

See [`frame_in_flight.hpp`][source-frame-header],
[`draw_constants.hpp`][source-draw-constants], and
[`scene.slang`][source-shader].

## Let one presentation extent drive three resources

The swapchain extent now has three related consequences:

```text
                         swapchain extent
                         /              \
                        v                v
          projection aspect ratio    DepthBuffer extent
                                              |
swapchain colour format ----+                 | depth format
                             v                 v
                         graphics Pipeline
```

The projection needs the extent's ratio. The depth image needs its exact width
and height because every colour sample requires a corresponding depth sample.
The graphics pipeline needs the colour and depth formats it will see during
dynamic rendering.

In the completed release, `PresentationState` makes the common replacement
lifetime visible:

```cpp
detail::Swapchain swapchain_;
detail::DepthBuffer depthBuffer_;
detail::Pipeline pipeline_;
```

Construction follows the dependency direction:

```cpp
swapchain_{device, window, oldSwapchain},
depthBuffer_{device, allocator, swapchain_.extent()},
pipeline_{device, swapchain_.imageFormat(), depthBuffer_.format()}
```

The depth buffer is not compiled from `RenderAssets`. It depends on the current
presentation extent and contributes a format to the compatible pipeline, so it
belongs beside the swapchain rather than beside meshes and textures.

Only one depth image is needed because release 0.8 has one frame in flight.
The frame fence finishes all drawing that used it before the next command
buffer is recorded. A renderer with overlapping frames would need one depth
attachment per concurrent frame slot, or another scheme that prevents two
submissions from writing the same image at once.

See the presentation ownership in [`renderer.cpp`][source-renderer].

## Select a supported depth-only format

The renderer does not assume that its preferred depth format is available for
optimal-tiled attachment use. `DepthBuffer` checks two depth-only candidates in
order:

```cpp
[[nodiscard]] vk::Format
chooseDepthFormat(const vk::raii::PhysicalDevice& physicalDevice)
{
    constexpr std::array candidates = {
        vk::Format::eD32Sfloat,
        vk::Format::eD16Unorm,
    };
    for (const vk::Format candidate : candidates)
    {
        const vk::FormatProperties properties =
            physicalDevice.getFormatProperties(candidate);
        if ((properties.optimalTilingFeatures &
             vk::FormatFeatureFlagBits::eDepthStencilAttachment) !=
            vk::FormatFeatureFlags{})
        {
            return candidate;
        }
    }
    throw std::runtime_error(
        "The selected device supports no depth-only attachment format");
}
```

`D32Sfloat` is preferred for its precision. `D16Unorm` supplies the smaller
fallback. Stencil is not part of the 0.8 rendering contract, so neither
candidate spends storage or API surface on a stencil component.

The test is about the intended image use, not recognition of an enum value.
The selected format must advertise
`eDepthStencilAttachment` in its optimal-tiling features because the image is
created with optimal tiling and written as a depth attachment.

The public `RendererInfo` exposes the selected format as text. That keeps the
facade free of Vulkan types while making a device-specific choice visible in
ordinary application diagnostics.

## Own the depth image and view together

`DepthBuffer` gives the selected format, extent-matched image, and depth-only
view one focused owner:

```cpp
class DepthBuffer final
{
public:
    DepthBuffer(const Device& device, const MemoryAllocator& allocator,
                vk::Extent2D extent);

    [[nodiscard]] vk::Format format() const noexcept;
    [[nodiscard]] vk::Image image() const noexcept;
    [[nodiscard]] const vk::raii::ImageView& view() const noexcept;

private:
    vk::Format format_;
    AllocatedImage image_;
    vk::raii::ImageView view_;
};
```

Construction reuses the VMA-backed image owner introduced for texture
compilation, but supplies depth-specific format, usage, and subresource state:

```cpp
DepthBuffer::DepthBuffer(const Device& device,
                         const MemoryAllocator& allocator,
                         vk::Extent2D extent)
    : format_{chooseDepthFormat(device.physicalDevice())},
      image_{allocator, extent.width, extent.height, format_,
             vk::ImageUsageFlagBits::eDepthStencilAttachment},
      view_{device.logicalDevice(), vk::ImageViewCreateInfo{
          .image = image_.handle(),
          .viewType = vk::ImageViewType::e2D,
          .format = format_,
          .subresourceRange = kDepthSubresourceRange,
      }}
{
}
```

The shared subresource range selects the sole mip, sole array layer, and depth
aspect:

```cpp
inline constexpr vk::ImageSubresourceRange kDepthSubresourceRange{
    .aspectMask = vk::ImageAspectFlagBits::eDepth,
    .baseMipLevel = 0,
    .levelCount = 1,
    .baseArrayLayer = 0,
    .layerCount = 1,
};
```

Declaration order releases the view before the image and its allocation. The
same direct-owner shape can be created again for a different extent without
teaching the generic `AllocatedImage` what a depth buffer means.

See [`depth_buffer.hpp`][source-depth-header],
[`depth_buffer.cpp`][source-depth-cpp], and
[`image_subresource_ranges.hpp`][source-subresources].

## Discard last frame's depth before this frame's clear

The depth image is cleared at the start of every geometry pass. Its previous
contents have no value, so the next frame can transition from
`eUndefined` and explicitly discard them:

```cpp
const vk::ImageMemoryBarrier2 toAttachment{
    .srcStageMask = vk::PipelineStageFlagBits2::eNone,
    .srcAccessMask = vk::AccessFlagBits2::eNone,
    .dstStageMask = vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                    vk::PipelineStageFlagBits2::eLateFragmentTests,
    .dstAccessMask = vk::AccessFlagBits2::eDepthStencilAttachmentRead |
                     vk::AccessFlagBits2::eDepthStencilAttachmentWrite,
    .oldLayout = vk::ImageLayout::eUndefined,
    .newLayout = vk::ImageLayout::eDepthAttachmentOptimal,
    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .image = presentation_->depthBuffer().image(),
    .subresourceRange = detail::kDepthSubresourceRange,
};
```

Using `eUndefined` after the first frame does not claim the image literally
retained that layout. It says the earlier contents may be discarded. The sole
frame fence has already proved that the previous submission is no longer using
the image, so no GPU execution overlaps this new transition.

The destination names both early and late fragment tests because Vulkan may
perform depth work in either stage. Its access mask admits both reading the
current stored depth for comparison and writing a nearer passing value.

Unlike the sampled texture, this image does not need a final shader-read
transition. It remains an attachment for the duration of the geometry pass,
then its contents are deliberately forgotten before the next clear.

See `transitionDepthToAttachment()` in
[`renderer.cpp`][source-renderer].

## Clear far and keep nearer fragments

Dynamic rendering receives the depth view alongside the acquired colour view:

```cpp
const vk::ClearValue depthClear{
    .depthStencil = {.depth = 1.0f, .stencil = 0},
};
const vk::RenderingAttachmentInfo depthAttachment{
    .imageView = *presentation_->depthBuffer().view(),
    .imageLayout = vk::ImageLayout::eDepthAttachmentOptimal,
    .loadOp = vk::AttachmentLoadOp::eClear,
    .storeOp = vk::AttachmentStoreOp::eDontCare,
    .clearValue = depthClear,
};

const vk::RenderingInfo renderingInfo{
    .renderArea = {
        .offset = {.x = 0, .y = 0},
        .extent = presentation_->swapchain().extent(),
    },
    .layerCount = 1,
    .colorAttachmentCount = 1,
    .pColorAttachments = &colorAttachment,
    .pDepthAttachment = &depthAttachment,
};
```

The projection maps the near plane to zero and far plane to one. Clearing to
`1.0` therefore starts every pixel at the farthest representable depth. A
fragment with a smaller value can pass and replace it.

`eClear` agrees with the barrier's decision to discard old data. `eDontCare`
on store says no later operation needs the completed depth image's contents.
The depth attachment exists to decide colour visibility during this pass, not
to become a sampled texture or a saved output.

The render area and depth extent both originate in the swapchain extent. A
mismatch would leave some colour samples without corresponding depth storage
or ask dynamic rendering to address outside the attachment.

## Make the pipeline name the same depth contract

Supplying a depth view while recording is only half of dynamic rendering's
contract. Pipeline creation must name a compatible depth format and enable the
fixed-function depth test:

```cpp
const vk::PipelineDepthStencilStateCreateInfo depthStencil{
    .depthTestEnable = vk::True,
    .depthWriteEnable = vk::True,
    .depthCompareOp = vk::CompareOp::eLess,
};
```

With the buffer cleared to one, `eLess` keeps a fragment only when its projected
depth is nearer than the value already stored at that sample. Enabling writes
then makes that passing depth the reference for later overlapping fragments.
Equal-depth fragments do not pass; this opaque path does not need coplanar
overdraw to depend on submission order.

The same selected depth format is chained into graphics-pipeline creation:

```cpp
const vk::StructureChain pipelineCreateChain{
    vk::GraphicsPipelineCreateInfo{
        // ...
        .pDepthStencilState = &depthStencil,
        // ...
        .layout = *pipelineLayout,
    },
    vk::PipelineRenderingCreateInfo{
        .colorAttachmentCount = 1,
        .pColorAttachmentFormats = &colorFormat,
        .depthAttachmentFormat = depthFormat,
    },
};
```

Dynamic rendering removes the render-pass object, not attachment
compatibility. The pipeline still needs to know the colour and depth formats
its fragment operations will target. `Pipeline` therefore accepts both values
at construction and lives in the same presentation group as the attachments.

See [`pipeline.hpp`][source-pipeline-header] and
[`pipeline.cpp`][source-pipeline-cpp].

## Cull back faces without guessing the winding

Depth decides which frontmost surface wins. Back-face culling prevents the
opposite side of an opaque closed surface from producing fragments in the
first place:

```cpp
const vk::PipelineRasterizationStateCreateInfo rasterization{
    .polygonMode = vk::PolygonMode::eFill,
    .cullMode = vk::CullModeFlagBits::eBack,
    .frontFace = vk::FrontFace::eCounterClockwise,
    .lineWidth = 1.0f,
};
```

The counter-clockwise value is a consequence of the complete coordinate path,
not a copy of glTF terminology into a Vulkan field:

```text
glTF primitive
counter-clockwise exterior
        |
        | model and right-handed view
        v
projection flips Y for Vulkan
        |
        | positive-height viewport uses framebuffer coordinates
        v
Vulkan front-face test
counter-clockwise is exterior
```

Vulkan determines facing after projection in framebuffer coordinates. The
projection-side Y inversion and Vulkan's downward framebuffer Y direction must
therefore be considered together. With both in place, AnimatedCube's glTF
counter-clockwise front faces remain `eCounterClockwise` rather than requiring
an apparently corrective clockwise setting.

A rotating solid cube makes a winding error conspicuous: the wrong faces
survive, or the exterior disappears as it turns. That visual pressure is useful
because a single front-facing triangle cannot expose the same mistake.

This is still a deliberately narrow opaque policy. A negative-determinant
model transform mirrors triangle winding, and glTF can mark a material as
double-sided. Release 0.8 neither changes front-face state for mirrored nodes
nor disables culling for double-sided materials. AnimatedCube uses the
positive-determinant, single-sided path this pipeline supports.

## Keep the frame order visible

The command buffer now records colour and depth setup before it begins dynamic
rendering:

```cpp
transitionToAttachment(commandBuffer, imageIndex);
transitionDepthToAttachment(commandBuffer);
beginGeometryPass(commandBuffer, imageIndex);
recordDraws(commandBuffer, drawItems);
commandBuffer.endRendering();
transitionToPresent(commandBuffer, imageIndex);
```

Read as a protocol, the frame is:

```text
wait for the sole frame fence
        |
        v
acquire colour image
        |
        v
transition colour + discard/transition depth
        |
        v
begin rendering with colour + cleared depth
        |
        v
draw with fixed culling and less-than depth testing
        |
        v
end rendering + transition colour to presentation
```

There is no depth transition after rendering because nothing consumes its
contents. There is no depth semaphore because depth never leaves the graphics
queue or enters presentation. Its reuse is protected by the same frame fence
that protects the command buffer and frame uniform.

That separation is useful: colour follows the acquire-render-present protocol,
while depth follows a shorter discard-render-discard lifetime inside the same
submitted frame.

## Verify the mathematical and device boundaries

The camera contract has a focused device-free case. It proves that perspective
maps the near and far planes to Vulkan's zero-to-one depth range, accounts for
aspect ratio, flips projected Y, places the viewed origin on negative Z, and
rejects invalid projection or degenerate view input:

```cpp
const Vec4 nearPoint = projection *
    Vec4{.x = 0.0f, .y = 0.0f, .z = -1.0f, .w = 1.0f};
const Vec4 farPoint = projection *
    Vec4{.x = 0.0f, .y = 0.0f, .z = -11.0f, .w = 1.0f};

REQUIRE(nearPoint.z / nearPoint.w == Approx(0.0f).margin(0.00001f));
REQUIRE(farPoint.z / farPoint.w == Approx(1.0f).margin(0.00001f));
```

The bounded AnimatedCube scenario crosses the device boundary. Creating the
renderer selects and allocates the depth attachment, creates a pipeline with
matching colour and depth formats, records the depth transition and clear, and
submits three real frames without accepting a Vulkan validation error.

Run both focused checks after configuring and building release 0.8:

```shell
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default -R "^(Mat4 camera transforms use Vulkan depth and right-handed view space|fireEngineTutorialAnimatedCubeSmoke)$"
```

The smoke scenario proves that the complete Vulkan path executes; it does not
compare a screenshot. Run the normal application to inspect the visible result
and catch an obviously inverted winding or missing depth test:

```shell
./build/fireEngineTutorial
```

These responsibilities sit at different test levels deliberately. Projection
arithmetic and degenerate inputs are deterministic CPU contracts. Format
selection, attachment creation, dynamic-rendering compatibility, culling, and
depth operations belong to a real device-backed scenario.

See [`test_mat4.cpp`][source-test-mat4], the application path in
[`main.cpp`][source-main], and its [`CMakeLists.txt` registration][source-cmake].

## Diagnose camera, depth, and culling failures

### The cube is stretched after the window changes shape

The projection aspect ratio must use the current swapchain extent, and the
frame uniform must be rewritten after that extent changes. Logical window size
is not necessarily the physical framebuffer size. Check the camera value and
depth extent against the same replacement presentation state.

### Every face disappears when culling is enabled

Check the whole coordinate path before reversing `frontFace`. Confirm the
shader multiplication order, projection-side Y inversion, positive viewport
height, source winding, and model-transform determinant. A negative scale can
mirror otherwise valid source geometry.

### Hidden faces draw over nearer ones

Confirm all four parts of the depth contract: a depth attachment is supplied to
dynamic rendering, its format is named during pipeline creation, depth testing
and writes are enabled, and the compare operation is `eLess` after clearing to
`1.0`.

### Validation reports an incompatible depth attachment

The `DepthBuffer` format passed to `Pipeline` must be the same format used by
the view supplied to `pDepthAttachment`. Rebuilding one without the other
breaks dynamic-rendering compatibility even though no render-pass object
exists.

### Validation reports the wrong depth layout or access

Transition the depth aspect—not the colour aspect—to
`eDepthAttachmentOptimal` before `beginRendering()`. The destination stages
must cover early and late fragment tests, and the access mask must admit depth
attachment reads and writes.

### The depth buffer cannot be created on a selected device

Query optimal-tiling attachment support for the candidate format rather than
assuming a format enum is sufficient. The error means neither of the two
depth-only candidates passed the required feature check; log the renderer's
device selection and queried format properties before expanding the format
set.

### Coplanar surfaces flicker or alternate

Depth testing cannot decide a stable visible order for geometrically coplanar
surfaces with nearly equal projected values. This release does not add polygon
offset or a specialised equal-depth policy. Remove the overlap or separate the
surfaces before treating `eLess` as the cause.

## What this part of release 0.8 gives us

This part of release 0.8 establishes one coherent opaque 3D visibility path:

- a fixed right-handed camera looks from positive Z towards the origin;
- a 60-degree Vulkan projection derives its aspect ratio from the current
  presentation extent;
- near and far planes map to normalized depth zero and one;
- the projection flips Y so positive view-space Y remains visually upward;
- one frame uniform carries the shared view-projection matrix while push
  constants retain each draw's model transform;
- the swapchain extent drives both projection and depth-image dimensions;
- `DepthBuffer` owns one selected depth format, VMA-backed image, and
  depth-only view;
- format selection verifies optimal-tiled depth-attachment support;
- the sole frame fence makes one reusable depth image sufficient;
- each frame discards old depth, transitions the image, and clears it to one;
- dynamic rendering binds colour and depth attachments with matching extents;
- pipeline compatibility includes both attachment formats;
- less-than testing and writes retain the nearest opaque fragment;
- back-face culling uses the counter-clockwise winding produced by the complete
  glTF-to-framebuffer coordinate path;
- the narrow policy names mirrored and double-sided content as unsupported
  cases rather than silently generalising from AnimatedCube; and
- device-free camera tests and a bounded Vulkan scenario exercise the two sides
  of the contract at their appropriate boundaries.

The renderer can now show AnimatedCube as a solid object rather than a textured
collection of triangles whose visibility depends on draw order. Animation and
presentation replacement can change transforms and extent around this contract
without redefining what near, front-facing, or visible means.

## Recommended reading

- [Foundations of Game Engine Development, Volume 1: Mathematics][reading-foundations] —
  the view, projection, coordinate-system, and matrix foundations behind the
  fixed camera.
- [glTF 2.0 specification: Meshes][reading-gltf-meshes] — primitive topology,
  counter-clockwise winding, and the effect of mirrored node transforms.
- [Vulkan Guide: Depth][reading-vulkan-depth] — Vulkan depth formats, image
  aspects, layouts, testing, and writes.
- [Vulkan specification: Fixed-Function Vertex Post-Processing][reading-vulkan-post] —
  clip coordinates, perspective division, viewport transformation, and the
  route into rasterization.
- [`VkFrontFace` reference][reading-vulkan-front-face] — the precise area and
  winding definitions selected by the pipeline's front-face state.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[transforms-post]: {% post_url 2026-08-22-giving-fireengine-imported-transforms-enough-vocabulary %}
[source-renderer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/renderer.cpp>
[source-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/mat4.hpp>
[source-frame-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/frame_in_flight.hpp>
[source-draw-constants]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/draw_constants.hpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/shaders/scene.slang>
[source-depth-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/depth_buffer.hpp>
[source-depth-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/depth_buffer.cpp>
[source-subresources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/image_subresource_ranges.hpp>
[source-pipeline-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/pipeline.hpp>
[source-pipeline-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/pipeline.cpp>
[source-test-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/math/test_mat4.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[reading-foundations]: <https://foundationsofgameenginedev.com/#fged1>
[reading-gltf-meshes]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#meshes>
[reading-vulkan-depth]: <https://docs.vulkan.org/guide/latest/depth.html>
[reading-vulkan-post]: <https://docs.vulkan.org/spec/latest/chapters/vertexpostproc.html>
[reading-vulkan-front-face]: <https://docs.vulkan.org/refpages/latest/refpages/source/VkFrontFace.html>
[reading-page]: {% link _tabs/reading.md %}
