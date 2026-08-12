---
title: Describing fireEngine's render assets without Vulkan
date: 2026-08-12 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, rendering, assets, meshes, materials, type-safety, architecture, cpp]
description: >-
  Move fireEngine's vertices, indexed meshes, materials, render objects, and
  asset ownership into a typed CPU-side model with no Vulkan dependencies.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

Release 0.6 could draw one triangle because the renderer already knew exactly
what that triangle was. Its three vertices were a renderer-owned constant, its
vertex buffer belonged to the renderer, and there was no need to name a mesh,
material, or reusable render object outside the Vulkan implementation.

That path proves rendering, but it cannot scale into application-owned content.
A model loader should not construct Vulkan buffers. A scene node should not
need a pipeline handle to identify what it instances. Reusing one mesh with two
materials should not require duplicating vertex data simply because the
renderer previously bundled everything together.

Release 0.7 moves those descriptions to the CPU side. `Color4`, `Vertex`,
`Mesh`, `Material`, `RenderObject`, and `RenderAssets` form a small graphics
model that contains no Vulkan types. Strongly typed IDs connect the pieces, and
one validation pass rejects descriptions that cannot be compiled safely later.

This is the third post based on release 0.7. The
[first post][testing-post] established the device-free test boundary, and the
[second][maths-post] introduced the `Vec3`, `Vec4`, and `Mat4` vocabulary used by
the scene. This post concentrates on render descriptions and their ownership.
Scene hierarchy, preparation-plan caching, and renderer-owned GPU resources
remain separate topics in the posts that follow.

The walkthrough follows the asset changes from [release 0.6][release-0-6] to
[release 0.7][release-0-7]. Every source link remains pinned to 0.7 so the
examples continue to match the published checkpoint.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Giving fireEngine a small maths vocabulary][maths-post] for the
> vector and matrix types used here. This post stops at validated CPU-side
> descriptions; it does not yet compile them into Vulkan resources.
{: .prompt-info }

## Introduce a typed asset graph

The new asset relationships form a small dependency graph:

```text
RenderObjectId
    -> RenderObject
        -> MeshId
            -> Mesh
                -> Vertex
                    -> Vec3 position
                    -> Color4 color
        -> MaterialId
            -> Material
                -> Color4 baseColor
```

`RenderAssets` owns the dense collections at the right-hand side. A render
object connects one mesh and one material, while a scene will later refer to the
render object through its ID.

These are explicit domain types rather than one generic graph abstraction.
There are only three relationships to express, and naming each one makes an
invalid connection harder to write and easier to diagnose.

The source tree gains one public graphics layer and one internal validator:

```text
include/fire_engine/graphics/
├── color4.hpp
├── detail/
│   └── asset_validation.hpp
├── material.hpp
├── mesh.hpp
├── render_assets.hpp
├── render_ids.hpp
├── render_object.hpp
└── vertex.hpp

src/graphics/
├── asset_validation.cpp
└── render_assets.cpp

tests/graphics/
└── test_asset_validation.cpp
```

The files live under `graphics`, not `render`, because they describe content
rather than the Vulkan mechanism that consumes it.

## Keep Vulkan at the compilation boundary

"Vulkan-free" does not mean these values will never reach Vulkan. It means they
can be created, inspected, validated, loaded, and traversed without Vulkan being
part of their interface.

None of the new public graphics headers contains a Vulkan handle, allocation,
descriptor, format, usage flag, or command type. Adding an asset does not upload
memory or record work. It changes an ordinary CPU-owned catalogue and returns a
small ID.

The renderer will eventually compile the required descriptions into vertex and
index buffers, pipeline state, push constants, and draw commands. Keeping that
conversion on the renderer side preserves a useful dependency direction:

```text
application content -> Vulkan-free graphics descriptions -> renderer -> Vulkan
```

The arrow does not point back. A mesh can exist before the renderer, and a test
can reject malformed geometry without opening a window or creating a device.

## Give colours their own domain type

The maths post introduced `Vec4` for homogeneous coordinates and row/column
products. A colour also contains four floats, but sharing a storage shape does
not make it the same concept.

[`Color4`][source-color4] uses colour-domain names and deliberately exposes no
vector operations:

```cpp
struct Color4
{
    float r = 0.0f;
    float g = 0.0f;
    float b = 0.0f;
    float a = 0.0f;

    [[nodiscard]] constexpr bool operator==(const Color4&) const noexcept = default;
};

static_assert(sizeof(Color4) == 4 * sizeof(float));
static_assert(std::is_aggregate_v<Color4>);
static_assert(std::is_standard_layout_v<Color4>);
static_assert(std::is_trivially_copyable_v<Color4>);
```

`r`, `g`, `b`, and `a` communicate intent at every call site. There is no dot
product because a colour is not a direction or homogeneous position, even
though both types can cross a shader interface as four contiguous floats.

The static assertions pin the representation relied upon by vertex data and
push constants. `Color4` remains an aggregate for designated initialisation, is
standard-layout for predictable member offsets, and is trivially copyable for
byte-wise transfer.

A default `Color4{}` is transparent black because every component begins at
zero. Places that require a neutral multiplicative colour choose opaque white
explicitly rather than changing the meaning of the type's default state.

## Move vertices out of the Vulkan renderer

Release 0.6 stored its vertex type under `render/`. Position was a raw array of
two floats already in clip space, and colour was a raw array of three floats.
That was enough for a fixed two-dimensional triangle.

Release 0.7 moves [`Vertex`][source-vertex] into the Vulkan-free graphics layer:

```cpp
struct Vertex
{
    Vec3 position;
    Color4 color;
};
```

Position is now three-dimensional and explicitly object-space. The scene's
model matrix will decide where the object appears, and the frame's
view-projection matrix will eventually decide how world space reaches the
screen. The vertex description no longer assumes that application content has
already been converted to clip space.

Colour grows from RGB to RGBA. Alpha does not participate in blending in release
0.7—the pipeline has blending disabled and the current data remains opaque—but
carrying the complete value now keeps vertex and material colour interfaces
consistent.

The type contains no Vulkan binding or attribute metadata. The pipeline remains
responsible for describing how this C++ representation is consumed by the
shader, while static assertions there require `Vertex` to remain standard-layout
and exactly seven floats wide.

## Make a mesh more than a vertex array

[`Mesh`][source-mesh] groups vertices with 32-bit triangle indices:

```cpp
struct Mesh
{
    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> indices;
};
```

An index names an entry in the vertex array. Every group of three indices forms
one triangle because the current graphics pipeline uses triangle-list topology.
The same vertex can therefore participate in several triangles without copying
all of its attributes into the mesh again.

The first triangle still uses `{0, 1, 2}`, so it does not yet demonstrate
sharing. The indexed representation establishes the contract needed by larger
meshes and changes the eventual render command from `draw` to `drawIndexed`.

`std::uint32_t` gives the renderer one fixed index width. Supporting 16-bit
indices later can be an explicit extension instead of an ambiguity that each
consumer interprets differently.

The mesh owns ordinary vectors. It does not own a vertex buffer, index buffer,
VMA allocation, device address, or upload state. Those are compiled resources,
not part of the source description.

## Keep the first material deliberately small

A material describes how a mesh should appear. Release 0.7 needs only one
unlit colour factor:

```cpp
struct Material
{
    Color4 baseColor{.r = 1.0f, .g = 1.0f, .b = 1.0f, .a = 1.0f}; ///< Vertex color factor.
};
```

Opaque white is the identity for component-wise colour multiplication, so a
default material leaves vertex colours unchanged. The tutorial material uses a
slightly blue-white factor to prove that material data reaches each draw.

There are no textures, samplers, normals, metallic or roughness factors,
lighting models, or pipeline variants yet. Adding those fields before a shader
uses them would make the description look more complete without establishing
their loading, validation, binding, or rendering contracts.

See [`material.hpp`][source-material].

## Connect one mesh and material as a render object

A mesh is reusable geometry, and a material is reusable appearance.
[`RenderObject`][source-render-object] connects one of each without owning
either:

```cpp
struct RenderObject
{
    MeshId mesh;
    MaterialId material;
};
```

That indirection lets several render objects share one mesh with different
materials, or share one material across different meshes. A scene node will
instance a `RenderObjectId`, keeping scene hierarchy separate from the catalogue
that owns geometry and appearance.

The name is intentionally narrower than `SceneNode`. A render object describes
the reusable mesh/material relationship; it has no parent, children, local
transform, world transform, or Vulkan state.

## Prevent unrelated IDs from being mixed

The three ID types have the same representation but different meanings:

```cpp
struct MeshId
{
    std::size_t value = std::numeric_limits<std::size_t>::max();

    [[nodiscard]] constexpr bool valid() const noexcept
    {
        return value != std::numeric_limits<std::size_t>::max();
    }

    [[nodiscard]] constexpr bool operator==(const MeshId&) const noexcept = default;
};

// MaterialId and RenderObjectId use the same representation and validity rule.
```

Using raw `std::size_t` values would allow a material index to be passed where a
mesh index is expected. Distinct types turn that domain mistake into a compiler
error while retaining the storage and lookup cost of a dense index.

The maximum `std::size_t` value is reserved as the invalid sentinel, making a
default-constructed ID invalid. Zero remains a valid ID because it names the
first item in its owning collection.

The IDs are stable across vector reallocations because they store positions,
not pointers or references into vector storage. Release 0.7 does not remove or
reorder assets, so appending another description leaves existing indices
unchanged.

See the complete [`render_ids.hpp`][source-render-ids].

## Give all render descriptions one owner

[`RenderAssets`][source-render-assets] owns separate dense collections for the
three description types:

```cpp
class RenderAssets final
{
public:
    [[nodiscard]] MeshId addMesh(Mesh mesh);
    [[nodiscard]] MaterialId addMaterial(Material material);
    [[nodiscard]] RenderObjectId addRenderObject(RenderObject renderObject);

    [[nodiscard]] const std::vector<Mesh>& meshes() const noexcept;
    [[nodiscard]] const std::vector<Material>& materials() const noexcept;
    [[nodiscard]] const std::vector<RenderObject>& renderObjects() const noexcept;

    [[nodiscard]] std::size_t revision() const noexcept;

    // Construction and move operations omitted here.

private:
    std::vector<Mesh> meshes_;
    std::vector<Material> materials_;
    std::vector<RenderObject> renderObjects_;
    std::size_t revision_ = 0;
};
```

The insertion methods calculate an ID from the current collection size before
appending the value:

```cpp
MeshId RenderAssets::addMesh(Mesh mesh)
{
    const MeshId id{.value = meshes_.size()};
    meshes_.push_back(std::move(mesh));
    ++revision_;
    return id;
}
```

Meshes move their potentially larger vectors into ownership. Materials and
render objects are small values and are copied into their collections. Every
insertion increments the shared revision because each can change what GPU
preparation will eventually require.

The collection accessors return const vectors. Callers can inspect the catalogue
but cannot modify an element behind `RenderAssets` and bypass its revision. New
mutation operations will need to update the revision as part of their contract.

Copying is disabled so that one catalogue has one identity and one set of dense
ID spaces. Moving transfers the descriptions and updates the affected revision
state, preventing an observer from mistaking a moved-from or replaced catalogue
for its previous contents.

See the complete [`render_assets.cpp`][source-render-assets-cpp].

## Validate descriptions before compiling them

Insertion establishes ownership but does not claim that every relationship is
ready to render. A render object can contain a default invalid ID, an index can
point beyond its vertex array, and a floating-point colour can contain infinity
or NaN.

The internal [`validateAssets()`][source-validation] pass checks the whole
catalogue before GPU preparation begins. Its rules are:

- every mesh has at least one vertex;
- every mesh has a non-empty index list containing complete groups of three;
- one draw's index count fits the renderer's 32-bit count;
- every index refers to an existing vertex;
- every material colour component is finite; and
- every render object refers to an assigned, in-range mesh and material.

Geometry validation keeps related failures together:

```cpp
for (const Mesh& mesh : assets.meshes())
{
    if (mesh.vertices.empty())
    {
        throw std::invalid_argument("A prepared mesh must contain vertices");
    }
    if (mesh.indices.empty() || mesh.indices.size() % 3 != 0)
    {
        throw std::invalid_argument("A prepared mesh must contain complete indexed triangles");
    }
    if (std::ranges::any_of(mesh.indices, [&mesh](std::uint32_t index)
                            { return index >= mesh.vertices.size(); }))
    {
        throw std::invalid_argument("A mesh index refers beyond its vertex array");
    }
}
```

The maximum-index-count check is omitted from the excerpt but remains part of
the complete source.

Typed IDs prevent mixing categories at compile time; validation catches values
that are the right category but still invalid or out of range:

```cpp
for (const RenderObject& renderObject : assets.renderObjects())
{
    if (!renderObject.mesh.valid() ||
        renderObject.mesh.value >= assets.meshes().size())
    {
        throw std::invalid_argument("A render object refers to a missing mesh");
    }
    if (!renderObject.material.valid() ||
        renderObject.material.value >= assets.materials().size())
    {
        throw std::invalid_argument("A render object refers to a missing material");
    }
}
```

This is still device-free work. Validation receives `RenderAssets`, walks CPU
values, and reports `std::invalid_argument`; it does not need a renderer or
Vulkan error code.

The testing post explained why this function moved behind a testable `detail`
interface. Here the important contract is when validation happens: after the
application has assembled a catalogue and before the renderer treats those
descriptions as safe compilation input. The next render-preparation post will
cover that call site and its caching policy.

## Make the application own the triangle description

Release 0.6 constructed and uploaded the fixed triangle inside `Renderer`.
Release 0.7's application instead builds the public description through the
same API that a future model loader can target:

```cpp
TutorialContent content;
const fire_engine::MeshId mesh = content.assets.addMesh({
    .vertices =
        {
            fire_engine::Vertex{
                .position = {.x = 0.0f, .y = -0.6f, .z = 0.0f},
                .color = {.r = 1.0f, .g = 0.2f, .b = 0.1f, .a = 1.0f},
            },
            fire_engine::Vertex{
                .position = {.x = 0.6f, .y = 0.6f, .z = 0.0f},
                .color = {.r = 0.1f, .g = 1.0f, .b = 0.2f, .a = 1.0f},
            },
            fire_engine::Vertex{
                .position = {.x = -0.6f, .y = 0.6f, .z = 0.0f},
                .color = {.r = 0.2f, .g = 0.3f, .b = 1.0f, .a = 1.0f},
            },
        },
    .indices = {0, 1, 2},
});
const fire_engine::MaterialId material = content.assets.addMaterial({
    .baseColor = {.r = 0.9f, .g = 0.95f, .b = 1.0f, .a = 1.0f},
});
const fire_engine::RenderObjectId triangle = content.assets.addRenderObject({
    .mesh = mesh,
    .material = material,
});

// Scene-node construction is omitted here.
```

No Vulkan owner appears in this construction path. The application states what
the triangle contains, receives typed references, and then uses the render-object
ID when it builds its scene.

`makeTriangleScene()` is tutorial bootstrap code, not a special renderer path.
Replacing it with a loader later should change where these descriptions come
from rather than how the renderer consumes them.

See the complete [`main.cpp`][source-main].

## Keep the shader-facing layout explicit

Moving `Vertex` out of the renderer does not remove the need for its C++ and
shader representations to agree. It changes which side owns the description.

The pipeline reads the public type to define one interleaved binding:

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
        .format = vk::Format::eR32G32B32Sfloat,
        .offset = static_cast<std::uint32_t>(offsetof(Vertex, position)),
    },
    vk::VertexInputAttributeDescription{
        .location = 1,
        .binding = 0,
        .format = vk::Format::eR32G32B32A32Sfloat,
        .offset = static_cast<std::uint32_t>(offsetof(Vertex, color)),
    },
};
```

The Slang input uses the same locations and widths:

```hlsl
struct VertexInput
{
    [[vk::location(0)]] float3 position : POSITION;
    [[vk::location(1)]] float4 color : COLOR;
};
```

The maths post covered the model and view-projection transform chain. The asset
contribution is the data on either side of it: object-space position, vertex
colour, and material base colour.

The vertex stage multiplies the two colours before interpolation:

```hlsl
output.color = input.color * draw.baseColor;
```

This lets the same vertex colours be reused with a different material factor.
The fragment stage simply returns the interpolated result.

See [`pipeline.cpp`][source-pipeline] and
[`triangle.slang`][source-shader].

## Test the asset contract without Vulkan

The previous testing post established the Catch2 target. The asset tests use it
to exercise the description rules directly.

[`test_asset_validation.cpp`][source-test-validation] contributes four cases:

- complete mesh, material, and render-object descriptions are accepted;
- empty vertices, empty indices, incomplete triangles, and out-of-range indices
  are rejected;
- infinity in any material colour component is rejected; and
- invalid or out-of-range mesh and material IDs are rejected.

One additional case in
[`test_render_preparation.cpp`][source-test-preparation] verifies that `Color4`
exposes `r`, `g`, `b`, and `a` with the values supplied by the caller. The
preparation behaviour in that file belongs to a later post.

The invalid-geometry case uses Catch2 sections to share one valid starting mesh:

```cpp
TEST_CASE("Asset validation rejects incomplete geometry")
{
    RenderAssets assets;
    Mesh mesh = makeTriangle();

    SECTION("empty vertices")
    {
        mesh.vertices.clear();
    }
    SECTION("empty indices")
    {
        mesh.indices.clear();
    }
    SECTION("incomplete triangle")
    {
        mesh.indices.pop_back();
    }
    SECTION("out-of-range index")
    {
        mesh.indices.back() = 3;
    }

    static_cast<void>(assets.addMesh(std::move(mesh)));
    REQUIRE_THROWS_AS(fire_engine::detail::validateAssets(assets), std::invalid_argument);
}
```

Each section begins again with a complete triangle, changes one condition, and
expects the same public failure category. No driver state can make one branch
pass on one machine and fail on another.

## Run the asset tests

Clone, configure, build, and run release 0.7 as described in the
[first 0.7 post][testing-post]. During focused asset work, CTest can select the
five directly relevant cases by name:

```shell
ctest --preset default -R "Asset validation|Color4"
```

The filter leaves scene traversal, maths, render-preparation behaviour,
swapchain policy, SPIR-V loading, and the Vulkan smoke test out of this focused
run without changing their registration.

## Diagnose the new failure boundaries

The asset model moves several mistakes earlier than Vulkan allocation, but the
error still needs to be read at the right layer.

### A render object reports a missing mesh or material

Check both `valid()` and the owning collection. A default ID contains the
invalid sentinel; a non-default ID can still be out of range if it came from a
different `RenderAssets` instance or was constructed manually.

### A mesh reports incomplete indexed triangles

The index vector must be non-empty and its length must be divisible by three.
Release 0.7 supports triangle lists only, so lines, strips, fans, and partially
specified triangles are outside this asset contract.

### A mesh index refers beyond its vertex array

Every index must be less than `vertices.size()`. An index names a vertex; it is
not a byte offset or a position in the index vector.

### A material base colour must be finite

Check every RGBA component for NaN or infinity before adding imported data.
Finite values are not clamped to zero-to-one in 0.7, leaving high-dynamic-range
factors possible while rejecting values that would poison later arithmetic.

### An asset changed without its revision changing

Use the owning mutation operations rather than modifying collection elements in
place. The accessors intentionally return const vectors so every supported
description change can update the revision observed by preparation.

### Vulkan types appear in a loader or scene header

The dependency boundary has been crossed in the wrong direction. Loaders and
scenes should produce or reference the CPU descriptions; the renderer should be
the component that compiles them into API-specific resources.

### The CPU vertex looks correct but the shader reads corrupt attributes

Check all three versions of the contract together: `Vertex` member order and
size, the Vulkan attribute formats and offsets, and the Slang input locations
and widths. The pipeline's static assertions catch padding changes, but they
cannot detect a manually mismatched shader location.

## What this part of release 0.7 gives us

The first two 0.7 posts established testability and maths. This third part moves
render content out of the Vulkan implementation:

- `Color4` gives linear RGBA values colour-domain names and representation
  checks;
- `Vertex` contains a three-dimensional object-space position and RGBA colour;
- `Mesh` owns vertices and 32-bit triangle-list indices;
- `Material` begins with one unlit base-colour factor;
- `RenderObject` connects one reusable mesh and material;
- `MeshId`, `MaterialId`, and `RenderObjectId` prevent unrelated dense indices
  from being mixed;
- default IDs have an explicit invalid sentinel while index zero remains valid;
- `RenderAssets` owns separate dense collections and their ID spaces;
- const collection access prevents mutation from bypassing revision tracking;
- every supported insertion advances the asset revision;
- validation rejects empty or incomplete geometry, out-of-range indices,
  non-finite colours, and missing relationships;
- the application constructs the triangle through a public Vulkan-free API;
- the pipeline consumes that public vertex layout without moving Vulkan
  metadata into it;
- material colour multiplies vertex colour before interpolation; and
- five focused Catch2 cases verify the asset-domain contract without a device.

The catalogue still does not decide which assets a scene currently needs, and
it does not allocate their GPU representations. The next 0.7 post can build the
first scene graph: a Vulkan-free hierarchy of nodes that instances these render
objects and produces current world transforms in stable traversal order.

## Recommended reading

- [C++ Software Design][reading-cpp-software-design] — a guide to dependency
  direction, type-safe interfaces, and keeping implementation choices behind
  coherent architectural boundaries.
- [Game Engine Architecture][reading-game-engine-architecture] — Jason
  Gregory's treatment of resource management, handles, and the boundary between
  application-owned asset descriptions and their runtime representations.
- [Real-Time Rendering][reading-real-time-rendering] — the classic rendering
  reference for how vertices, indexed geometry, materials, transforms, and the
  graphics pipeline fit together.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[maths-post]: {% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %}
[source-color4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/color4.hpp>
[source-vertex]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/vertex.hpp>
[source-mesh]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/mesh.hpp>
[source-material]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/material.hpp>
[source-render-object]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/render_object.hpp>
[source-render-ids]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/render_ids.hpp>
[source-render-assets]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/render_assets.hpp>
[source-render-assets-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/graphics/render_assets.cpp>
[source-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/graphics/asset_validation.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/main.cpp>
[source-pipeline]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/render/pipeline.cpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/shaders/triangle.slang>
[source-test-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/graphics/test_asset_validation.cpp>
[source-test-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/graphics/test_render_preparation.cpp>
[reading-cpp-software-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-game-engine-architecture]: <https://www.gameenginebook.com/>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-page]: {% link _tabs/reading.md %}
