---
title: "Compiling and sampling fireEngine's first texture"
date: 2026-08-28 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", vulkan, textures, rendering, synchronization, shaders, vma, assets]
description: >-
  Compile selected RGBA8 descriptions into device-local Vulkan images and
  samplers, upload them safely, and bind one base-colour texture per draw.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.8 can describe images and textures without Vulkan, then load those
descriptions from a deliberately narrow glTF slice. At that point the CPU owns
tightly packed RGBA8 pixels, filtering and wrapping choices, and material
references. None of those values is yet an image the fragment shader can
sample.

The renderer needs a second representation with a different job. It must
allocate device-preferred images, upload the selected pixels, establish their
first usable layout, create image views and samplers, and bind the resulting
pair while recording a draw. It must also preserve the existing preparation
rule: resources are compiled because the current scene reaches them, not merely
because they exist in an asset collection.

This part of release 0.8 crosses that boundary for one base-colour texture. The
normal application loads AnimatedCube, samples its imported image, and
multiplies the result by the material and vertex colour factors. An untextured
material follows the same pipeline through a persistent one-pixel white
fallback.

This detailed post is based on release 0.8. The
[architectural overview][planning-post] describes the complete release, while
the [scene-content post][scene-content-post] stops with the validated CPU data
consumed here.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> The [scene-content post][scene-content-post] covers the format-neutral input.
> This one follows selected image and texture descriptions across fireEngine's
> Vulkan boundary and into the fragment shader.
{: .prompt-info }

## Start from the selected preparation plan

`RenderAssets` is a catalogue. It can contain images, textures, materials,
meshes, and render objects that the current scene does not use. Compiling the
whole catalogue would make an unused addition allocate GPU memory and would
erase the reachability boundary established by `RenderPreparation`.

Instead, preparation computes the transitive resource subset required by the
scene's ordered render objects:

```text
SceneDrawList + RenderAssets
             |
             v
  RenderPreparationPlan
  +-- meshes
  +-- images
  +-- textures
  +-- materials
  +-- prepared render objects
             |
             v
     CompiledResources
  +-- Vulkan buffers
  +-- images + image views
  +-- samplers
  +-- per-draw lookup
```

The renderer compiles only when that plan's generation changes:

```cpp
const SceneDrawList drawList = scene.buildDrawItems();
const RenderPreparationPlan& plan = renderPreparation_.build(assets, drawList);
if (compiledGeneration_.has_value() &&
    *compiledGeneration_ == renderPreparation_.generation())
{
    return;
}

if (workMayBePending_)
{
    waitIdle();
}

compiledResources_.replace(device_, allocator_, frame_, assets, plan);
compiledGeneration_ = renderPreparation_.generation();
```

Adding an unreachable image still advances the asset revision, so it rebuilds
the plan and recompiles the selected GPU subset. What it does not do is put that
unused image in `plan.images` or allocate a device image for it. Changing only
a node transform preserves both the asset revision and ordered render-object
identities, so it returns the cached plan and avoids every GPU operation above.

`CompiledResources` uses vectors sized for dense engine-ID lookup, but it
creates an object only in slots named by the plan. A catalogue can therefore
retain stable IDs without forcing every entry onto the device.

AnimatedCube makes that distinction concrete. The loader retains its
base-colour and metallic-roughness images and textures, but fireEngine's 0.8
material model reaches only the base-colour texture. Preparation selects and
compiles that chain; the unused metallic-roughness image keeps its CPU ID and
description without receiving a Vulkan image.

See [`renderer.cpp`][source-renderer],
[`render_preparation.hpp`][source-render-preparation], and
[`compiled_resources.cpp`][source-compiled-resources].

## Give a device image one allocation owner

A decoded `ImageData` owns ordinary vector memory. Its device counterpart must
keep a `VkImage` and the memory bound to it alive as one resource. The internal
`AllocatedImage` type gives that pair one RAII owner:

```cpp
class AllocatedImage final
{
public:
    AllocatedImage(const MemoryAllocator& allocator, std::uint32_t width,
                   std::uint32_t height, vk::Format format,
                   vk::ImageUsageFlags usage);
    ~AllocatedImage();

    AllocatedImage(const AllocatedImage&) = delete;
    AllocatedImage& operator=(const AllocatedImage&) = delete;
    AllocatedImage(AllocatedImage&&) = delete;
    AllocatedImage& operator=(AllocatedImage&&) = delete;

    [[nodiscard]] vk::Image handle() const noexcept;

private:
    VmaAllocator_T* allocator_ = nullptr;
    VmaAllocation_T* allocation_ = nullptr;
    vk::Image image_{};
};
```

Construction fixes the resource shape needed by this release:

```cpp
const VkImageCreateInfo imageInfo{
    .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
    .imageType = VK_IMAGE_TYPE_2D,
    .format = static_cast<VkFormat>(format),
    .extent = {.width = width, .height = height, .depth = 1},
    .mipLevels = 1,
    .arrayLayers = 1,
    .samples = VK_SAMPLE_COUNT_1_BIT,
    .tiling = VK_IMAGE_TILING_OPTIMAL,
    .usage = static_cast<VkImageUsageFlags>(usage),
    .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
    .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
};

VmaAllocationCreateInfo allocationInfo{};
allocationInfo.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
```

VMA chooses and binds suitable memory through `vmaCreateImage()`. Destruction
passes the image and allocation back together through `vmaDestroyImage()`.
The allocator is borrowed and outlives the image; the image itself cannot be
copied or moved into a lifetime the owner graph did not plan for.

This type is format-agnostic enough to support sampled colour and later depth
resources. The texture compiler supplies the particular format and usage:

```cpp
image_{allocator, source.width, source.height,
       vk::Format::eR8G8B8A8Srgb,
       vk::ImageUsageFlagBits::eTransferDst |
           vk::ImageUsageFlagBits::eSampled}
```

`eTransferDst` admits the upload copy. `eSampled` admits reads through a shader
descriptor. Optimal tiling gives the implementation freedom to arrange the
device image for GPU access, which is why CPU pixels cannot simply be copied
into it as though it were another linear byte vector.

See [`image.hpp`][source-image-header] and
[`image.cpp`][source-image-cpp].

## Pair the image with its shader-visible view

The `CompiledImage` owner comes from
[`compiled_resources.cpp`][source-compiled-resources].

Vulkan descriptors do not bind a raw image allocation. They bind an image view
that selects the format and subresources through which the image will be used.
`CompiledImage` owns both layers:

```cpp
class CompiledImage final
{
public:
    CompiledImage(const Device& device, const MemoryAllocator& allocator,
                  const ImageData& source)
        : image_{allocator, source.width, source.height,
                 vk::Format::eR8G8B8A8Srgb,
                 vk::ImageUsageFlagBits::eTransferDst |
                     vk::ImageUsageFlagBits::eSampled},
          view_{device.logicalDevice(), vk::ImageViewCreateInfo{
              .image = image_.handle(),
              .viewType = vk::ImageViewType::e2D,
              .format = vk::Format::eR8G8B8A8Srgb,
              .subresourceRange = kColorSubresourceRange,
          }}
    {
    }

private:
    AllocatedImage image_;
    vk::raii::ImageView view_;
};
```

Declaration order matters here. The view borrows the image and is therefore
destroyed first; the image and its allocation are released afterwards.
`kColorSubresourceRange` covers colour aspect, mip level zero, and array layer
zero—the complete texture shape supported by this release.

The sRGB format is also part of the data contract. The stored bytes describe
sRGB colour. Sampling performs the format conversion into linear values before
the shader multiplies them by its other colour factors. Keeping that choice at
compilation avoids asking the loader to know how the renderer represents
colour on a device.

## Stage pixels before copying them to the image

The chosen image uses optimal tiling and device-preferred memory. Upload
therefore begins with a temporary host-visible buffer:

```cpp
const auto stageImage = [&](const ImageData& source,
                            const CompiledImage& destination)
{
    auto staging = std::make_unique<AllocatedBuffer>(
        allocator, source.pixels.size(),
        vk::BufferUsageFlagBits::eTransferSrc);
    staging->write(std::as_bytes(std::span{source.pixels}));
    uploads.push_back({
        .staging = std::move(staging),
        .source = &source,
        .destination = &destination,
    });
};
```

`AllocatedBuffer::write()` asks VMA to map, copy, and flush the allocation as
needed. The staging buffer then remains alive beside borrowed pointers to its
CPU source and device destination until the transfer has finished:

```text
ImageData pixels
      |
      | CPU copy
      v
host-visible staging buffer
      |
      | vkCmdCopyBufferToImage
      v
optimal-tiled device image
```

One pending upload record is built for every selected image. The upload helper
records all of them into one command buffer and submits them together. Waiting
for that submission before returning gives the staging buffers a simple and
provable lifetime: they can be destroyed when the local upload collection
leaves scope.

That synchronous choice favours a small setup path over streaming throughput.
It is appropriate while preparation happens occasionally and the renderer has
one frame in flight; it is not a general asynchronous asset-transfer system.

See [`buffer.hpp`][source-buffer-header],
[`buffer.cpp`][source-buffer-cpp], and
[`compiled_resources.cpp`][source-compiled-resources].

## Transition through the image's three real states

A newly allocated image starts with an undefined layout. The transfer command
needs it as a copy destination, and the fragment shader later needs it as a
read-only sampled image:

```text
eUndefined
    |
    | none -> copy / transfer write
    v
eTransferDstOptimal
    |
    | copyBufferToImage
    v
eTransferDstOptimal
    |
    | copy / transfer write -> fragment / sampled read
    v
eShaderReadOnlyOptimal
```

The first Synchronization 2 barrier discards any nonexistent previous content
and makes the transfer write legal:

```cpp
const vk::ImageMemoryBarrier2 toTransfer{
    .srcStageMask = vk::PipelineStageFlagBits2::eNone,
    .srcAccessMask = vk::AccessFlagBits2::eNone,
    .dstStageMask = vk::PipelineStageFlagBits2::eCopy,
    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
    .oldLayout = vk::ImageLayout::eUndefined,
    .newLayout = vk::ImageLayout::eTransferDstOptimal,
    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .image = upload.destination->image(),
    .subresourceRange = kColorSubresourceRange,
};
```

The copy describes one tightly packed colour subresource. Leaving buffer row
length and image height at zero tells Vulkan to derive tightly packed rows from
the image extent:

```cpp
const vk::BufferImageCopy copyRegion{
    .imageSubresource = {
        .aspectMask = vk::ImageAspectFlagBits::eColor,
        .mipLevel = 0,
        .baseArrayLayer = 0,
        .layerCount = 1,
    },
    .imageExtent = {
        .width = upload.source->width,
        .height = upload.source->height,
        .depth = 1,
    },
};

commandBuffer.copyBufferToImage(
    upload.staging->handle(), upload.destination->image(),
    vk::ImageLayout::eTransferDstOptimal, copyRegion);
```

The second barrier makes the written bytes visible to the operation that
actually consumes them:

```cpp
const vk::ImageMemoryBarrier2 toShaderRead{
    .srcStageMask = vk::PipelineStageFlagBits2::eCopy,
    .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
    .dstStageMask = vk::PipelineStageFlagBits2::eFragmentShader,
    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead,
    .oldLayout = vk::ImageLayout::eTransferDstOptimal,
    .newLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
    .image = upload.destination->image(),
    .subresourceRange = kColorSubresourceRange,
};
```

The stage and access masks name the specific producer and consumer rather than
using broad all-commands barriers. Queue-family indices are ignored because
the same graphics queue performs the upload and later draw; no ownership
transfer is required.

See the complete `uploadImages()` in
[`compiled_resources.cpp`][source-compiled-resources].

## Borrow the one frame slot for setup work

Release 0.8 owns one command buffer and one frame-finished fence. The upload
path reuses them instead of adding a second command pool and fence solely for
preparation:

```text
Renderer::prepare()
    |
    +-- plan unchanged? --------------------------> return
    |
    +-- earlier frame work may be pending? ------> waitIdle()
    |
    +-- CompiledResources::replace()
            |
            +-- reset and record frame command buffer
            +-- reset frame-finished fence
            +-- submit all image uploads
            +-- wait for frame-finished fence
```

The first preparation has no earlier frame work to wait for. A later
preparation that changes the compiled plan first waits for submitted drawing
and presentation work to finish using the old resources. The image upload then
resets the same command resources, submits its one-time transfer commands, and
waits for their fence before compilation continues.

There is no overlap to recover in a one-frame tutorial renderer: setup borrows
the frame slot only after earlier use has finished, and returns it only after
the upload has finished. Multiple frames in flight or background streaming
would change that trade-off. They would need a dedicated upload context and a
way to retire staging resources after an asynchronous completion point.

The important contract is smaller than that future system: command pools and
fences may be reused, but never while earlier work still owns their state.

## Compile filter and wrap meaning into one sampler

The `CompiledTexture` constructor comes from
[`compiled_resources.cpp`][source-compiled-resources].

The CPU `Texture` describes nearest or linear filtering and one of three wrap
modes without naming Vulkan. `CompiledTexture` converts those choices while
borrowing the already compiled image:

| fireEngine description | Vulkan sampler value |
| --- | --- |
| `TextureFilter::eNearest` | `vk::Filter::eNearest` |
| `TextureFilter::eLinear` | `vk::Filter::eLinear` |
| `TextureWrap::eRepeat` | `vk::SamplerAddressMode::eRepeat` |
| `TextureWrap::eMirroredRepeat` | `vk::SamplerAddressMode::eMirroredRepeat` |
| `TextureWrap::eClampToEdge` | `vk::SamplerAddressMode::eClampToEdge` |

The compiled sampler applies horizontal and vertical choices independently:

```cpp
CompiledTexture::CompiledTexture(const Device& device,
                                 const CompiledImage& image,
                                 const Texture& source)
    : image_{&image},
      sampler_{device.logicalDevice(), vk::SamplerCreateInfo{
          .magFilter = compileFilter(source.magFilter),
          .minFilter = compileFilter(source.minFilter),
          .mipmapMode = vk::SamplerMipmapMode::eNearest,
          .addressModeU = compileWrap(source.wrapU),
          .addressModeV = compileWrap(source.wrapV),
          .addressModeW = vk::SamplerAddressMode::eRepeat,
          .minLod = 0.0f,
          .maxLod = 0.0f,
      }}
{
}
```

Only mip level zero exists, so both LOD limits are zero. The mipmap-mode value
cannot select another level and anisotropy remains disabled. Mipmaps and richer
sampling can wait until something in the tutorial needs them. Both add
resources and synchronisation work, and neither earns that while a single
unmipped texture is all that gets sampled.

Two engine textures can refer to the same `ImageId` while compiling distinct
samplers. The image owns pixels; the texture owns the policy used to sample
them. That relationship survives the Vulkan boundary instead of being flattened
into duplicate images.

## Keep untextured materials on the sampled path

The fallback construction and render-object lookup come from
[`compiled_resources.cpp`][source-compiled-resources].

An optional base-colour texture is useful CPU vocabulary, but making it a
shader branch would split the draw contract:

```text
textured material ----> sampled shader path
untextured material --> different descriptor or shader path
```

Release 0.8 uses a neutral resource instead. The first compilation creates a
one-pixel opaque-white image and uploads it through the same transfer path:

```cpp
const ImageData fallbackSource{
    .width = 1,
    .height = 1,
    .pixels = {255, 255, 255, 255},
};
```

A default `Texture{}` supplies linear filtering and repeat wrapping. When a
material has no base-colour texture, its compiled render object points at that
fallback; otherwise it points at the selected compiled texture:

```cpp
objects[object.id.value] = {
    .mesh = meshes[object.mesh.value].get(),
    .texture = material.baseColorTexture.has_value()
                   ? textures[material.baseColorTexture->value].get()
                   : fallback,
    .baseColor = material.baseColor,
};
```

Sampling white is the multiplicative identity, so the material and vertex
factors pass through unchanged. Every draw can now promise one valid sampler
and image view. The pipeline layout, command recording, and shader contain no
special case for texture absence.

The fallback is persistent across resource replacements. It is allocated and
uploaded once, then reused even when the selected scene subset changes. A
renderer invariant—not every content producer—owns the neutral device
resource.

## Add one image-sampler binding to the pipeline

The existing frame uniform occupies binding zero. The base-colour texture adds
one fragment-stage combined image-sampler at binding one:

```cpp
constexpr vk::DescriptorSetLayoutBinding kBaseColorTextureBinding{
    .binding = 1,
    .descriptorType = vk::DescriptorType::eCombinedImageSampler,
    .descriptorCount = 1,
    .stageFlags = vk::ShaderStageFlagBits::eFragment,
};

constexpr std::array kDescriptorBindings = {
    kFrameUniformBinding,
    kBaseColorTextureBinding,
};
```

A combined descriptor matches the shader operation: one texture access needs
both an image view and the sampling policy. fireEngine uses a push-descriptor
layout:

```cpp
const vk::DescriptorSetLayoutCreateInfo createInfo{
    .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptor,
    .bindingCount = static_cast<std::uint32_t>(kDescriptorBindings.size()),
    .pBindings = kDescriptorBindings.data(),
};
```

Push descriptors let command recording provide the small descriptor contents
inline. This renderer does not need a descriptor pool, allocate one set per
material, or manage set retirement when preparation replaces resources.

Release 0.8 requires Vulkan 1.4 and explicitly checks and enables the core
`pushDescriptor` feature during device creation. The pipeline flag and command
therefore use their unsuffixed core names rather than depending on the older
extension spelling.

See [`pipeline.cpp`][source-pipeline] and
[`device.cpp`][source-device].

## Bind the selected texture while recording each draw

Compilation produces a dense lookup from `RenderObjectId` to the handles and
material value required by command recording:

```cpp
struct CompiledDraw
{
    vk::Buffer vertexBuffer;
    vk::Buffer indexBuffer;
    std::uint32_t indexCount;
    vk::Sampler sampler;
    vk::ImageView imageView;
    Color4 baseColor;
};
```

The scene draw list still supplies the current world transform and render
object identity. The renderer combines that transient state with the compiled
lookup, then pushes the texture pair for the draw:

```cpp
const detail::CompiledDraw draw =
    compiledResources_.draw(item.renderObject);

const vk::DescriptorImageInfo textureInfo{
    .sampler = draw.sampler,
    .imageView = draw.imageView,
    .imageLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
};
const vk::WriteDescriptorSet textureWrite{
    .dstBinding = 1,
    .descriptorCount = 1,
    .descriptorType = vk::DescriptorType::eCombinedImageSampler,
    .pImageInfo = &textureInfo,
};
commandBuffer.pushDescriptorSet(
    vk::PipelineBindPoint::eGraphics,
    *presentation_->pipeline().pipelineLayout(), 0, textureWrite);
```

The descriptor's declared layout agrees with the final upload transition.
Release 0.8 writes the geometry and texture bindings for every draw, keeping
the first sampled path direct even when adjacent draws happen to reuse the same
handles.

Material base colour remains a push constant beside the model matrix. The
texture is a descriptor because sampling needs resource handles; the factor is
plain per-draw data. Both meet again in the shader.

See [`compiled_resources.hpp`][source-compiled-resources-header] and the draw
loop in [`renderer.cpp`][source-renderer].

## Carry UVs into one fragment sample

The vertex layout gained a two-float texture-coordinate attribute at location
two. The Slang interface carries it unchanged from the vertex input to the
fragment stage:

```cpp
struct VertexInput
{
    [[vk::location(0)]] float3 position : POSITION;
    [[vk::location(1)]] float4 color : COLOR;
    [[vk::location(2)]] float2 textureCoordinate : TEXCOORD;
};

struct FragmentInput
{
    float4 position : SV_Position;
    [[vk::location(0)]] float4 color : COLOR;
    [[vk::location(1)]] float2 textureCoordinate : TEXCOORD;
};
```

Binding one is expressed as a combined `Sampler2D<float4>` matching the Vulkan
descriptor layout:

```cpp
[[vk::binding(1, 0)]]
Sampler2D<float4> baseColorTexture;
```

The vertex stage combines the vertex and material factors. The fragment stage
multiplies that value by the sampled texel:

```cpp
output.color = input.color * draw.baseColor;
output.textureCoordinate = input.textureCoordinate;

return baseColorTexture.Sample(input.textureCoordinate) * input.color;
```

The complete result is therefore:

```text
sampled base-colour texel * material base-colour factor * vertex colour
```

Imported vertices start with white colour, so AnimatedCube displays its
decoded texture modulated by the glTF material factor. Procedural content can
use vertex colour deliberately. An untextured material samples the white
fallback, leaving its other two factors visible.

See [`scene.slang`][source-shader] and the vertex input declarations in
[`pipeline.cpp`][source-pipeline].

## Verify selection, upload, and both material paths

The boundary divides naturally into device-free and device-backed checks.

Two focused preparation cases prove the CPU selection contract. One extracts
two textures sharing one image and fixes their stable plan order. The other
proves that image or texture catalogue additions advance the asset revision and
invalidate a cached plan:

```shell
ctest --preset default -R "^(Render preparation extracts shared image and texture dependencies|Image and texture additions invalidate render preparation)$"
```

Those cases do not claim to test Vulkan allocation or synchronization. Three
bounded application scenarios take over at that boundary:

```shell
ctest --preset default -R "^(fireEngineTutorialAnimatedCubeSmoke|fireEngineTutorialUntexturedSmoke|fireEngineTutorialPrepareTwiceSmoke)$"
```

The AnimatedCube scenario crosses the real loader, selected-image upload,
sampled descriptor, and shader path. The untextured scenario uses a material
whose optional texture is absent and proves the persistent fallback path. The
repeated-preparation scenario changes the required
render-object set after a frame, exercising the wait, resource replacement,
and reuse of the existing fallback.

### Prove resource discovery is independent of the working directory

The basic AnimatedCube scenario also checks how the two file-backed ends of
the path are found. CMake gives the engine and application absolute build-tree
directories through private compile definitions:

```cmake
set(FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/shaders")
target_compile_definitions(fireEngineTutorialEngine PRIVATE
    FIRE_ENGINE_SHADER_DIRECTORY="${FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY}"
)

set(FIRE_ENGINE_ASSET_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/assets")
target_compile_definitions(fireEngineTutorial PRIVATE
    FIRE_ENGINE_ASSET_DIRECTORY="${FIRE_ENGINE_ASSET_OUTPUT_DIRECTORY}"
)
```

`main.cpp` resolves AnimatedCube beneath `FIRE_ENGINE_ASSET_DIRECTORY`, while
pipeline creation loads the compiled Slang module beneath
`FIRE_ENGINE_SHADER_DIRECTORY`. Neither path is derived from the process's
current directory.

CTest turns that property into an integration check by running the basic
scenario from a separate `smoke-work` directory, away from the executable and
the build-tree `assets/` and `shaders/` directories:

```cmake
set(FIRE_ENGINE_SMOKE_WORKING_DIRECTORY
    "${CMAKE_CURRENT_BINARY_DIR}/smoke-work")
file(MAKE_DIRECTORY "${FIRE_ENGINE_SMOKE_WORKING_DIRECTORY}")
set_tests_properties(fireEngineTutorialAnimatedCubeSmoke PROPERTIES
    WORKING_DIRECTORY "${FIRE_ENGINE_SMOKE_WORKING_DIRECTORY}"
)
```

The scenario can therefore parse the document, decode its image, load the
SPIR-V module, upload the selected texture, and draw without accidentally
finding either resource beside the process or relative to the shell that
launched it.

These three scenarios need a usable Vulkan device and presentation
environment. CTest gives all Vulkan scenarios one resource lock so they do not
contend for the device, fails them when the application reports a validation
error, and keeps each run bounded by a timeout. A Debug build also supplies a
synchronization-validation version of repeated preparation.

See [`test_render_preparation.cpp`][source-test-preparation], the application
scenarios in [`main.cpp`][source-main], and their
[`CMakeLists.txt` registration][source-cmake].

## Diagnose the first sampled-image failures

### An image reaches the shader as black or corrupted data

Check the upload as a complete sequence: a transfer-source staging buffer,
`eUndefined` to `eTransferDstOptimal`, `copyBufferToImage()`, then
`eTransferDstOptimal` to `eShaderReadOnlyOptimal`. The final barrier must make
transfer writes visible to fragment-shader sampled reads. Also confirm that the
copy extent matches the validated `ImageData` dimensions.

### Validation reports that an image has the wrong layout

The layout named in `vk::DescriptorImageInfo` must match the layout established
by the upload barrier. Both are `eShaderReadOnlyOptimal` here. Do not treat a
layout transition as a field update: it is a recorded GPU command whose
ordering, stage masks, and access masks are part of the dependency.

### A texture appears blurred or pixelated

Trace the source `Texture` rather than changing Vulkan sampler values directly.
Magnification and minification compile independently from the engine's nearest
or linear choices. This release has only mip level zero, so mip-filter variants
from glTF have already collapsed into those two meaningful modes.

### Texture coordinates outside zero to one behave incorrectly

Check `wrapU` and `wrapV` separately. Repeat, mirrored repeat, and clamp to edge
compile to different sampler address modes, and a glTF sampler can choose a
different policy per axis.

### An untextured material draws with an unexpected tint

The fallback contributes opaque white, not the final surface colour. The
fragment result still includes the material base-colour factor and vertex
colour. Check those values before suspecting a second shader path; there is no
untextured shader variant in this release.

### Repeated preparation fails around command-buffer or fence reuse

Confirm that earlier frame work has finished before `CompiledResources`
resets the borrowed frame command buffer and fence. The upload submission then
waits for that fence before staging buffers leave scope. Reusing either object
while an earlier submission still owns it violates the setup protocol.

## What this part of release 0.8 gives us

This part of release 0.8 turns validated image descriptions into one complete
sampled-texture path:

- preparation continues to select the reachable resource subset before any
  Vulkan allocation;
- `AllocatedImage` owns a Vulkan image and its VMA allocation together;
- selected RGBA8 pixels compile into device-preferred, optimal-tiled sRGB
  images and colour views;
- host-visible staging buffers bridge ordinary CPU vectors to those images;
- Synchronization 2 barriers move each image from undefined, through transfer
  destination, to fragment-shader read-only use;
- one setup submission borrows the sole frame command buffer and fence only
  after earlier work has finished;
- engine filter and wrap values compile into Vulkan samplers without leaking
  Vulkan into the description model;
- one persistent opaque-white image keeps untextured materials on the same
  descriptor and shader path;
- a Vulkan 1.4 push descriptor supplies one combined image-sampler per draw;
- UVs cross the vertex interface into one Slang texture sample;
- sampled colour, material colour, and vertex colour multiply in one explicit
  shader contract;
- compiled absolute asset and shader paths let the integration scenario run
  independently of its process working directory; and
- device-free selection tests and bounded Vulkan scenarios verify the two
  sides of the boundary at their appropriate levels.

The renderer can now make AnimatedCube's imported base-colour texture visible
without teaching `ImageData`, `Texture`, `Material`, or `GltfLoader` about a
device. Camera, depth, culling, and animation can build on that path without
changing what a texture description means.

## Recommended reading

- [Vulkan Guide: Synchronization Examples][reading-vulkan-sync] — worked
  Synchronization 2 barriers for image uploads and shader reads.
- [Vulkan Guide: Image Copies][reading-vulkan-image-copies] — buffer-to-image
  copy regions, tightly packed data, image subresources, and copy extents.
- [Vulkan specification: Push Descriptors][reading-vulkan-push-descriptors] —
  the descriptor-set-layout flag and command model used for fireEngine's small
  inline bindings.
- [Vulkan Memory Allocator][reading-vma] — resource creation, memory-type
  selection, mapping, and paired allocation cleanup.
- [Slang `Sample` reference][reading-slang-sample] — the texture-sampling
  operation used by the fragment shader.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[scene-content-post]: {% post_url 2026-08-27-introducing-format-neutral-scene-content-to-fireengine %}
[source-renderer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/renderer.cpp>
[source-render-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/graphics/render_preparation.hpp>
[source-compiled-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/compiled_resources.cpp>
[source-compiled-resources-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/compiled_resources.hpp>
[source-image-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/image.hpp>
[source-image-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/image.cpp>
[source-buffer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/buffer.hpp>
[source-buffer-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/buffer.cpp>
[source-pipeline]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/pipeline.cpp>
[source-device]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/device.cpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/shaders/scene.slang>
[source-test-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/graphics/test_render_preparation.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[reading-vulkan-sync]: <https://docs.vulkan.org/guide/latest/synchronization_examples.html>
[reading-vulkan-image-copies]: <https://docs.vulkan.org/guide/latest/image_copies.html>
[reading-vulkan-push-descriptors]: <https://docs.vulkan.org/spec/latest/chapters/descriptorsets.html>
[reading-vma]: <https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator>
[reading-slang-sample]: <https://docs.shader-slang.org/en/stable/external/core-module-reference/types/0texture-01/sample-0.html>
[reading-page]: {% link _tabs/reading.md %}
