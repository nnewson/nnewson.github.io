---
title: "Extending fireEngine's descriptions without introducing Vulkan"
date: 2026-08-23 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, assets, textures, animation, scene-graph, architecture, gltf, cpp]
description: >-
  Add Vulkan-free image, texture, material, animation, and scene-component
  descriptions while preserving fireEngine's explicit preparation boundary.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
source_commit_url: "https://github.com/nnewson/fireEngine-tutorial/commit/658f2bfc61ab282075709d736eebb5672e324cfb"
previous_source_commit_url: "https://github.com/nnewson/fireEngine-tutorial/commit/d75c3d669fde4e5392be19b44b10a4e9d2062114"
---

The first release 0.8 implementation step gave fireEngine enough mathematical
and scene vocabulary for imported content. Nodes now retain decomposed
translation, rotation, and scale; quaternions can be normalised and
interpolated; and stable scene-local IDs give future animation a target that
survives traversal.

The next step has to describe what a textured, animated scene contains without
prematurely deciding how Vulkan will represent it. Decoded pixels are not yet a
`VkImage`. Filtering and wrapping policy are not yet a `VkSampler`. A material's
base-colour texture is not yet a descriptor set. An animation curve is neither
a scene node nor a per-frame command.

This checkpoint extends the CPU-owned side of the architecture with those
distinctions. `RenderAssets` gains images and textures, preparation follows
their transitive relationships, reusable animation channels remain separate
from node-local playback state, and each scene node receives one explicit
component role.

The rendered subject does not change. The tutorial still draws its coloured
triangle, the shader still ignores the new texture coordinate, and there is no
glTF loader or animation playback yet. That is deliberate: this part defines
and tests the descriptions that later loader and renderer work will consume.

This is the second detailed post based on release 0.8. The
[architectural overview][planning-post] describes the complete path to
AnimatedCube, while the [previous walkthrough][transform-post] covers the
transform and identity vocabulary on which this step builds.

> Starting point: [TRS transforms and stable node identities][previous-source-commit]
>
> Source checkpoint: [Add composable animation and texture asset descriptions][source-commit]
>
> Release destination: [fireEngine 0.8][release-0-8]
>
> This walkthrough stays at the second non-merge commit after
> [fireEngine 0.7][release-0-7]. It adds descriptions and validation, but does
> not include the later glTF loader, texture upload, or animation playback.
{: .prompt-info }

## Grow the description side of the boundary

Release 0.7 already separated reusable render descriptions from scene
instances and renderer-owned Vulkan resources. This checkpoint grows that
model in two directions:

<!-- align: ignore R1 -->
```text
RenderAssets                         animations
├── Mesh                             └── Animation
├── ImageData                            └── AnimationChannel
├── Texture                                  ├── timestamps
├── Material                                 └── quaternion values
└── RenderObject
        ^                                      ^
        |                                      |
        +---- RenderObjectId   Animator -------+
                    \           /
                     SceneComponent
                           |
                       SceneNode
```

The asset catalogue owns durable rendering descriptions. Animations remain an
external reusable collection until a later format-neutral `SceneContent` type
groups them with the assets and scene. A scene node stores either a renderable
reference, an animation binding, or no component at all.

None of these public types includes a Vulkan header. They can be created by a
procedural builder, populated by a future importer, validated in unit tests,
and inspected without a window or graphics device.

The main new and changed files are:

```text
include/fire_engine/
├── animation/
│   ├── animation.hpp
│   ├── animation_ids.hpp
│   └── detail/animation_validation.hpp
├── graphics/
│   ├── image_data.hpp
│   ├── material.hpp
│   ├── render_assets.hpp
│   ├── render_ids.hpp
│   ├── render_preparation.hpp
│   ├── texture.hpp
│   └── vertex.hpp
└── scene/
    ├── animator.hpp
    ├── components.hpp
    └── scene_node.hpp

src/
├── animation/animation_validation.cpp
├── graphics/
│   ├── asset_validation.cpp
│   ├── render_assets.cpp
│   └── render_preparation.cpp
└── scene/scene_node.cpp

tests/
├── animation/test_animation_validation.cpp
├── graphics/
│   ├── test_asset_validation.cpp
│   └── test_render_preparation.cpp
└── scene/test_scene.cpp
```

## Keep decoded pixels separate from sampling policy

An image and a texture are related, but they are not the same resource.
`ImageData` owns decoded pixel content:

```cpp
struct ImageData
{
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<std::uint8_t> pixels;
};
```

The byte vector is tightly packed, row-major RGBA8. It does not retain a PNG
file, a decoder object, a Vulkan format, device memory, an image layout, or an
image view. Decoding will belong to the loader; compiling those bytes into a
sampled GPU image will belong to the renderer.

See [`image_data.hpp`][source-image-data].

A `Texture` adds the policy for reading an image:

```cpp
struct Texture
{
    ImageId image;
    TextureFilter minFilter = TextureFilter::eLinear;
    TextureFilter magFilter = TextureFilter::eLinear;
    TextureWrap wrapU = TextureWrap::eRepeat;
    TextureWrap wrapV = TextureWrap::eRepeat;
};
```

This separation allows two textures to share one decoded image while choosing
different sampling behaviour. The relationship is visible in the data rather
than being hidden inside a GPU object:

```text
Texture 0 -- linear + repeat ---------+
                                      >-- ImageData 0
Texture 1 -- nearest + clamp-to-edge -+
```

The engine enums describe only the choices required by the intended glTF
slice:

```cpp
enum class TextureFilter : std::uint8_t
{
    eNearest,
    eLinear,
};

enum class TextureWrap : std::uint8_t
{
    eRepeat,
    eMirroredRepeat,
    eClampToEdge,
};
```

They deliberately are not aliases for `VkFilter` or
`VkSamplerAddressMode`. A later compilation step will translate the engine's
meaning into Vulkan values. Mipmap selection, anisotropy, comparison sampling,
and border colours stay out of this checkpoint because no demonstrated content
requires them yet.

See [`texture.hpp`][source-texture].

## Extend materials and vertices at the same boundary

A texture becomes useful to a draw through its material. The existing unlit
material keeps its base-colour factor and gains one optional texture reference:

```cpp
struct Material
{
    Color4 baseColor{.r = 1.0f, .g = 1.0f, .b = 1.0f, .a = 1.0f};
    std::optional<TextureId> baseColorTexture;
};
```

The optional preserves the existing untextured path. Absence is part of the
description rather than a fabricated invalid texture ID or a renderer-owned
fallback leaking into application data. A later renderer step can compile both
cases into one descriptor layout using a neutral white texture.

The vertex description gains the `Vec2` introduced by the previous checkpoint:

```cpp
struct Vertex
{
    Vec3 position;
    Color4 color;
    Vec2 textureCoordinate;
};
```

The attribute exists before the pipeline consumes it. The static layout check
is updated from seven floats to nine, but the current Vulkan attribute list and
shader still read only position and colour. The triangle supplies zero texture
coordinates and its material supplies no texture, so the visual integration
path keeps the same meaning.

This is a useful sequencing property. The public description can settle before
image allocation, descriptors, shader sampling, and synchronization arrive in
one much larger renderer change.

See [`material.hpp`][source-material], [`vertex.hpp`][source-vertex], and the
current [`pipeline.cpp`][source-pipeline].

## Give images and textures distinct typed identities

The dense typed-ID pattern already used for meshes, materials, render objects,
and scene nodes now covers the new asset kinds:

```cpp
struct ImageId
{
    std::size_t value = std::numeric_limits<std::size_t>::max();

    [[nodiscard]] constexpr bool valid() const noexcept
    {
        return value != std::numeric_limits<std::size_t>::max();
    }

    [[nodiscard]] constexpr bool operator==(const ImageId&) const noexcept = default;
};

struct TextureId
{
    std::size_t value = std::numeric_limits<std::size_t>::max();

    [[nodiscard]] constexpr bool valid() const noexcept
    {
        return value != std::numeric_limits<std::size_t>::max();
    }

    [[nodiscard]] constexpr bool operator==(const TextureId&) const noexcept = default;
};
```

Both wrap a `std::size_t`, but the types are intentionally incompatible. An
`ImageId` cannot accidentally be supplied where a `TextureId` is expected, and
neither can be confused with a `MaterialId` simply because all three happen to
address dense vectors.

Default construction retains the invalid sentinel used by the earlier IDs.
Validation therefore distinguishes an unassigned reference from a valid dense
index, then checks that assigned indices are within their owning collection.

See [`render_ids.hpp`][source-render-ids].

## Let one catalogue own the complete render graph

`RenderAssets` remains the owner of reusable render descriptions. Its shape now
matches the dependency graph needed by a textured draw:

```text
RenderObject
├── Mesh
└── Material
    └── optional Texture
        └── ImageData
```

The collection adds insertion operations and const views for images and
textures alongside the existing mesh, material, and render-object operations:

```cpp
[[nodiscard]] ImageId addImage(ImageData image);
[[nodiscard]] TextureId addTexture(Texture texture);

[[nodiscard]] const std::vector<ImageData>& images() const noexcept;
[[nodiscard]] const std::vector<Texture>& textures() const noexcept;
```

Every insertion advances the same asset revision. Images and textures may not
be compiled by the renderer at this checkpoint, but changing the catalogue is
already visible to `RenderPreparation`. Move construction and move assignment
also transfer the new collections while changing the moved-from object's
revision so an existing address-and-revision cache cannot mistake moved state
for unchanged input.

The ownership rule remains simple: an ID is meaningful only with the
`RenderAssets` instance that assigned it. It is a typed local handle, not a
globally unique asset identifier.

See [`render_assets.hpp`][source-render-assets] and
[`render_assets.cpp`][source-render-assets-cpp].

## Validate complete relationships before GPU work

The existing asset validator grows from geometry and render-object checks into
a complete catalogue check. Images are validated first:

```cpp
if (image.width == 0 || image.height == 0)
{
    throw std::invalid_argument("A decoded image must have a non-zero extent");
}

constexpr std::size_t kRgbaChannelCount = 4;
const std::size_t width = image.width;
const std::size_t height = image.height;
if (width > std::numeric_limits<std::size_t>::max() / height / kRgbaChannelCount ||
    image.pixels.size() != width * height * kRgbaChannelCount)
{
    throw std::invalid_argument(
        "A decoded image must contain tightly packed RGBA8 pixels");
}
```

The overflow check happens before multiplying the dimensions. A malformed or
hostile extent cannot wrap the expected byte count into a smaller value and
make an unrelated pixel vector appear valid.

The validator then checks each relationship in owning-container order:

- every texture refers to an assigned, in-range image;
- every mesh contains vertices and complete indexed triangles;
- every index addresses the mesh's vertex vector;
- every material factor contains finite red, green, blue, and alpha values;
- every present base-colour texture ID is assigned and in range; and
- every render object refers to an existing mesh and material.

Colour components are required to be finite, but they are not clamped to the
zero-to-one interval here. The engine-level description preserves the supplied
factor; format-specific rules can be applied at the loader boundary when that
boundary exists.

Validation still covers the complete catalogue before preparation selects a
visible subset. An unused malformed image is not allowed to remain dormant
until some later scene happens to reference it. `RenderAssets` represents one
valid graph, not a bag whose invalid regions become acceptable when unseen.

See [`asset_validation.cpp`][source-asset-validation].

## Follow transitive dependencies during preparation

Release 0.7 preparation selected the distinct meshes and materials reachable
from the scene's ordered render-object dependencies. Textures add two more
edges that must be followed:

```text
SceneDrawList
    |
    v
RenderObjectId
    |
    +--> MeshId
    |
    +--> MaterialId
             |
             +--> optional TextureId
                         |
                         +--> ImageId
```

`RenderPreparationPlan` now names every selected resource category:

```cpp
struct RenderPreparationPlan
{
    std::vector<MeshId> meshes;
    std::vector<ImageId> images;
    std::vector<TextureId> textures;
    std::vector<MaterialId> materials;
    std::vector<PreparedRenderObject> renderObjects;
    std::size_t assetRevision = 0;
    std::size_t dependencyHash = 0;
};
```

Compilation begins with a boolean selection vector for each owning collection.
Used render objects mark their meshes and materials. Used materials mark their
optional textures, and used textures finally mark their images. Each vector is
then scanned in dense ID order to produce a deterministic, duplicate-free
plan.

That means two selected materials can use different `TextureId` values that
share one `ImageId`. Both sampling descriptions appear in `plan.textures`, but
the decoded pixels appear once in `plan.images`. Unused images and textures do
not enter the plan at all.

The renderer does not compile these two new lists yet. Their presence makes the
preparation contract complete before the later Vulkan texture step consumes
it, just as the CPU asset types arrived before their device representation.

See [`render_preparation.hpp`][source-render-preparation] and
[`render_preparation.cpp`][source-render-preparation-cpp].

## Preserve the transform-independent cache key

Adding transitive resources does not change what makes a preparation plan
stable. Its cache key remains:

```text
RenderAssets identity
        +
asset revision
        +
ordered RenderObjectId dependencies
```

The draw-list dependency hash remains a fast summary rather than the sole
authority; the exact ordered render-object sequence still protects against a
hash collision. Texture and image IDs do not need to be repeated in the cache
key because they are reached through the validated asset graph represented by
the collection identity and revision.

A transform-only change leaves every part of this key unchanged. Later
animation playback can replace a node's local rotation, resolve new world
matrices, and submit different per-draw transforms while reusing the same
prepared image, texture, mesh, material, and render-object resources.

Adding even an unused image or texture does advance the asset revision and
causes a rebuild. That is consistent with complete-catalogue validation: the
input version has changed and must become the new validated version before its
selected subset can be trusted.

## Describe reusable animation channels without scene targets

Animation enters the model as sampled data rather than behaviour embedded in a
node:

```cpp
struct AnimationChannel
{
    std::vector<float> timestamps;
    std::vector<Quaternion> values;
};

struct Animation
{
    std::string name;
    std::vector<AnimationChannel> channels;
};
```

An animation owns a stable ordered collection of channels and an optional
diagnostic name. Each channel contains strictly increasing times in seconds and
one quaternion value for each time. The checkpoint intentionally supports only
linear rotation data; translation, scale, morph weights, cubic splines, and
step interpolation need different value or interpolation contracts and remain
outside the selected vertical slice.

The important omission is a target node. One curve can be reused by more than
one scene binding, and animation descriptions can exist before a scene has
been composed. Keeping `SceneNodeId` out of `AnimationChannel` prevents imported
sample data from owning runtime scene identity.

`AnimationId` addresses one externally owned animation, while
`AnimationChannelId` addresses a channel within it. They repeat the same typed,
dense, locally scoped identity pattern as render assets.

See [`animation.hpp`][source-animation] and
[`animation_ids.hpp`][source-animation-ids].

## Bind playback state at the scene node

An `Animator` connects reusable curve data to one node-local transform property:

```cpp
enum class AnimationTargetPath : std::uint8_t
{
    eRotation,
};

struct Animator
{
    AnimationId animation;
    AnimationChannelId channel;
    AnimationTargetPath targetPath = AnimationTargetPath::eRotation;
    float playbackTime = 0.0f;
    bool looping = true;
};
```

The binding identifies its source animation and channel, records which local
property will be driven, and owns its playback state. Two animators can refer
to the same channel while holding different times or looping choices. The
sample values stay shared; runtime state belongs to each use.

There is still no sampling operation in this checkpoint. `playbackTime` does
not advance, timestamps are not searched, and no quaternion is written to a
node's `Transform`. Defining the binding first lets later playback depend on a
small validated contract instead of inventing animation ownership during the
frame loop.

See [`animator.hpp`][source-animator].

## Give every scene node one explicit component role

Before this change, a scene node stored an optional `RenderObjectId`. That
answers whether the node emits a draw, but it cannot express a transform-only
hierarchy node or an animation behaviour as equally deliberate alternatives.

`SceneComponent` makes those roles explicit:

```cpp
using SceneComponent =
    std::variant<std::monostate, Animator, RenderObjectId>;
```

The three alternatives mean:

- `std::monostate` is a transform-only hierarchy node;
- `Animator` will drive one local transform property; and
- `RenderObjectId` emits a draw item during traversal.

Default construction selects `std::monostate`, so an ordinary grouping node
requires no special marker. `SceneNode::component()` exposes the current value,
and its setter replaces the complete role.

Draw-list construction asks whether the component currently holds a render
object:

```cpp
const RenderObjectId* renderObject = std::get_if<RenderObjectId>(&component_);
if (renderObject != nullptr)
{
    output.push_back({.renderObject = *renderObject, .world = worldTransform_});
}
```

Regardless of its own role, the node then visits every child. Animator and
transform-only nodes therefore contribute hierarchy without producing empty or
invalid draw items.

See [`components.hpp`][source-components],
[`scene_node.hpp`][source-scene-node], and
[`scene_node.cpp`][source-scene-node-cpp].

## Compose animation and rendering through hierarchy

One component per node creates a small, predictable composition rule. A source
node that both animates and contains a renderable mesh becomes a parent-child
pair:

```text
source node transform -> Animator
└── primitive child   -> RenderObjectId
```

The animator changes the parent's local rotation. Normal scene traversal then
propagates its resolved world matrix to the renderable child. The draw list
contains the child once, with the inherited animated transform, while the
animation node itself remains absent from render dependencies.

This shape also handles a glTF mesh with several primitives:

```text
animated source node -> Animator
├── primitive 0 -> RenderObjectId 4
├── primitive 1 -> RenderObjectId 5
└── primitive 2 -> RenderObjectId 6
```

One animation binding affects every primitive through the existing hierarchy,
and each primitive can retain its own mesh/material relationship. The loader
that creates this structure arrives later; this checkpoint proves that the
scene representation can already express it.

The trade-off is intentionally narrow. A node cannot directly hold several
behaviours or several animation channels. The selected AnimatedCube path needs
one rotation animator and renderable children, so a general component container
would add policy before a concrete use case requires it.

## Validate curves separately from bindings

Animation validity has two layers. The internal
`detail::validateAnimation()` helper checks reusable curve data without needing
a scene:

- a channel contains at least one sample;
- timestamp and value counts match;
- every timestamp is finite and non-negative;
- timestamps are strictly increasing; and
- every quaternion is finite and non-zero, and can therefore be normalised.

The validator does not require stored quaternion samples to have unit length.
It requires them to be normalisable, allowing the later interpolation operation
to produce a unit result through the robust quaternion contract introduced in
the previous step.

`detail::validateAnimationBindings()` composes those animations with a scene.
It first validates every reusable animation, then walks every root and
descendant. Each `Animator` must name an existing animation and channel, use the
supported rotation target, and hold a finite, non-negative playback time.

```cpp
namespace fire_engine::detail
{
void validateAnimationBindings(const Scene& scene,
                               std::span<const Animation> animations);
}
```

The `std::span` makes external ownership explicit: validation observes a
contiguous animation collection but neither copies nor owns it. Both validation
functions live under `animation/detail/` and are marked as internal rather than
supported application API. They perform setup-time composition work for later
engine stages and focused tests. Frame updates should consume an already trusted
binding set rather than repeat the full curve validation and scene traversal for
every sample.

See [`animation_validation.hpp`][source-animation-validation] and
[`animation_validation.cpp`][source-animation-validation-cpp].

## Keep implementation helpers visibly internal

The checkpoint also moves existing debug, hash, and logging support beneath
`core/detail/` and places the debug helpers in `fire_engine::detail`. This does
not change the triangle or the new description model, but it corrects a public
header boundary exposed by the growing include tree.

`log()` remains public; its `LogMessage` implementation helper moves to
`core/detail/log_message.hpp`. Scene hashing includes the internal hash
constants from `core/detail/hash.hpp`, and device setup includes the internal
debug declarations from `core/detail/debug.hpp`.

That small cleanup prepares for the next release 0.8 checkpoint, which makes
the renderer's public/internal boundary systematic. Here it ensures the new
public description headers do not suggest that unrelated implementation helpers
are supported engine API. Animation validation follows the same rule beneath
`animation/detail/`.

## Preserve the procedural triangle

The application migrates to the new descriptions without pretending to use
features that are not implemented yet. Each vertex receives an empty texture
coordinate, and the material explicitly contains no base-colour texture:

```cpp
fire_engine::Vertex{
    .position = {.x = 0.0f, .y = -0.6f, .z = 0.0f},
    .color = {.r = 1.0f, .g = 0.2f, .b = 0.1f, .a = 1.0f},
    .textureCoordinate = {},
};

const fire_engine::MaterialId material = content.assets.addMaterial({
    .baseColor = {.r = 0.9f, .g = 0.95f, .b = 1.0f, .a = 1.0f},
    .baseColorTexture = std::nullopt,
});
```

The scene node now receives its render role through `component()` rather than
an optional render-object setter:

```cpp
node.component(triangle);
```

Those are structural migrations, not visual changes. `Renderer::prepare()`
still validates and compiles the triangle's mesh and material, while
`drawFrame()` consumes the scene's current draw items exactly as before.

See the checkpoint's [`main.cpp`][source-main].

## Test descriptions and composition without a device

The device-free Catch2 count rises from 29 to 38. Nine new cases cover the
contracts introduced by this checkpoint.

Asset tests reject zero image extents, incorrect RGBA8 byte counts, invalid and
out-of-range image references, and invalid and out-of-range material texture
references. A valid one-pixel image, texture, and material proves the complete
relationship.

Preparation tests build two materials and two textures over one shared image:

```cpp
REQUIRE(plan.images == std::vector{image});
REQUIRE(plan.textures == std::vector{firstTexture, secondTexture});
REQUIRE(plan.materials == std::vector{firstMaterial, secondMaterial});
```

That fixes both deduplication and stable ID ordering. A separate case proves
that adding an image or texture advances the asset revision and invalidates the
cached plan, while the existing transform test continues to prove that moving
a scene node does not.

Four animation cases distinguish valid reusable channels from malformed
timelines, and valid shared bindings from dangling animation or channel IDs,
invalid playback time, and unsupported target paths.

The scene-component case builds two animator parents that share one animation
channel, gives each a renderable child, and adds a transform-only root. Only the
children enter the draw list, and the first child's world transform inherits
its animator parent's translation.

See [`test_asset_validation.cpp`][source-test-assets],
[`test_render_preparation.cpp`][source-test-preparation],
[`test_animation_validation.cpp`][source-test-animation], and
[`test_scene.cpp`][source-test-scene].

## Run the description and composition tests

Configure and build the source checkpoint through the vcpkg preset, then ask
CTest for the nine new cases by anchored prefix:

```shell
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default -R "^(Asset validation rejects malformed images|Asset validation rejects missing texture resources|Render preparation extracts shared image and texture dependencies|Image and texture additions invalidate render preparation|Animation validation accepts|Animation validation rejects|Animation binding validation accepts|Animation binding validation rejects|Scene components separate)"
```

The remaining maths, scene, asset, preparation, swapchain, and SPIR-V tests,
plus the Vulkan smoke test, remain outside this focused run. Running the full
CTest preset verifies that the wider triangle path still behaves as it did at
the previous checkpoint.

## Diagnose the new failure boundaries

The new descriptions make several errors visible before a loader or renderer
can hide them behind format or graphics-API diagnostics.

### A decoded image fails validation

Check that both dimensions are non-zero and that the byte vector contains
exactly `width * height * 4` bytes. `ImageData` is decoded RGBA8, not a PNG file
or an arbitrary channel layout. Very large extents are rejected if their byte
count would overflow `std::size_t`.

### A texture reports a missing image

An `ImageId` is local to its owning `RenderAssets`. Confirm that it identifies
an image in the same collection rather than an index from another catalogue.
It only needs to be assigned and in range when validation runs; insertion order
is not part of the check.

### A material reports a missing base-colour texture

Use `std::nullopt` for an untextured material. A present `TextureId` promises a
real entry and must be assigned and in range. The invalid default sentinel is
not another spelling of absence once it is placed inside the optional.

### A required image is absent from the preparation plan

Trace the complete relationship from a scene draw to its render object,
material, optional texture, and image. Preparation intentionally excludes
unreachable resources; simply adding an image or texture to the catalogue does
not make it part of the selected plan.

### Preparation rebuilds after only a transform change

Animation and ordinary movement should change `Transform` and resolved world
matrices without changing the asset catalogue or ordered `RenderObjectId`
sequence. Check for accidental asset insertion or component replacement in the
update path.

### An animation timeline is rejected

Check for empty channels, unequal timestamp and value counts, negative or
non-finite times, duplicate timestamps, or decreasing order. Each pair of
neighbouring times must advance strictly so later sampling always has a
well-defined interval.

### A rotation sample is rejected even though its components are finite

The all-zero quaternion is finite but cannot represent a rotation or be
normalised. Supply a non-zero quaternion. Samples need not arrive at exact unit
length, but each must pass the robust normalisation operation.

### An animator node produces no draw item

That is the component contract. `Animator` is behaviour, not geometry. Put the
`RenderObjectId` on a child node so the child's world transform inherits the
animated parent transform.

### Animation validation appears in the frame loop

`detail::validateAnimationBindings()` is internal setup machinery that checks
every curve and traverses the entire scene. Keep it at the engine's content
composition boundary and let playback consume the resulting trusted state. It
is not supported application API or intended as per-frame defensive work.

## What this part of release 0.8 gives us

The second implementation checkpoint extends fireEngine's source-side model
without crossing its Vulkan boundary:

- `ImageData` owns tightly packed decoded RGBA8 pixels and explicit dimensions;
- image content remains separate from texture sampling behaviour;
- engine-level filter and wrap enums avoid exposing Vulkan sampler values;
- `ImageId` and `TextureId` extend the typed dense-handle pattern;
- materials gain an optional base-colour texture without losing the untextured
  path;
- vertices gain one texture-coordinate pair before the shader consumes it;
- `RenderAssets` owns images and textures beside meshes, materials, and render
  objects;
- all asset insertions participate in the existing revision contract;
- validation rejects malformed images and dangling texture relationships before
  GPU work;
- preparation computes the transitive render-object-to-image dependency closure;
- shared images are selected once even when several textures use them;
- unused images and textures remain outside the preparation plan;
- transform-only changes continue to reuse stable prepared resources;
- `Animation` and `AnimationChannel` describe reusable rotation samples without
  naming scene nodes;
- animation and channel IDs keep external and animation-local identity distinct;
- `Animator` owns one binding's target path, playback time, and looping state;
- `SceneComponent` makes transform-only, animator, and renderable roles explicit;
- hierarchy composes one animated source node with one or more renderable
  primitive children;
- curve validation remains separate from scene-binding validation;
- core implementation helpers move beneath a visible `detail/` boundary;
- nine new device-free cases bring the checkpoint total to 38; and
- the procedural triangle preserves the previous runtime behaviour through the
  expanded descriptions.

There is still no file format, decoded PNG loader, GPU image, sampler,
descriptor, texture-sampling shader, or playback loop. The next architectural
checkpoint tightens the renderer's public/internal boundary; the later loader
and compilation steps can then consume these descriptions without making glTF
or Vulkan their owner.

## Recommended reading

- [Game Engine Architecture][reading-game-engine-architecture] — Jason
  Gregory's broad treatment of resource ownership, animation systems, scene
  representation, handles, and the boundary between source and runtime data.
- [glTF 2.0 specification: Textures][reading-gltf-textures] — the Khronos
  definitions of images, samplers, textures, and texture coordinates that
  inform this deliberately narrow model.
- [glTF 2.0 specification: Animations][reading-gltf-animations] — the source
  format's separation of samplers, channels, target nodes, target paths, input
  times, and output values.
- [C++ `std::variant`][reading-cpp-variant] — cppreference's description of the
  type-safe discriminated union used to make a scene node's single component
  role explicit.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[source-commit]: {{ page.source_commit_url }}
[previous-source-commit]: {{ page.previous_source_commit_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[transform-post]: {% post_url 2026-08-22-giving-fireengine-imported-transforms-enough-vocabulary %}
[source-image-data]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/image_data.hpp>
[source-texture]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/texture.hpp>
[source-material]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/material.hpp>
[source-vertex]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/vertex.hpp>
[source-pipeline]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/render/pipeline.cpp>
[source-render-ids]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/render_ids.hpp>
[source-render-assets]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/render_assets.hpp>
[source-render-assets-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/graphics/render_assets.cpp>
[source-asset-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/graphics/asset_validation.cpp>
[source-render-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/graphics/render_preparation.hpp>
[source-render-preparation-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/graphics/render_preparation.cpp>
[source-animation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/animation/animation.hpp>
[source-animation-ids]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/animation/animation_ids.hpp>
[source-animator]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/scene/animator.hpp>
[source-components]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/scene/components.hpp>
[source-scene-node]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/scene/scene_node.hpp>
[source-scene-node-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/scene/scene_node.cpp>
[source-animation-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/include/fire_engine/animation/detail/animation_validation.hpp>
[source-animation-validation-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/animation/animation_validation.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/src/main.cpp>
[source-test-assets]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/tests/graphics/test_asset_validation.cpp>
[source-test-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/tests/graphics/test_render_preparation.cpp>
[source-test-animation]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/tests/animation/test_animation_validation.cpp>
[source-test-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/658f2bfc61ab282075709d736eebb5672e324cfb/tests/scene/test_scene.cpp>
[reading-game-engine-architecture]: <https://www.gameenginebook.com/>
[reading-gltf-textures]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#textures>
[reading-gltf-animations]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations>
[reading-cpp-variant]: <https://en.cppreference.com/w/cpp/utility/variant.html>
[reading-page]: {% link _tabs/reading.md %}
