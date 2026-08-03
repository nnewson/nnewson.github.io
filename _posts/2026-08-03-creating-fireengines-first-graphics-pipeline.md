---
title: "Creating fireEngine's first graphics pipeline"
date: 2026-08-03 19:45:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, slang, shaders, graphics-pipeline, cpp, cmake, vcpkg]
description: >-
  Compile a Slang vertex and fragment shader to SPIR-V, describe their C++
  interface, and create fireEngine's first Vulkan 1.4 graphics pipeline.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.4"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.3"
---

Release 0.3 gave fireEngine a memory allocator, a swapchain, and image views.
Release 0.4 describes the work that will eventually write a triangle into those
images: a vertex format, vertex and fragment shaders, their resource layout,
and a Vulkan graphics pipeline.

The result still does not draw. There is no vertex buffer, uniform buffer,
command buffer, or submitted work yet. Building the pipeline separately is
useful because it proves that the shader compiler, SPIR-V interface, device
features, swapchain format, and fixed-function state agree before resource and
command lifetimes join the problem.

This post follows the changes from [release 0.3][release-0-3] to
[release 0.4][release-0-4]. Code links are pinned to 0.4 so the walkthrough
continues to match the published source as fireEngine evolves.

> Source: [fireEngine 0.4]({{ page.release_url }})
>
> Start with the [0.3 swapchain post][swapchain-post] if you want the allocator,
> surface-policy, swapchain, and image-view setup. This post concentrates on the
> first shader and graphics-pipeline milestone.
{: .prompt-info }

## Choose US English for engine code

Before introducing the new rendering pieces, I want to record a code-style
decision that will apply from here onwards: fireEngine code will use US English.

That means identifiers, comments, and diagnostics will use spellings such as
`color`, `synchronize`, and `rasterization`, rather than `colour`,
`synchronise`, and `rasterisation`. The prose on this site can retain my usual
UK English, but the source should have one predictable convention.

This is a policy announcement rather than a 0.4 migration. Release 0.3 already
used US spellings throughout, so no identifiers were renamed here. Recording the
convention now gives later releases a rule to point at rather than a precedent
to infer.

Vulkan makes US English the practical choice. Its types, members, flags,
enumerators, and features already contain names such as
`VkPipelineColorBlendAttachmentState`,
`colorWriteMask`, `VkPipelineRasterizationStateCreateInfo`, and
`synchronization2`. Mirroring that vocabulary avoids code where an engine
`colour` sits beside a Vulkan `color`, makes searches more reliable, and keeps
new abstractions visually aligned with the API they wrap.

## Introducing Slang and the graphics pipeline

Release 0.4 introduces four connected pieces:

- **Slang** is the shading language and compiler. Its syntax is deliberately
  familiar to HLSL users, while its compiler can emit code for several graphics
  APIs and execution targets. fireEngine uses it to compile one source file
  into Vulkan SPIR-V 1.6 during the normal CMake build;
- the **shader interface** defines how CPU data, vertex attributes, values
  passed between stages, and the colour attachment meet. The declarations in
  Slang and the descriptions in C++ are separate, so their bindings, locations,
  formats, and memory layouts must agree;
- a **pipeline layout** describes the resources that shaders can access. This
  milestone reserves set zero, binding zero for a frame uniform buffer supplied
  through Vulkan 1.4 push descriptors; and
- a **graphics pipeline** combines the vertex and fragment entry points with
  the fixed-function state between and around them: vertex input, triangle
  assembly, rasterisation, multisampling, colour output, and the attachment
  format used by dynamic rendering.

Slang does not replace Vulkan's pipeline model. It produces the SPIR-V consumed
by that model. Vulkan still needs an exact description of how bytes become
vertex attributes, which entry point runs at each stage, which resources are
visible, and which state turns the shader results into pixels.

## Extend the rendering chain

Release 0.3 stopped with presentable images and their views:

```text
Vulkan device
    -> VMA allocator
    -> swapchain
        -> presentable images
            -> image views
```

Release 0.4 adds a build-time chain and a run-time chain. At build time:

```text
triangle.slang
    -> vcpkg-provided slangc
        -> SPIR-V 1.6 module
            -> fireEngineShaders target
                -> fireEngineTutorial executable dependency
```

At run time:

```text
Vulkan device with required features
    -> swapchain format
        -> push-descriptor set layout
            -> pipeline layout
                -> dynamic-rendering graphics pipeline
                    -> vertexMain and fragmentMain from one SPIR-V module
```

The source tree gains one shader and three rendering files:

```text
fireEngine-tutorial/
├── shaders/
│   └── triangle.slang
├── include/fire_engine/render/
│   ├── pipeline.hpp
│   └── vertex.hpp
└── src/render/
    └── pipeline.cpp
```

`triangle.slang` owns the programmable stages. `vertex.hpp` establishes the CPU
vertex representation that a later buffer will contain. `Pipeline` owns the
pipeline layout and graphics pipeline that later command buffers will use.

## Add Slang through vcpkg

The manifest moves to version 0.4.0 and adds one package:

```json
{
  "name": "fire-engine-tutorial",
  "version-string": "0.4.0",
  "dependencies": [
    "glfw3",
    "shader-slang",
    "vulkan-memory-allocator",
    "vulkan-headers",
    {
      "name": "vulkan-loader",
      "features": [
        { "name": "xcb", "platform": "linux" },
        { "name": "xlib", "platform": "linux" }
      ]
    }
  ]
}
```

The CMake project version moves in step with the manifest:

```cmake
project(fire_engine_tutorial
    VERSION 0.4.0
    DESCRIPTION "A development tutorial to building your own fireEngine"
    LANGUAGES CXX
)
```

Keeping both declarations at 0.4.0 means the vcpkg package metadata, Vulkan
application version compiled into C++, and release checkpoint remain aligned.

The complete manifest is [`vcpkg.json`][source-vcpkg]. The package is named
`shader-slang` in vcpkg, but its CMake configuration is found as `slang`:

```cmake
find_package(slang CONFIG REQUIRED)
```

That package exports `slang::slangc` as an imported executable target. The build
can name the target directly instead of searching `PATH`, hard-coding a vcpkg
tools directory, or asking every contributor to install a matching compiler by
hand. The compiler version therefore follows the registry baseline and manifest
used by the rest of the build.

## Compile the shader as part of the build graph

The shader is a build input rather than a checked-in binary. CMake first names
its source, output directory, and generated module:

```cmake
set(FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/shaders")
set(FIRE_ENGINE_SHADER_SOURCE
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/triangle.slang"
)
set(FIRE_ENGINE_SHADER_BINARY
    "${FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY}/triangle.spv"
)
```

Source and generated files stay on opposite sides of the source/build boundary.
The binary directory can be removed and regenerated without touching the Slang
source, and different build trees can produce their own shader artefacts.

### Make `triangle.spv` a real generated output

The custom command describes how that binary is produced:

```cmake
add_custom_command(
    OUTPUT "${FIRE_ENGINE_SHADER_BINARY}"
    COMMAND "${CMAKE_COMMAND}" -E make_directory
        "${FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY}"
    COMMAND slang::slangc
        "${FIRE_ENGINE_SHADER_SOURCE}"
        -target spirv
        -profile spirv_1_6
        -matrix-layout-column-major
        -fvk-use-entrypoint-name
        -restrictive-capability-check
        -warnings-as-errors all
        -o "${FIRE_ENGINE_SHADER_BINARY}"
    DEPENDS "${FIRE_ENGINE_SHADER_SOURCE}" slang::slangc
    COMMENT "Compiling Slang shader to SPIR-V"
    VERBATIM
)
```

Using the [`OUTPUT` form][cmake-custom-command] matters. CMake and Ninja can
compare the output with its dependencies, so an unchanged shader does not
compile on every build. Editing `triangle.slang` rebuilds it, while listing
`slang::slangc` in `DEPENDS` means a compiler update also invalidates the
output. `VERBATIM` asks CMake to preserve each argument correctly on every
supported command shell.

The compiler options, documented in Slang's
[command-line reference][slang-command-line], establish a narrow contract:

| Option | Contract |
| --- | --- |
| `-target spirv` | Emit binary SPIR-V rather than another textual shading language. |
| `-profile spirv_1_6` | Restrict the module to SPIR-V 1.6, accepted by Vulkan 1.4. |
| `-matrix-layout-column-major` | Give buffer matrices an explicit column-major storage policy. |
| `-fvk-use-entrypoint-name` | Preserve `vertexMain` and `fragmentMain` in the emitted module. |
| `-restrictive-capability-check` | Turn capability mismatches that might otherwise be warnings into errors. |
| `-warnings-as-errors all` | Give shader warnings the same build-stopping status as C++ warnings. |

The matrix option controls memory layout, not the order of the operands in a
matrix multiplication. The shader still states that order explicitly with
`mul(frame.transform, vertex)`.

The entry-point flag deserves special attention. Slang can place several entry
points in one module, but when compiling a single entry point it may emit the
conventional name `main`. Preserving the source names keeps the SPIR-V contract
stable if the file is later split, because `pipeline.cpp` always requests
`vertexMain` and `fragmentMain`.

### Attach the output to targets

A generated file does not build merely because a custom command knows how to
create it. Release 0.4 connects the rule to the default build and then makes the
executable wait for it:

```cmake
add_custom_target(fireEngineShaders ALL
    DEPENDS "${FIRE_ENGINE_SHADER_BINARY}"
)
add_dependencies(fireEngineTutorial fireEngineShaders)
```

`ALL` includes `fireEngineShaders` in the default build. The explicit target
dependency also handles a direct request to build `fireEngineTutorial`: pipeline
code cannot start with a missing shader module.

This first rule has one known boundary. Its dependencies include the single
source file and compiler, but not files later brought in through Slang `import`
or `#include`. When the shader grows beyond one file, `slangc` should emit a
dependency file and the CMake command should name it with `DEPFILE`.

### Give the executable a stable shader path

`Pipeline` opens the generated file at run time. A relative path would make the
program depend on the shell's working directory, so CMake passes the absolute
build-tree directory as a private definition:

```cmake
target_compile_definitions(fireEngineTutorial PRIVATE
    FIRE_ENGINE_SHADER_DIRECTORY="${FIRE_ENGINE_SHADER_OUTPUT_DIRECTORY}"
)
```

`pipeline.cpp` then forms the complete file name once:

```cpp
constexpr std::string_view kShaderPath =
    FIRE_ENGINE_SHADER_DIRECTORY "/triangle.spv";
```

Direct runs and CTest therefore load the same output regardless of where they
are launched. See the complete [`CMakeLists.txt`][source-cmake].

## Read the first Slang shader

As the [Slang language guide][slang-language] explains, Slang deliberately
preserves much of HLSL's surface syntax: C-family structs
and functions, vector and matrix types such as `float3` and `float4x4`, resource
types such as `ConstantBuffer`, and semantics such as `SV_Position`. On top of
that familiar base it adds a modern module and type system that later releases
can use to organise a larger shader codebase.

Release 0.4 needs only a compact part of the language. The complete shader is
[`triangle.slang`][source-shader].

### Describe the frame resource

The shader begins with the uniform data used by the vertex stage:

```hlsl
struct FrameUniforms
{
    float4x4 transform;
};

[[vk::binding(0, 0)]]
ConstantBuffer<FrameUniforms, Std140DataLayout> frame;
```

`FrameUniforms` currently contains one four-by-four transform. Wrapping it in a
`ConstantBuffer` makes `frame` a shader resource rather than an ordinary global
value. `Std140DataLayout` states the Vulkan buffer layout at the declaration,
so the later C++ uniform type will have an explicit ABI to match.

`[[vk::binding(0, 0)]]` assigns the resource to binding zero in descriptor set
zero. That order is easy to misread: the first argument is the binding and the
second is the set. The C++ pipeline layout later describes the same address as
set zero containing binding zero.

Being a `ConstantBuffer` does not make this a Vulkan push constant. It is still
a uniform-buffer descriptor. "Push" enters on the C++ side because a future
command will push that descriptor update directly into its command buffer
instead of allocating and updating a persistent descriptor set.

### Define the vertex-stage boundary

The two interface structures describe data entering the vertex shader and
leaving it for rasterisation:

```hlsl
struct VertexInput
{
    [[vk::location(0)]] float2 position : POSITION;
    [[vk::location(1)]] float3 color : COLOR;
};

struct FragmentInput
{
    float4 position : SV_Position;
    [[vk::location(0)]] float3 color : COLOR;
};
```

The `vk::location` attributes pin user-defined inputs and outputs to Vulkan
locations. Vertex location zero is two floating-point position components;
location one is three floating-point colour components. The colour passed to
the fragment stage uses location zero because stage-to-stage locations form a
different interface from vertex-buffer locations.

The `POSITION` and `COLOR` suffixes are user-defined HLSL-style semantics.
`SV_Position` is different: it is a system-value semantic telling the
rasteriser that this four-component output is the clip-space position. Keeping
matching stage values aligned in type, order, semantic, and explicit location
makes the interface clear to both Slang and Vulkan.

### Transform each vertex

The attribute on `vertexMain` marks both an entry point and its pipeline stage:

```hlsl
[shader("vertex")]
FragmentInput vertexMain(VertexInput input)
{
    FragmentInput output;
    output.position = mul(
        frame.transform,
        float4(input.position, 0.0, 1.0)
    );
    output.color = input.color;
    return output;
}
```

The two-dimensional input position is extended to a homogeneous `float4` with
zero depth and a `w` value of one. `mul` applies the frame transform, and the
result becomes the clip-space position consumed by the rasteriser. The vertex's
linear RGB value is copied unchanged into the varying output. Rasterisation will
interpolate it across the triangle before each fragment invocation.

No vertex or uniform data exists yet, but writing the interface now is useful:
pipeline creation can validate its SPIR-V while the next milestone gains an
exact description of the resources it must allocate and bind.

### Return one opaque fragment colour

The fragment stage is smaller:

```hlsl
[shader("fragment")]
float4 fragmentMain(FragmentInput input) : SV_Target
{
    return float4(input.color, 1.0);
}
```

`[shader("fragment")]` identifies the second entry point in the same module.
`SV_Target` routes the returned value to colour attachment zero. The
interpolated RGB input is extended with an alpha value of one, giving the
opaque output that the pipeline's blend state expects.

This is also where Slang's multi-entry-point model pays off. Vertex and fragment
code share their interface declarations in one source file, compile together in
one command, and live in one SPIR-V module. Vulkan still selects them separately
by stage and entry-point name.

## Mirror the vertex interface in C++

The future vertex buffer will contain instances of one standard-layout type:

```cpp
struct Vertex
{
    std::array<float, 2> position;
    std::array<float, 3> color;
};
```

The declaration is in [`vertex.hpp`][source-vertex-header]. Its names follow the
US-English code convention and match the Slang fields. The pipeline then
describes how Vulkan should walk the array:

```cpp
constexpr vk::VertexInputBindingDescription kVertexBinding{
    .binding = 0,
    .stride = static_cast<std::uint32_t>(sizeof(Vertex)),
    .inputRate = vk::VertexInputRate::eVertex,
};

constexpr std::array kVertexAttributes = {
    vk::VertexInputAttributeDescription{
        .location = 0,
        .binding = 0,
        .format = vk::Format::eR32G32Sfloat,
        .offset = static_cast<std::uint32_t>(offsetof(Vertex, position)),
    },
    vk::VertexInputAttributeDescription{
        .location = 1,
        .binding = 0,
        .format = vk::Format::eR32G32B32Sfloat,
        .offset = static_cast<std::uint32_t>(offsetof(Vertex, color)),
    },
};
```

Binding zero advances once per vertex by `sizeof(Vertex)`. Its first attribute
matches Slang's location-zero `float2`; its second matches the location-one
`float3`. `offsetof` lets the C++ compiler supply the member offsets rather than
assuming them independently.

Two assertions turn the remaining assumptions into compile-time checks:

```cpp
static_assert(std::is_standard_layout_v<Vertex>);
static_assert(sizeof(Vertex) == 5 * sizeof(float));
```

The first makes `offsetof` valid. The second rejects unexpected padding that
would change the tightly packed two-float-plus-three-float contract. See the
full pipeline implementation in [`pipeline.cpp`][source-pipeline].

## Require the Vulkan 1.4 pipeline features

Release 0.2 already queried Vulkan 1.3 dynamic-rendering and synchronization-2
features. Device inspection now extends that query through the Vulkan 1.4
feature structure:

```cpp
const auto features = physicalDevice.getFeatures2<
    vk::PhysicalDeviceFeatures2,
    vk::PhysicalDeviceVulkan13Features,
    vk::PhysicalDeviceVulkan14Features
>();

const auto& features14 =
    features.get<vk::PhysicalDeviceVulkan14Features>();
```

The candidate is rejected unless `pushDescriptor` and `maintenance5` are both
available. Vulkan 1.4 promoted the earlier `VK_KHR_push_descriptor` and
`VK_KHR_maintenance5` functionality into the core API, so fireEngine queries
the core features rather than requiring those extension names.

A conformant Vulkan 1.4 driver is required to report both features. These checks
are defensive diagnostics for incomplete or preview implementations, continuing
the approach used for the Vulkan 1.3 feature checks in release 0.2.

Support is not enablement. The logical-device chain must still request the
features the engine intends to use:

```cpp
vk::PhysicalDeviceVulkan14Features enabledFeatures14{
    .maintenance5 = vk::True,
    .pushDescriptor = vk::True,
};
vk::PhysicalDeviceVulkan13Features enabledFeatures13{
    .pNext = &enabledFeatures14,
    .synchronization2 = vk::True,
    .dynamicRendering = vk::True,
};

const vk::DeviceCreateInfo deviceCreateInfo{
    .pNext = &enabledFeatures13,
    // Queue and extension fields omitted here.
};
```

The order of designated initializers follows the Vulkan structure declarations:
`maintenance5` appears before `pushDescriptor`. Both feature locals are mutable
because each `pNext` is a non-const pointer even though creation does not modify
the values.

### Keep the device-create chain manual

This is one of the few places where the release does not use
`vk::StructureChain`. `vk::DeviceCreateInfo` still contains the deprecated
`enabledLayerCount` and `ppEnabledLayerNames` members. Storing that structure in
a `vk::StructureChain` copies those members, and this build rejects the
resulting deprecation diagnostics under `-Werror`.

The code therefore links `vk::DeviceCreateInfo` to the Vulkan 1.3 and 1.4
feature structures manually. The feature query above can use
`vk::StructureChain` through `getFeatures2` because it does not contain the
problematic device-create structure. The complete changes are in
[`device.cpp`][source-device].

## Create a layout for the future frame descriptor

The shader reserves set zero, binding zero. C++ describes the matching binding
as one uniform buffer visible to the vertex stage:

```cpp
constexpr vk::DescriptorSetLayoutBinding kFrameUniformBinding{
    .binding = 0,
    .descriptorType = vk::DescriptorType::eUniformBuffer,
    .descriptorCount = 1,
    .stageFlags = vk::ShaderStageFlagBits::eVertex,
};
```

The descriptor-set layout carries the push-descriptor flag:

```cpp
const vk::DescriptorSetLayoutCreateInfo createInfo{
    .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptor,
    .bindingCount = 1,
    .pBindings = &kFrameUniformBinding,
};
```

As described by the Vulkan specification's
[push-descriptor section][vulkan-push-descriptors], push descriptors record
descriptor updates inline in a command buffer. They do not need a descriptor
pool or allocated descriptor set, which suits a single per-frame uniform in
this first pipeline. A later command will still need a real uniform buffer and
must push its descriptor before drawing.

The descriptor-set layout is used to create a pipeline layout at set zero. It
can then be destroyed: Vulkan has already incorporated its definition into the
pipeline layout, and no descriptor set will ever be allocated from it. The
pipeline layout remains a `Pipeline` member because future push-descriptor
commands must name it while recording frames.

## Load SPIR-V without creating shader modules

Pipeline creation reads the generated binary into 32-bit words. The loader
rejects a missing or empty file, a byte count that is not divisible by four, and
an incomplete read before Vulkan sees the data:

```cpp
std::ifstream file{std::string{path}, std::ios::ate | std::ios::binary};
if (!file)
{
    throw std::runtime_error(
        "Could not open compiled shader: " + std::string{path}
    );
}

const std::streamoff byteCount = file.tellg();
if (byteCount <= 0 ||
    byteCount % static_cast<std::streamoff>(sizeof(std::uint32_t)) != 0)
{
    throw std::runtime_error(
        "Compiled shader is not valid SPIR-V: " + std::string{path}
    );
}

std::vector<std::uint32_t> code(
    static_cast<std::size_t>(byteCount) / sizeof(std::uint32_t)
);
file.seekg(0, std::ios::beg);
file.read(
    reinterpret_cast<char*>(code.data()),
    static_cast<std::streamsize>(byteCount)
);
if (!file)
{
    throw std::runtime_error(
        "Could not read compiled shader: " + std::string{path}
    );
}
return code;
```

Older Vulkan code would normally create a `VkShaderModule` from those words,
reference it during pipeline creation, then destroy it. Vulkan 1.4's
[maintenance5 path][vulkan-inline-spirv] allows the create info to be chained
directly into each pipeline stage instead:

```cpp
const vk::ShaderModuleCreateInfo moduleInfo{
    .codeSize = shaderCode.size() * sizeof(std::uint32_t),
    .pCode = shaderCode.data(),
};

const vk::StructureChain vertexStage{
    vk::PipelineShaderStageCreateInfo{
        .stage = vk::ShaderStageFlagBits::eVertex,
        .module = nullptr,
        .pName = "vertexMain",
    },
    moduleInfo,
};
```

The fragment stage chains the same `moduleInfo` but selects `fragmentMain`.
Both structure chains and the vector of SPIR-V words remain alive until pipeline
creation returns, so every copied `pNext` and `pCode` pointer stays valid.

This is not run-time Slang compilation. `slangc` finished during the build;
the executable reads already compiled SPIR-V. Maintenance5 removes the temporary
Vulkan shader-module handles, not the compilation step or the shader bytecode.

## Describe the fixed-function pipeline

The two shader stages are only part of a Vulkan graphics pipeline. Release 0.4
also supplies the state around them:

| State | Release 0.4 choice |
| --- | --- |
| Vertex input | One interleaved binding containing `float2` position and `float3` colour. |
| Input assembly | Triangle list, so every three vertices form one independent triangle. |
| Viewport and scissor | One of each, with their values marked dynamic. |
| Rasterisation | Filled polygons, no face culling, line width 1.0. |
| Multisampling | One sample per pixel. |
| Colour blending | Disabled, with red, green, blue, and alpha writes enabled. |
| Depth and stencil | Absent for this two-dimensional first triangle. |
| Tessellation | Absent because there are no tessellation shader stages. |

Viewport and scissor values depend on the current swapchain extent and will be
set when a command buffer records a frame. Making them dynamic avoids baking
800-by-600—or the 1600-by-1200 framebuffer size on the test machine—into the
pipeline. The pipeline still declares that one viewport and one scissor will be
used.

There is no culling because this milestone has not yet chosen a durable
framebuffer-space winding convention. There is no blending because the fragment
shader returns the final opaque colour. These are deliberate first-pipeline
defaults, not general renderer policy.

## Target the swapchain with dynamic rendering

A traditional graphics pipeline is created for a compatible render pass.
fireEngine instead uses the
[dynamic-rendering feature][vulkan-dynamic-rendering] enabled since release
0.2. The swapchain's selected format is chained directly into pipeline
creation:

```cpp
const vk::StructureChain pipelineCreateChain{
    vk::GraphicsPipelineCreateInfo{
        .stageCount = static_cast<std::uint32_t>(shaderStages.size()),
        .pStages = shaderStages.data(),
        .pVertexInputState = &vertexInput,
        .pInputAssemblyState = &inputAssembly,
        .pViewportState = &viewportState,
        .pRasterizationState = &rasterization,
        .pMultisampleState = &multisampling,
        .pColorBlendState = &colorBlending,
        .pDynamicState = &dynamicState,
        .layout = *pipelineLayout,
    },
    vk::PipelineRenderingCreateInfo{
        .colorAttachmentCount = 1,
        .pColorAttachmentFormats = &colorFormat,
    },
};
```

`Pipeline` receives `swapchain.imageFormat()` from `main()`, so the fragment
output state is compatible with the image views created in 0.3. Depth and
stencil formats remain undefined, making a null depth/stencil state valid. A
null pipeline-cache argument is also intentional: one pipeline compiled once at
startup does not yet justify cache persistence or invalidation policy.

The resulting RAII pipeline and its layout become the two members of
[`Pipeline`][source-pipeline-header].

## Give the pipeline one RAII owner

As with the allocator and swapchain owners introduced in release 0.3, the
public class makes ownership and permitted operations explicit:

```cpp
class Pipeline final
{
public:
    Pipeline(const Device& device, vk::Format colorFormat);
    ~Pipeline() = default;

    Pipeline(const Pipeline&) = delete;
    Pipeline& operator=(const Pipeline&) = delete;
    Pipeline(Pipeline&&) = delete;
    Pipeline& operator=(Pipeline&&) = delete;

    [[nodiscard]] const vk::raii::PipelineLayout&
    pipelineLayout() const noexcept;
    [[nodiscard]] const vk::raii::Pipeline& pipeline() const noexcept;

private:
    vk::raii::PipelineLayout pipelineLayout_{nullptr};
    vk::raii::Pipeline pipeline_{nullptr};
};
```

The default destructor delegates both releases to Vulkan-Hpp, and reverse
declaration order releases the pipeline first and the layout second. That order
reflects the layout's future use by push-descriptor commands rather than a
Vulkan creation dependency; Vulkan would allow the layout to be destroyed once
the pipeline exists.

Copy operations remain deleted because the handles have unique ownership, while
moves remain deleted so the owner's place in the startup lifetime stays
explicit. The accessors return const references rather than copying or
transferring either owner. Later command recording will use those references to
push the frame descriptor and bind the graphics pipeline.

## Leave `main()` with one more owner

The startup path adds one line after swapchain creation:

```cpp
const fire_engine::Device device{glfw, window, applicationName};
const fire_engine::MemoryAllocator allocator{device};
const fire_engine::Swapchain swapchain{device, window};
const fire_engine::Pipeline pipeline{device, swapchain.imageFormat()};
```

The reverse destruction order releases the pipeline before the swapchain and
device it depends on. `main()` does not need a manual handle check: Vulkan-Hpp's
RAII constructors throw if either pipeline object cannot be created, so reaching
the final diagnostic already proves success. See [`main.cpp`][source-main].

## Configure, build, and run release 0.4

The development prerequisites and platform policy remain those described in
the [0.1 foundation post][foundation-post]. Check out the exact release:

```shell
git clone --branch 0.4 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

Configure and build with the existing presets:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

The build now prints `Compiling Slang shader to SPIR-V` before the executable is
complete. Run it on macOS or Linux with:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

The release 0.4 run was captured on an Apple M2 Pro running macOS 26, using the
KosmicKrisp driver from the LunarG Vulkan SDK:

```text
Selected Vulkan 1.4 device: Apple M2 Pro
Graphics queue family: 0
Present queue family: 0
Logical device and queues created.
VMA allocator created.
Swapchain created: 3 images at 1600x1200 (B8G8R8A8Srgb, Fifo).
Pipeline layout and dynamic-rendering pipeline created.
```

The window still closes immediately. No frame can appear until command and
resource work arrives, but that final line proves that the driver accepted the
complete shader and pipeline contract.

The same path remains registered as a CTest smoke test:

```shell
ctest --preset default
```

CTest now reaches shader loading and pipeline creation as well as the device,
allocator, swapchain, and image views established by earlier releases.

## Prove shader compilation in CI

`ci.yml` does not need a workflow change. Every platform build restores the new
vcpkg package and builds the default target, so each one runs the same
`slang::slangc` command and treats shader warnings as failures. The existing
manifest-based cache key also changes when `vcpkg.json` changes, preventing a
0.3 dependency cache from masquerading as the 0.4 environment.

Linux still goes further. Its Lavapipe process runs CTest inside Xvfb, which now
proves that a software Vulkan 1.4 implementation accepts the enabled features,
push-descriptor layout, inline SPIR-V, swapchain format, and dynamic-rendering
pipeline. macOS and Windows continue to provide build coverage without a
compatible hosted-runner driver. See the complete [`ci.yml`][source-ci].

## Diagnose the new failure boundaries

Release 0.4 introduces failures on both sides of the executable boundary.

### CMake cannot find Slang

`find_package(slang CONFIG REQUIRED)` reports that the package configuration is
missing. Reconfigure through the vcpkg preset, confirm `VCPKG_ROOT` points to
the intended vcpkg checkout, and let manifest mode install `shader-slang`.
Installing an unrelated `slangc` on `PATH` does not satisfy the imported-target
contract.

### Slang compilation fails

The build stops before C++ linking. Read the `slangc` diagnostic first: syntax,
stage-interface, capability, and warning failures are deliberately part of the
normal build. If an imported shader module was recently added, also remember
that release 0.4 does not yet generate a depfile for transitive shader inputs.

### The compiled shader cannot be opened

The error contains the absolute expected path. Building only a stale executable,
moving it away from its build tree, or removing `build/shaders/triangle.spv`
after compilation can all cause this. Rebuilding `fireEngineTutorial` should
recreate the output through its target dependency.

### The compiled shader is not valid SPIR-V

The file is empty or its size is not a multiple of one 32-bit SPIR-V word. That
points to a truncated, replaced, or otherwise damaged build artefact before any
driver-specific pipeline validation begins.

### No device supports push descriptors or maintenance5

The physical-device rejection list names the unavailable feature. A conformant
Vulkan 1.4 device should expose the promoted functionality, so this is most
likely an older, incomplete, or preview Vulkan implementation rather than a
pipeline-state error.

### Pipeline creation throws `vk::SystemError`

The driver rejected some part of the combined contract: SPIR-V, entry-point
names, shader interfaces, pipeline layout, vertex attributes, fixed-function
state, or dynamic-rendering attachment format. A Debug build with validation is
the most useful next step because the validation message can identify the
specific mismatch hidden behind the pipeline-creation result.

## What release 0.4 gives us

Release 0.3 established presentable storage. Release 0.4 establishes the program
that will eventually write into it and the Vulkan state that will execute that
program:

- Slang is installed through the pinned vcpkg manifest;
- `slang::slangc` participates in the CMake build as an imported executable
  target;
- one source file compiles into a SPIR-V 1.6 module containing vertex and
  fragment entry points;
- strict capability checks and warnings make shader diagnostics build
  failures;
- the generated output is dependency-tracked and available to direct runs and
  CTest;
- the shader defines an explicit std140 frame uniform at set zero, binding zero;
- explicit Vulkan locations connect vertex data and stage-to-stage colour;
- a standard-layout C++ vertex type matches the shader's position and colour;
- device selection checks push-descriptor and maintenance5 support;
- logical-device creation enables the required Vulkan 1.3 and 1.4 features;
- a push-descriptor layout reserves the future frame uniform without a
  descriptor pool;
- maintenance5 supplies SPIR-V during pipeline creation without temporary
  `VkShaderModule` objects;
- fixed-function state describes filled, unculled, opaque triangle-list
  rendering;
- dynamic viewport and scissor values remain ready for the frame extent;
- dynamic rendering makes the pipeline compatible with the selected swapchain
  format; and
- one RAII owner preserves the pipeline layout and graphics pipeline lifetimes.

There is still no vertex buffer or uniform buffer to satisfy the interfaces,
and there are no command pools, command buffers, semaphores, fences, draw calls,
or presented frames. That is now a much narrower gap. The next release can
allocate the data already described here and record work against a pipeline the
driver has already accepted.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan] — a detailed treatment of the
  pipeline, shader-interface, descriptor, command, and synchronization model.
  Its examples predate current Vulkan, but the underlying division between
  programmable stages and explicit pipeline state remains valuable.
- [How to Vulkan][reading-how-to-vulkan] — a compact, code-first modern Vulkan
  guide whose shader and graphics-pipeline sections provide a useful comparison
  with this tutorial's Vulkan-Hpp RAII and dynamic-rendering approach.
- [Your first Slang shader][reading-first-slang] — the official introduction
  to Slang source, entry points, `slangc`, cross-target compilation, SPIR-V,
  and deterministic resource bindings.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-3]: {{ page.previous_release_url }}
[release-0-4]: {{ page.release_url }}
[swapchain-post]: {% post_url 2026-08-01-preparing-fireengine-for-its-first-frame %}
[foundation-post]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[source-vcpkg]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/vcpkg.json
[source-cmake]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/CMakeLists.txt
[source-shader]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/shaders/triangle.slang
[source-vertex-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/include/fire_engine/render/vertex.hpp
[source-pipeline-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/include/fire_engine/render/pipeline.hpp
[source-pipeline]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/src/render/pipeline.cpp
[source-device]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/src/render/device.cpp
[source-main]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/src/main.cpp
[source-ci]: https://github.com/nnewson/fireEngine-tutorial/blob/0.4/.github/workflows/ci.yml
[slang-language]: https://docs.shader-slang.org/en/latest/external/slang/docs/user-guide/02-conventional-features.html
[slang-command-line]: https://docs.shader-slang.org/en/latest/external/slang/docs/command-line-slangc-reference.html
[cmake-custom-command]: https://cmake.org/cmake/help/latest/command/add_custom_command.html
[vulkan-inline-spirv]: https://docs.vulkan.org/guide/latest/ways_to_provide_spirv.html
[vulkan-dynamic-rendering]: https://docs.vulkan.org/features/latest/features/proposals/VK_KHR_dynamic_rendering.html
[vulkan-push-descriptors]: https://docs.vulkan.org/spec/latest/chapters/descriptorsets.html
[reading-page]: {% link _tabs/reading.md %}
[reading-vulkan]: https://www.vulkanprogrammingguide.com
[reading-how-to-vulkan]: https://howtovulkan.com
[reading-first-slang]: https://shader-slang.org/docs/first-slang-shader
