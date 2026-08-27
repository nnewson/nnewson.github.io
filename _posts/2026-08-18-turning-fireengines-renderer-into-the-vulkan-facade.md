---
title: "Turning fireEngine's renderer into the Vulkan facade"
date: 2026-08-18 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, rendering, vulkan, architecture, command-buffers, shaders, pimpl, cpp]
description: >-
  Hide fireEngine's Vulkan ownership behind Renderer, compile prepared scene
  assets into indexed GPU resources, and draw current instances explicitly.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

Release 0.6 ended with a working renderer, but the application still assembled
most of its Vulkan ownership tree. `main()` created the device, allocator,
swapchain, and pipeline in dependency order, then passed them into a `Renderer`
that borrowed those owners and uploaded its own hard-coded triangle.

The earlier release 0.7 posts have moved every application-facing description
needed to replace that path. `RenderAssets` owns reusable meshes, materials, and
render objects. `Scene` owns transformable instances. Traversal emits current
draw items, and `RenderPreparation` compiles their stable dependencies into a
validated plan.

The final step is to make `Renderer` the Vulkan facade. Release 0.7 moves the
complete Vulkan ownership tree behind its public interface, consumes the
preparation plan during an explicit `prepare()`, and records current scene
instances during `drawFrame()`. The application still controls its content and
event loop, while the renderer no longer hard-codes the triangle's description
or asks `main()` to coordinate Vulkan objects.

This is the sixth and final post based on release 0.7. The
[first][testing-post] established the device-free test boundary, the
[second][maths-post] introduced the transform vocabulary, the
[third][assets-post] described reusable render content, the
[fourth][scene-post] built the scene graph, and the [fifth][preparation-post]
compiled its stable resource requirements. This post brings those boundaries
together without repeating their implementations.

The walkthrough follows the renderer changes from [release 0.6][release-0-6]
to [release 0.7][release-0-7]. Every source link remains pinned to 0.7 so the
examples continue to match the release.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Preparing fireEngine's scene data explicitly][preparation-post]
> for the plan consumed here. This post completes the 0.7 series by following
> that plan through GPU compilation, current command recording, and the public
> application boundary.
{: .prompt-info }

## Bring the release boundaries together

Release 0.7 now has a complete direction of travel from application values to
Vulkan work:

```text
Application
├── RenderAssets
│   ├── Mesh
│   ├── Material
│   └── RenderObject
└── Scene
    └── SceneNode hierarchy
          |
          v
    SceneDrawList --------+
                          v
RenderPreparation -> RenderPreparationPlan
                          |
                          v
Renderer::prepare() -> compiled meshes and object lookups
                          |
current SceneDrawList ----+
                          v
Renderer::drawFrame() -> command buffer -> submit -> present
```

The renderer sits at the API-specific end of the dependency chain. Plain C++
descriptions point towards it; Vulkan handles do not point back into the asset
or scene layers.

The final refactor centres on a small set of files:

```text
include/fire_engine/render/
├── draw_constants.hpp
├── frame_in_flight.hpp
├── pipeline.hpp
└── renderer.hpp

src/render/
├── frame_in_flight.cpp
├── pipeline.cpp
└── renderer.cpp

shaders/
└── triangle.slang

src/
└── main.cpp
```

The preparation post covered the CPU compiler used by `Renderer`. This part
concentrates on the ownership, GPU-resource, command-recording, and shader
contracts that consume its result.

## Move Vulkan ownership out of the application

Release 0.6 made lifetime order explicit in `main()`:

```cpp
fire_engine::Glfw glfw;
const fire_engine::Window window{800, 600, applicationName};
const fire_engine::Device device{glfw, window, applicationName};
const fire_engine::MemoryAllocator allocator{device};
const fire_engine::Swapchain swapchain{device, window};
const fire_engine::Pipeline pipeline{device, swapchain.imageFormat()};
fire_engine::Renderer renderer{device, allocator, swapchain, pipeline};
```

That was useful while each owner was introduced. It exposed construction and
reverse destruction directly, but it also made the application responsible for
Vulkan relationships that every use of this renderer must get right.

Release 0.7 reduces the application-facing construction path to platform
owners, the renderer, and Vulkan-free content:

```cpp
fire_engine::Glfw glfw;
const fire_engine::Window window{800, 600, applicationName};
fire_engine::Renderer renderer{glfw, window, applicationName};
TutorialContent content = makeTriangleScene();
renderer.prepare(content.assets, content.scene);
```

`Glfw` and `Window` remain outside because the application owns its platform
event loop. `Renderer` takes the information required to create a surface and
presentation path, then owns every Vulkan and VMA object behind that boundary.

This is a facade rather than a global engine object. It presents one coherent
rendering operation over several internal subsystems without absorbing scene
ownership, asset creation, window events, or application policy.

See the complete [`main.cpp`][source-main].

## Keep the public renderer surface Vulkan-free

The release 0.6 header included buffer and frame headers, accepted four
render-layer owners, and exposed a renderer whose documentation described a
single triangle. The new public declaration depends only on standard-library
types and forward-declared application-facing classes:

```cpp
class Renderer final
{
public:
    Renderer(const Glfw& glfw, const Window& window, const std::string& applicationName);
    ~Renderer() noexcept;

    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;
    Renderer(Renderer&&) = delete;
    Renderer& operator=(Renderer&&) = delete;

    void prepare(const RenderAssets& assets, const Scene& scene);
    [[nodiscard]] RenderResult drawFrame(const Scene& scene);
    void waitIdle();
    [[nodiscard]] RendererInfo info() const;

private:
    class Impl;
    std::unique_ptr<Impl> implementation_;
};
```

There is no `vk::` type, Vulkan handle, VMA allocation, device, swapchain, or
pipeline in those declarations. Callers describe stable content through
`RenderAssets`, current placement through `Scene`, and presentation outcomes
through the engine-owned `RenderResult` enum.

Information that the tutorial prints also crosses the boundary as ordinary
values:

```cpp
struct RendererInfo
{
    std::string deviceName;
    std::uint32_t graphicsQueueFamily;
    std::uint32_t presentQueueFamily;
    std::size_t swapchainImageCount;
    std::size_t presentationSemaphoreCount;
    std::uint32_t width;
    std::uint32_t height;
    std::string imageFormat;
    std::string presentMode;
};
```

The implementation converts Vulkan formats and presentation modes to strings
before returning. `main()` can report the selected configuration without
including Vulkan just to name an enum.

The interface makes its two rendering phases and two supporting operations
explicit:

- `prepare()` validates and uploads stable scene dependencies;
- `drawFrame()` consumes current transforms and records a fresh frame;
- `waitIdle()` exposes the synchronization point required before shutdown; and
- `info()` describes the internally selected configuration without returning
  its handles.

See the complete [`renderer.hpp`][source-renderer-header].

## Hide the implementation with a pimpl

Forward declarations alone cannot hide Vulkan if `Renderer` stores its owners
directly: the compiler needs their complete types to lay out and destroy the
class. Release 0.7 instead gives the public object one
`std::unique_ptr<Renderer::Impl>`.

The complete implementation class lives in `renderer.cpp`, where the Vulkan
headers and concrete owners are already available. Its member order documents
the lifetime graph:

```cpp
// Foundational long-lived state.
Device device_;             ///< Vulkan instance, surface, device, and queues.
MemoryAllocator allocator_; ///< VMA owner created from the logical device.

// Presentation-dependent state replaced together when recreation is added.
Swapchain swapchain_; ///< Images and synchronization tied to presentation.
Pipeline pipeline_;   ///< Pipeline compatible with the swapchain format.

// Per-frame submission state.
FrameInFlight frame_;           ///< Reusable resources for the current frame slot.
bool workMayBePending_ = false; ///< Whether destruction requires a defensive wait.

// Prepared state compiled from the current scene dependencies.
RenderPreparation renderPreparation_; ///< Vulkan-free validation and plan cache.
std::vector<std::unique_ptr<CompiledMesh>> compiledMeshes_; ///< Mesh lookup by MeshId.
std::vector<CompiledRenderObject> compiledObjects_;         ///< Draw lookup by RenderObjectId.
std::optional<std::size_t> compiledGeneration_; ///< Plan generation uploaded to the GPU.
```

C++ destroys members in reverse declaration order. Prepared mesh buffers die
before the allocator that owns their VMA allocations. The frame, pipeline, and
swapchain die before the device whose handles they use. The declaration keeps
the same lifetime lesson previously visible in `main()`, but moves
responsibility for it into the component that owns the relationship.

`Renderer::~Renderer()` is defined out of line in `renderer.cpp` after `Impl`
is complete. That gives `std::unique_ptr` the complete type it needs when it
deletes the implementation while keeping the definition out of the public
header.

Copy and move remain disabled. One renderer has one Vulkan ownership tree, and
release 0.7 does not need transfer semantics for an initialised device,
surface, presentation path, frame slot, or compiled-resource lookup.

## Construct the internal tree in dependency order

The pimpl constructor rebuilds the ownership chain removed from `main()`:

```cpp
Renderer::Impl::Impl(const Glfw& glfw, const Window& window, const std::string& applicationName)
    : device_{glfw, window, applicationName},
      allocator_{device_},
      swapchain_{device_, window},
      pipeline_{device_, swapchain_.imageFormat()},
      frame_{device_, allocator_}
{
    // Construction checks follow.
}
```

The initialiser dependency is direct:

```text
Glfw + Window
      |
      v
    Device -> MemoryAllocator
      |
      +----> Swapchain -> Pipeline
      |
      +----> FrameInFlight <- MemoryAllocator
```

After construction, the implementation checks that Vulkan supplied both
queues, VMA supplied an allocator, the swapchain collections agree, and the
frame fence began signalled. Those checks used to live partly in the
application; keeping them beside ownership means every constructed renderer
receives the same invariant checks.

The public constructor creates the implementation, and its methods delegate
across the boundary:

```cpp
Renderer::Renderer(const Glfw& glfw, const Window& window, const std::string& applicationName)
    : implementation_{std::make_unique<Impl>(glfw, window, applicationName)}
{
}

void Renderer::prepare(const RenderAssets& assets, const Scene& scene)
{
    implementation_->prepare(assets, scene);
}
```

The facade stays small because the implementation owns the complexity rather
than mirroring each internal Vulkan object in the public API.

## Compile prepared meshes into indexed buffers

The CPU plan identifies distinct `MeshId`, `MaterialId`, and `RenderObjectId`
values. The renderer gives their GPU forms two private representations:

```cpp
class CompiledMesh final
{
public:
    CompiledMesh(const MemoryAllocator& allocator, const Mesh& mesh);

    [[nodiscard]] const AllocatedBuffer& vertexBuffer() const noexcept;
    [[nodiscard]] const AllocatedBuffer& indexBuffer() const noexcept;
    [[nodiscard]] std::uint32_t indexCount() const noexcept;

private:
    AllocatedBuffer vertexBuffer_;
    AllocatedBuffer indexBuffer_;
    std::uint32_t indexCount_;
};

struct CompiledRenderObject
{
    const CompiledMesh* mesh = nullptr;
    Color4 baseColor{};
};
```

One `CompiledMesh` owns both buffers needed for indexed drawing. A compiled
render object shares that mesh through a pointer and copies the selected
material colour needed at draw time. Release 0.7 has no standalone GPU material
resource; its one colour factor fits in per-draw constants.

The mesh constructor uploads both validated arrays and retains the index count:

```cpp
CompiledMesh::CompiledMesh(const MemoryAllocator& allocator, const Mesh& mesh)
    : vertexBuffer_{allocator, mesh.vertices.size() * sizeof(Vertex),
                    vk::BufferUsageFlagBits::eVertexBuffer},
      indexBuffer_{allocator, mesh.indices.size() * sizeof(std::uint32_t),
                   vk::BufferUsageFlagBits::eIndexBuffer},
      indexCount_{static_cast<std::uint32_t>(mesh.indices.size())}
{
    vertexBuffer_.write(std::as_bytes(std::span{mesh.vertices}));
    indexBuffer_.write(std::as_bytes(std::span{mesh.indices}));
}
```

Asset validation has already proved that the geometry is non-empty, contains
complete triangles, uses in-range indices, and fits the renderer's 32-bit draw
count. GPU compilation can consume those invariants rather than rediscovering
them after allocating memory.

See [`renderer.cpp`][source-renderer-cpp] and the earlier
[render-assets post][assets-post].

## Turn a plan into stable ID lookups

`Renderer::Impl::prepare()` obtains the plan covered by the previous post and
returns immediately if the renderer has already compiled its generation:

```cpp
const SceneDrawList drawList = scene.buildDrawItems();
const RenderPreparationPlan& plan = renderPreparation_.build(assets, drawList);
if (compiledGeneration_.has_value() && *compiledGeneration_ == renderPreparation_.generation())
{
    return;
}
```

An unchanged call therefore performs no device wait, buffer allocation, or
upload. A changed plan must replace buffers that an earlier submission may
still use, so preparation synchronizes before compiling it:

```cpp
if (workMayBePending_)
{
    waitIdle();
}
```

The new lookup tables are built as local values:

```cpp
std::vector<std::unique_ptr<CompiledMesh>> compiledMeshes(assets.meshes().size());
for (const MeshId meshId : plan.meshes)
{
    compiledMeshes[meshId.value] =
        std::make_unique<CompiledMesh>(allocator_, assets.meshes()[meshId.value]);
}

std::vector<CompiledRenderObject> compiledObjects(assets.renderObjects().size());
for (const PreparedRenderObject& object : plan.renderObjects)
{
    compiledObjects[object.id.value] = {
        .mesh = compiledMeshes[object.mesh.value].get(),
        .baseColor = assets.materials()[object.material.value].baseColor,
    };
}
```

Each vector is sized to the complete catalogue, but only IDs selected by the
plan receive compiled values. That preserves direct dense-ID lookup during
drawing: no map search or plan-local remapping sits between a `DrawItem` and
its resource.

Several render objects may point at the same `CompiledMesh`. The mesh lives in
a separately allocated object owned by `std::unique_ptr`, so moving the vector
into renderer state does not change the pointee address retained by those
objects.

Only after every allocation and upload succeeds does the implementation replace
its current state:

```cpp
compiledMeshes_ = std::move(compiledMeshes);
compiledObjects_ = std::move(compiledObjects);
compiledGeneration_ = renderPreparation_.generation();
```

If a new allocation or upload throws, the local partial resources clean
themselves up and `compiledGeneration_` remains behind the plan generation. A
retry of the same preparation input therefore attempts GPU compilation again
instead of falsely accepting an incomplete result.

## Require successful preparation before drawing

The old `renderFrame()` could assume its constructor had uploaded the one
triangle. The new `drawFrame()` accepts a scene, so it first enforces the
explicit phase contract:

```cpp
if (!compiledGeneration_.has_value())
{
    throw std::logic_error("Renderer::prepare must be called before drawFrame");
}
```

It then builds the current draw list and checks every referenced object against
the compiled lookup:

```cpp
const SceneDrawList drawList = scene.buildDrawItems();
for (const DrawItem& item : drawList.drawItems)
{
    if (!item.renderObject.valid() || item.renderObject.value >= compiledObjects_.size() ||
        compiledObjects_[item.renderObject.value].mesh == nullptr)
    {
        throw std::logic_error("Scene refers to an object not compiled by prepare");
    }
}
```

This permits any transform value for an object in the prepared subset. It
rejects an invalid ID, an ID outside the prepared catalogue, or a valid
catalogue ID whose object was not selected by the last successful preparation.

The preflight happens before waiting for the frame fence or acquiring a
swapchain image. A scene error therefore cannot acquire an image, signal the
image-available semaphore, and then abandon that synchronization state before
submission.

Once the checks pass, the familiar frame sequence remains: wait for the
previous submission, acquire an image, recycle the command pool, record,
submit, and present. The [first-triangle post][triangle-post] covers those
Vulkan synchronization and presentation steps; the new contract is the scene
validation that precedes them.

## Record current commands instead of durable commands

Preparation creates durable buffers, not a permanently recorded command
buffer. `drawFrame()` passes the latest flattened scene to command recording on
every successful frame:

```cpp
void Renderer::Impl::recordCommands(std::uint32_t imageIndex,
                                    const std::vector<DrawItem>& drawItems) const
{
    const vk::raii::CommandBuffer& commandBuffer = frame_.commandBuffer();
    const vk::CommandBufferBeginInfo beginInfo{
        .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit,
    };
    commandBuffer.begin(beginInfo);

    transitionToAttachment(commandBuffer, imageIndex);
    beginColorPass(commandBuffer, imageIndex);
    recordDraws(commandBuffer, drawItems);
    commandBuffer.endRendering();
    transitionToPresent(commandBuffer, imageIndex);
    commandBuffer.end();
}
```

The command sequence is split by responsibility:

- `transitionToAttachment()` makes the acquired image writable;
- `beginColorPass()` clears it and binds pipeline, viewport, scissor, and frame
  data shared by every object;
- `recordDraws()` binds each selected resource and its current constants; and
- `transitionToPresent()` makes completed colour writes visible to
  presentation.

The acquired image changes across iterations, and the single frame slot's
command buffer is recycled and recorded again. World transforms may also change
after `Scene::updateWorldTransforms()`. Recording again keeps those transient
values current while reusing the prepared vertex and index buffers.

## Separate frame-wide and per-draw shader data

Release 0.6 placed one transform in the frame uniform. With several scene
instances, fireEngine needs to distinguish the transform shared by the view
from the transform belonging to one object.

The frame uniform now gives the shared matrix its intended name and type:

```cpp
struct alignas(16) FrameUniforms
{
    Mat4 viewProjection = Mat4::identity(); ///< World-to-clip transform shared by every draw.
};

static_assert(sizeof(FrameUniforms) == 16 * sizeof(float));
static_assert(alignof(FrameUniforms) == 16);
```

Release 0.7 initialises `viewProjection` to identity. A later camera can update
that frame-wide value without changing the per-object contract established
here.

One draw supplies its world transform and material factor through push
constants:

```cpp
struct alignas(16) DrawConstants
{
    Mat4 model = Mat4::identity(); ///< Object-to-world transform for one scene node.
    Color4 baseColor{.r = 1.0f, .g = 1.0f, .b = 1.0f, .a = 1.0f}; ///< Material tint.
};

static_assert(sizeof(DrawConstants) == 20 * sizeof(float));
static_assert(alignof(DrawConstants) == 16);
static_assert(offsetof(DrawConstants, baseColor) == 16 * sizeof(float));
```

The static assertions pin the C++ representation expected by the shader. The
pipeline layout exposes the complete block to the vertex stage:

```cpp
constexpr vk::PushConstantRange drawConstants{
    .stageFlags = vk::ShaderStageFlagBits::eVertex,
    .offset = 0,
    .size = sizeof(DrawConstants),
};
```

The frame uniform remains a push descriptor at set zero, binding zero. Push
constants are separate Vulkan state, so many draws can share the same frame
descriptor while changing model and material values between draw calls.

See [`frame_in_flight.hpp`][source-frame-header],
[`draw_constants.hpp`][source-draw-constants], and
[`pipeline.cpp`][source-pipeline].

## Bind and draw each prepared object

`beginColorPass()` binds the graphics pipeline and frame uniform once. The draw
loop then resolves each `RenderObjectId` directly through the prepared lookup:

```cpp
void Renderer::Impl::recordDraws(const vk::raii::CommandBuffer& commandBuffer,
                                 const std::vector<DrawItem>& drawItems) const
{
    constexpr vk::DeviceSize bufferOffset = 0;
    for (const DrawItem& item : drawItems)
    {
        const CompiledRenderObject& object = compiledObjects_[item.renderObject.value];
        const vk::Buffer vertexBuffer = object.mesh->vertexBuffer().handle();
        commandBuffer.bindVertexBuffers(0, vertexBuffer, bufferOffset);
        commandBuffer.bindIndexBuffer(object.mesh->indexBuffer().handle(), 0,
                                      vk::IndexType::eUint32);

        const DrawConstants constants{
            .model = item.world,
            .baseColor = object.baseColor,
        };
        commandBuffer.pushConstants<DrawConstants>(*pipeline_.pipelineLayout(),
                                                   vk::ShaderStageFlagBits::eVertex, 0, constants);
        commandBuffer.drawIndexed(object.mesh->indexCount(), 1, 0, 0, 0);
    }
}
```

Each instance performs four object-specific operations:

1. bind its compiled vertex buffer;
2. bind its compiled 32-bit index buffer;
3. push its current world matrix and prepared material colour; and
4. issue one indexed draw with the mesh's retained index count.

Repeated instances of one render object repeat the constants and draw call but
reuse the same compiled buffers. Two render objects that share one mesh bind
the same geometry while supplying their own material factors.

Release 0.7 does not yet sort draw items by mesh or material. The renderer
preserves the deterministic depth-first order emitted by the scene, making the
first multi-object contract straightforward before optimisation changes its
submission policy.

## Match the shader to the two-level transform

The Slang shader mirrors the C++ frame and draw structures:

```hlsl
struct FrameUniforms
{
    float4x4 viewProjection;
};

[[vk::binding(0, 0)]]
ConstantBuffer<FrameUniforms, Std140DataLayout> frame;

struct DrawConstants
{
    float4x4 model;
    float4 baseColor;
};

[[vk::push_constant]]
ConstantBuffer<DrawConstants> draw;
```

The vertex stage applies the model transform first, then the shared
view-projection transform:

```hlsl
[shader("vertex")]
FragmentInput vertexMain(VertexInput input)
{
    FragmentInput output;
    output.position = mul(frame.viewProjection, mul(draw.model, float4(input.position, 1.0)));
    output.color = input.color * draw.baseColor;
    return output;
}
```

Object-space position becomes world-space through `draw.model`, then clip-space
through `frame.viewProjection`. The material factor multiplies the vertex
colour before interpolation. The fragment stage only returns that interpolated
RGBA value.

The public `Vertex` now supplies a three-component position and four-component
colour, and the pipeline describes matching Vulkan attributes. The
[render-assets post][assets-post] covers that layout; the renderer contribution
here is how current transform and material data join it at draw time.

See the complete [`triangle.slang`][source-shader].

## Keep the application loop at its own level

Once content is prepared, each event-loop iteration performs application and
facade operations rather than Vulkan orchestration:

```cpp
content.scene.updateWorldTransforms();
const fire_engine::RenderResult result = renderer.drawFrame(content.scene);
```

`main()` does not acquire an image, wait on a Vulkan fence, reset a command
pool, bind a pipeline, or submit a queue. It updates scene state and asks the
renderer to draw it. The application still interprets `RenderResult` because
deciding whether to continue, recreate presentation state, or exit belongs to
the event loop.

The logging path follows the same boundary. Instead of querying `Device` and
`Swapchain` directly, it asks for `RendererInfo`:

```cpp
const fire_engine::RendererInfo rendererInfo = renderer.info();
std::println("Selected Vulkan 1.4 device: {}", rendererInfo.deviceName);
std::println("Graphics queue family: {}", rendererInfo.graphicsQueueFamily);
std::println("Present queue family: {}", rendererInfo.presentQueueFamily);
```

The renderer hides mechanism without hiding outcomes the application needs to
report or act upon.

## Run the rendered-frame test

Most release 0.7 rules are device-free, but pimpl ownership, buffer upload,
command recording, submission, and presentation only become a working whole
when the application runs them together.

The existing CTest entry exercises that path for one bounded frame:

```cmake
add_test(NAME fireEngineTutorialSmoke COMMAND fireEngineTutorial --frames 1)
set_tests_properties(fireEngineTutorialSmoke PROPERTIES TIMEOUT 30)
```

It now proves the refactored route: create the facade, build application-owned
assets and scene, prepare them, update world transforms, record an indexed
draw, submit, present, wait idle, and destroy the internal ownership tree.

After configuring and building release 0.7 as described in the
[testing post][testing-post], select only that integration case with:

```shell
ctest --preset default -R "^fireEngineTutorialSmoke$"
```

The test requires a working display and Vulkan driver. The Linux CI job supplies
Xvfb and Lavapipe; a local machine without those runtime facilities can still
run the 24 device-free cases with the exclusion described in the testing post.

## Diagnose the new failure boundaries

The new interface makes stable preparation errors distinct from current frame
errors and internal Vulkan failures.

### `drawFrame()` says that `prepare()` must run first

Call `renderer.prepare(assets, scene)` after constructing the application
content and before entering the frame loop. Constructor success establishes
Vulkan ownership, not a compiled scene.

### A scene object was not compiled by `prepare()`

The current draw list contains an invalid ID, an ID beyond the prepared
catalogue, or an object outside the subset selected by the last successful
preparation. Correct the reference and prepare again when stable dependencies
change. Moving an already prepared instance does not require another upload.

### Repeating `prepare()` appears to do no GPU work

That is the intended cache hit. When the `RenderPreparation` generation matches
`compiledGeneration_`, the renderer returns before waiting for the device or
allocating buffers.

### Changed preparation waits for the whole device

Previously submitted work may still read the compiled buffers being replaced.
Release 0.7 uses `waitIdle()` as the simple safe boundary before destruction.
Deferred resource retirement can avoid that broad stall when the renderer has
multiple frames and more frequent streaming updates.

### A buffer upload fails and retrying uses the same plan

The CPU plan may already have advanced its generation, but renderer state is
only marked compiled after every temporary mesh and object lookup succeeds.
Retrying sees the generation mismatch and attempts the GPU compilation again.

### A moved node renders at its old position

Call `scene.updateWorldTransforms()` after changing local transforms and before
`drawFrame()`. Preparation deliberately ignores world matrices; command
recording consumes the current values from the new draw list.

### Geometry draws but material colour has no effect

Check the complete per-draw contract: `CompiledRenderObject::baseColor`, the
`DrawConstants` member offset and push range, the vertex-stage push, and the
matching Slang `float4`. The shader multiplies material and vertex colours; it
does not read a separate material buffer.

### Indexed geometry is missing or corrupt

Check that preparation selected the expected mesh, that `CompiledMesh` uploaded
both vectors, and that command recording binds the index buffer as
`eUint32`. CPU validation should reject empty, incomplete, or out-of-range
geometry before this boundary.

### The application needs a Vulkan handle from `RendererInfo`

`RendererInfo` is a diagnostic value, not an escape hatch to internal
ownership. Add an engine-level operation or result that expresses the real
application need rather than returning a handle whose lifetime would pierce the
facade.

### An exception leaves submitted work pending

Normal shutdown calls `waitIdle()` and can report a Vulkan error. During
exception unwinding, `Renderer::Impl` performs a non-throwing defensive device
wait before its buffers and frame resources are destroyed, logging only if that
fallback wait fails.

## What this part of release 0.7 gives us

The first five posts established the CPU-side descriptions and compiler. This
final part turns their output into a coherent Vulkan implementation:

- `Renderer` becomes the owner of the complete device, allocator, swapchain,
  pipeline, frame, and compiled-resource tree;
- the application no longer constructs or orders Vulkan rendering objects;
- the public renderer header contains no Vulkan types or handles;
- a pimpl hides implementation dependencies and preserves reverse destruction
  order;
- `RendererInfo` reports selected configuration through ordinary values;
- the facade exposes separate stable `prepare()` and current `drawFrame()`
  phases;
- unchanged preparation generations avoid waits, allocations, and uploads;
- changed plans wait before replacing buffers still visible to submitted work;
- each selected mesh compiles into reusable vertex and 32-bit index buffers;
- dense typed IDs provide direct compiled mesh and render-object lookup;
- temporary compilation state makes a failed upload retryable;
- `drawFrame()` rejects unprepared scene references before image acquisition;
- command buffers are recorded again with current scene transforms;
- frame-wide view-projection data remains separate from per-draw model and
  material data;
- push constants carry each current world matrix and material base colour;
- repeated instances reuse compiled resources while issuing distinct indexed
  draws;
- the Slang shader applies object-to-world and world-to-clip transforms in
  order and combines vertex and material colours;
- `main()` remains responsible for content, transforms, event policy, and
  presentation outcomes rather than Vulkan mechanism; and
- the rendered-frame smoke test verifies the complete refactored path through a
  real window and Vulkan driver.

A familiar coloured triangle remains on screen, but no layer owns more than its
part of the description. The application owns what exists. The scene owns where
an instance is. Preparation decides which stable resources are required. The
renderer owns their Vulkan forms and records the current frame.

That completes the release 0.7 series and the architectural plan set out in
[Refactoring fireEngine for what comes next][roadmap-post]. fireEngine now has
the boundaries needed for model loading, richer materials, visibility,
resource caching, and more advanced render compilation without pushing those
concerns back into `main()` or exposing Vulkan to application content.

## Recommended reading

- [C++ Software Design][reading-cpp-software-design] — Klaus Iglberger's guide
  to dependency inversion, implementation hiding, and designing interfaces
  around reasons to change.
- [Game Engine Architecture][reading-game-engine-architecture] — Jason
  Gregory's treatment of renderer structure, resource ownership, scene
  submission, and runtime architecture.
- [Real-Time Rendering][reading-real-time-rendering] — the wider rendering
  context for transforms, indexed geometry, materials, command generation, and
  persistent versus per-frame state.
- [Vulkan Programming Guide][reading-vulkan-programming-guide] — an
  example-rich reference for Vulkan object ownership, commands, memory,
  synchronization, and presentation.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[triangle-post]: {% post_url 2026-08-05-rendering-fireengines-first-triangle %}
[roadmap-post]: {% post_url 2026-08-08-refactoring-fireengine-for-what-comes-next %}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[maths-post]: {% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %}
[assets-post]: {% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %}
[scene-post]: {% post_url 2026-08-14-building-fireengines-first-scene-graph %}
[preparation-post]: {% post_url 2026-08-16-preparing-fireengines-scene-data-explicitly %}
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/main.cpp>
[source-renderer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/renderer.hpp>
[source-renderer-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/render/renderer.cpp>
[source-frame-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/frame_in_flight.hpp>
[source-draw-constants]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/draw_constants.hpp>
[source-pipeline]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/render/pipeline.cpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/shaders/triangle.slang>
[reading-cpp-software-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-game-engine-architecture]: <https://www.gameenginebook.com/>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-vulkan-programming-guide]: <https://www.vulkanprogrammingguide.com>
[reading-page]: {% link _tabs/reading.md %}
