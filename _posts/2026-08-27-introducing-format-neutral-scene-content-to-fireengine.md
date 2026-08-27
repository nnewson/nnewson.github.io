---
title: "Introducing format-neutral scene content to fireEngine"
date: 2026-08-27 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, gltf, assets, animation, scene-graph, architecture, cpp]
description: >-
  Compose fireEngine's Vulkan-free scene data and import a deliberately narrow
  glTF slice without leaking the source format into the engine model.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.8 gives fireEngine Vulkan-free vocabulary for textured and animated
content. Images, textures, materials, meshes, animations, and scene components
remain useful independently, but imported content needs them to travel as one
validated result.

`SceneContent` supplies that coherent content boundary. It groups the render
assets, hierarchy, and reusable animations that describe a scene. `GltfLoader`
translates a deliberately small glTF 2.0 subset into that engine-owned result,
validates the composition, and then discards all parser-specific state.

The completed release loads AnimatedCube through this path, advances its
rotation animation, and renders it with a sampled base-colour texture. This
article concentrates on where source-format knowledge ends: producing
`SceneContent`. GPU compilation, playback, and drawing remain downstream
consumers of the returned data.

This is the third detailed post based on release 0.8. The
[architectural overview][planning-post] describes the complete path, while the
[previous walkthrough][descriptions-post] defines the descriptions consumed
here.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> The [previous walkthrough][descriptions-post] covers the descriptions grouped
> here. This one concentrates on the format-neutral composition and constrained
> glTF loading path present in version 0.8.
{: .prompt-info }

## Give every content producer the same destination

The loader needs to return more than a mesh, but it should not return a glTF
document. `SceneContent` supplies the missing composition:

```cpp
struct SceneContent
{
    RenderAssets assets;
    Scene scene;
    std::vector<Animation> animations;
};
```

The type owns three related domains:

| Member | Owns | References from the composition |
| --- | --- | --- |
| `assets` | images, textures, meshes, materials, and render objects | scene render components use `RenderObjectId` |
| `scene` | roots, hierarchy, transforms, and components | animator components use animation and channel IDs |
| `animations` | reusable names, timelines, and quaternion samples | animator components bind them to nodes |

The important word is not *glTF* but *content*. A procedural builder, editor,
different importer, or future cache reader can all produce this shape:

```text
procedural builder ----+
glTF loader -----------+--> SceneContent --> Renderer::prepare(...)
future cached format --+          |
                                  +--> animation playback
```

Nothing in `SceneContent` names a parser, file, buffer view, accessor, decoder,
Vulkan image, or descriptor. The long-lived engine model describes meaning;
the producer owns the mechanics needed to construct it.

The application receives the same type directly from the loader, then passes
its format-neutral members to the renderer:

```cpp
fire_engine::SceneContent content = fire_engine::GltfLoader{}.load(
    std::filesystem::path{FIRE_ENGINE_ASSET_DIRECTORY} /
    "AnimatedCube" / "AnimatedCube.gltf");

renderer.prepare(content.assets, content.scene);
```

Procedural builders can produce the same `SceneContent` without emulating a
glTF document. That is what makes the composition an engine type rather than a
loader result in disguise.

See [`scene_content.hpp`][source-scene-content] and the updated
[`main.cpp`][source-main].

## Keep the importer on one side of the public operation

The complete public loader interface is intentionally small:

```cpp
class GltfLoader final
{
public:
    [[nodiscard]] SceneContent load(const std::filesystem::path& path) const;
};
```

Its header includes `scene_content.hpp`, not fastgltf or stb. Both third-party
libraries are private implementation dependencies of the engine target:

```text
application
    |
    v
GltfLoader::load(path)                    public, format-specific entry
    |
    +--> fastgltf                         private parsing and accessor traversal
    +--> stb_image                        private image decoding
    |
    v
SceneContent                              public, format-neutral result
```

That distinction prevents parser types from spreading into scene traversal,
animation playback, preparation, or rendering. Changing the parser should
change the implementation of `GltfLoader`, not every consumer of imported
content.

The build reflects the same rule. `fastgltf::fastgltf` is a private link
dependency and the stb include directory is private. Neither library appears
in the engine's public header surface.

See [`gltf_loader.hpp`][source-gltf-loader] and the relevant
[`CMakeLists.txt` changes][source-cmake].

## Make the translation stages explicit

`GltfLoader::load()` is mostly orchestration. Each stage translates one source
domain into the corresponding engine-owned domain:

```cpp
fastgltf::Asset source = parseAsset(path);
SceneContent result;

loadImages(source, path.parent_path(), result.assets);
loadTextures(source, result.assets);
const std::vector<MaterialId> materials = loadMaterials(source, result.assets);
const MeshRenderObjects meshes = loadMeshes(source, materials, result.assets);
const std::vector<std::optional<NodeAnimationBinding>> animationBindings =
    loadAnimations(source, result.animations);
loadScene(source, meshes, animationBindings, result.scene);
result.scene.updateWorldTransforms();
detail::validateSceneContent(result);
return result;
```

The order follows the references being constructed:

```text
glTF document
    │
    ├─ images ─> textures ─> materials ──┐
    │                                    ├─> RenderAssets ─────────────┐
    ├─ accessors ─> meshes ─> primitives ┘                             │
    │                                                                  │
    ├─ animation samplers ─> channels ───┬─> animations ───────────────┤
    │                                    │                             │
    │                                    └─> node bindings ┐           │
    │                                                      ├─> Scene ──┤
    └─ selected scene ─> nodes ────────────────────────────┘           │
                                                                       │
    ┌──────────────────────────────────────────────────────────────────┘
    v
    update world transforms, then validateSceneContent()
    │
    v
    SceneContent
```

Two details are worth reading off that shape. The animation stage has a single
source and two products: sampler data becomes reusable `AnimationChannel`
values, while the source channels also yield the per-node bindings. And `Scene`
is not produced by nodes alone — it is built from the selected hierarchy and
those bindings together.

One edge is left off to keep the picture legible. Node construction also
consumes the mesh translation table, because a node carrying a source mesh
gains one renderable child per primitive. That relationship has its own diagram
in the hierarchy section below.

Images are inserted in glTF image order, textures in texture order, and
materials in material order. The importer can therefore translate a validated
source array index directly into the corresponding dense engine ID. Meshes
need a richer mapping because one glTF mesh can contain several primitives;
each source mesh maps to a vector of engine `RenderObjectId` values.

The implementation imports the source asset tables before selecting a scene.
Only one scene hierarchy is instantiated, but unsupported data elsewhere in
those imported tables can still reject the file. The loader favours one
complete, predictable document conversion over importing only the assets
reachable from the chosen scene.

See the complete [`gltf_loader.cpp`][source-gltf-loader-cpp].

## Parse a deliberately constrained document

Parsing starts from a JSON `.gltf` path. `fastgltf::GltfDataBuffer::FromPath()`
owns the initial file read, then the parser loads external buffers and asks
fastgltf to decompose node matrices into translation, rotation, and scale:

```cpp
constexpr fastgltf::Options kOptions =
    fastgltf::Options::LoadExternalBuffers |
    fastgltf::Options::DecomposeNodeMatrices;

auto parsed = parser.loadGltf(file.get(), path.parent_path(), kOptions);
```

The document's directory is passed to the parser, so a relative buffer URI is
resolved beside the source document rather than against the application's
working directory.

The parser recognizes all extension grammars built into fastgltf, but release
0.8 accepts no required extension. Recognizing first and
rejecting second produces a specific error such as:

```text
Unsupported glTF data: required extension 'KHR_materials_transmission'
```

That is more useful than allowing a required semantic to disappear during
conversion. Optional information outside the selected slice can be ignored;
required information cannot.

Binary `.glb`, embedded resources, and broad extension support remain outside
the documented contract. The supported path is a JSON document with external
content committed beside it.

## Resolve and decode external images

Every imported image must use a local external URI. Remote URIs, embedded data,
and buffer-view images are rejected:

```cpp
const auto* uri = std::get_if<fastgltf::sources::URI>(&image.data);
if (uri == nullptr || !uri->uri.isLocalPath())
{
    unsupported("images must use external local files");
}
```

The image path is resolved relative to the `.gltf` file and passed to one
internal decoder. stb converts the source to four channels regardless of its
original channel count, then the importer copies the decoded bytes into the
engine's tightly packed `ImageData`:

```cpp
ImageData result{
    .width = static_cast<std::uint32_t>(width),
    .height = static_cast<std::uint32_t>(height),
    .pixels = std::vector<std::uint8_t>(decoded, decoded + byteCount),
};
```

The supported tutorial asset uses PNG. The implementation does not inspect the
filename extension, so stb will also decode formats such as JPEG and BMP. Those
formats are implementation side effects rather than part of the loader's
documented contract; only external PNG content is promised by release 0.8.

The decoder checks for failed loads, non-positive dimensions, and size
overflow before copying. Its raw allocation is released on both the invalid
dimension path and after a successful copy; the returned content owns ordinary
`std::vector` memory.

See [`image_decoder.hpp`][source-image-decoder] and
[`image_decoder.cpp`][source-image-decoder-cpp].

## Translate texture and material meaning

A glTF texture refers to an image and optionally a sampler. The loader maps
those values into the format-neutral types covered in the
[descriptions post][descriptions-post]:

```text
glTF image index ----------------------> ImageId

glTF sampler min/mag filters ---+
glTF sampler wrapS/wrapT -------+------> Texture
glTF texture source ------------+          |
                                           v
                                       TextureId

baseColorFactor ------------------------> Material::baseColor
baseColorTexture.index -----------------> Material::baseColorTexture
```

Nearest-family mip filters collapse to `TextureFilter::eNearest`; linear-family
mip filters collapse to `TextureFilter::eLinear`. fireEngine has no mip chain
yet, so retaining a distinction between the mip variants would promise a
behaviour the renderer cannot provide. Repeat, mirrored repeat, and
clamp-to-edge map directly into the three engine wrap choices.

When a texture has no sampler, or its sampler omits a filter, the engine's
linear filtering and repeat wrapping defaults apply. Invalid source indices
are reported before an engine ID is constructed.

Materials import the base-colour factor and optional base-colour texture. A
textured material must use `TEXCOORD_0`. Metallic-roughness values, normal
textures, occlusion, emissive data, alpha behaviour, and double-sided state do
not enter the 0.8 material description.

An unmaterialled primitive receives one lazily created default material shared
by every such primitive in the document. That keeps the engine asset graph
complete without inventing a source-format dependency in the renderer.

## Extract geometry through accessors, not byte assumptions

The supported primitive shape is intentionally exact:

- triangle-list mode;
- indexed geometry;
- `POSITION` as a non-sparse float `VEC3` accessor;
- `TEXCOORD_0` as a non-sparse float `VEC2` accessor;
- equal position and texture-coordinate counts; and
- non-sparse unsigned 16-bit or unsigned 32-bit scalar indices.

Both attributes are required even when a primitive's material is untextured.
This is a vertical slice for AnimatedCube, not a general mesh importer.

The loader does not calculate byte addresses itself. It asks fastgltf to
iterate each accessor:

```cpp
fastgltf::iterateAccessorWithIndex<fastgltf::math::fvec3>(
    source, positions,
    [&result](fastgltf::math::fvec3 value, std::size_t index)
    {
        result.vertices[index] = {
            .position = {.x = value[0], .y = value[1], .z = value[2]},
            .color = {.r = 1.0f, .g = 1.0f, .b = 1.0f, .a = 1.0f},
            .textureCoordinate = {},
        };
    });
```

That library operation honours accessor offsets, buffer-view offsets, and
interleaved byte strides. A second pass fills `TEXCOORD_0`. Imported vertex
colour starts at white so later shading can multiply the base-colour texture,
material factor, and vertex factor without tinting the asset accidentally.

Indices are converted into the engine's existing `std::uint32_t`
representation. Each value is also checked against the imported vertex count;
correct accessor metadata does not make an out-of-range index safe.

Every glTF primitive becomes a distinct engine `Mesh` and `RenderObject`, while
its selected material can remain shared:

```text
glTF mesh
├── primitive 0 --> MeshId 0 + MaterialId 0 --> RenderObjectId 0
└── primitive 1 --> MeshId 1 + MaterialId 1 --> RenderObjectId 1
```

This is why the mesh translation table stores a vector of render-object IDs
rather than one mesh ID.

## Preserve reusable animation data and node-local bindings

The animation importer follows the separation established in the
[descriptions post][descriptions-post]. A glTF animation sampler becomes
reusable engine channel data; the target node receives the `Animator` binding:

```text
glTF animation sampler             glTF animation channel
├── input timestamps               ├── sampler index
└── output rotations               ├── target node
        |                          └── rotation path
        v                                  |
AnimationChannel                           v
        ^                              Animator
        |                                  |
        +-------- AnimationId + ChannelId -+
```

Only `LINEAR` rotation channels are accepted. Input accessors must be float
scalars, output accessors must be float `VEC4` values, neither may be sparse,
and the sample counts must agree. Timestamps must increase strictly.

Imported quaternion values use glTF's `(x, y, z, w)` order and are normalised
at the boundary. A zero, non-finite, or otherwise unusable value is rejected
before it becomes animation data. Node-local rotations receive the same
normalisation when transforms are imported.

If several glTF channels reuse one sampler inside an animation, the loader
creates one engine `AnimationChannel` and lets their bindings share it. The
current scene-component model still allows only one binding on a source node,
so a second channel—or a channel in another animation—targeting that same node
is rejected explicitly.

Each imported binding starts at time zero, targets rotation, and loops. The
loader does not advance it: the release's separate `advanceAnimations()` frame
operation consumes the returned animations and bindings without adding
playback policy to glTF import.

## Rebuild the selected hierarchy without duplicating mesh data

glTF can identify a default scene. If it does not, the loader selects the first
scene. Its root indices drive recursive node construction; other scene
hierarchies are not instantiated.

For each selected node, the loader:

1. creates an engine node with the source name;
2. applies decomposed translation, normalised rotation, and scale;
3. installs its optional `Animator` component;
4. adds one renderable child for every primitive in its source mesh; and
5. recursively imports its source children.

The extra primitive children preserve the rule that one engine node has one
component role:

```text
source node transform -> Animator
├── primitive 0       -> RenderObjectId 4
├── primitive 1       -> RenderObjectId 5
└── source child
```

The animator remains on the source node. Primitive children inherit its world
transform and each keep their own mesh/material pairing. An ordinary mesh node
uses the same shape without the animator component.

A glTF mesh can also be instanced by several nodes. Because primitives were
translated once into reusable render objects, each instance creates only new
scene nodes referring to the same IDs; it does not duplicate vertices or
materials.

After all roots have been imported, `updateWorldTransforms()` resolves the
hierarchy. The returned content therefore has valid initial local and world
state even though the animation clock has not started.

## Validate at both content and rendering trust boundaries

The loader finishes by calling an internal composition validator:

```cpp
void validateSceneContent(const SceneContent& content)
{
    validateAssets(content.assets);
    validateAnimationBindings(content.scene, content.animations);
}
```

This combines two existing checks. `validateAssets()` proves the internal
image, texture, mesh, material, and render-object graph. Animation validation
proves timelines and quaternions, then walks the scene to check every animator's
animation ID, channel ID, target path, and playback time.

Scene render-object references are constructed from the loader's own mapping,
so they are valid by construction here. The independently usable
`RenderPreparation` still checks every `RenderObjectId` extracted from a draw
list. That matters when `SceneContent` comes from a procedural builder rather
than this loader.

Asset validation runs twice, and that is deliberate:

```text
GltfLoader::load()
    └── validateSceneContent()
            ├── validateAssets()
            └── validateAnimationBindings()

Renderer::prepare()
    └── RenderPreparation::build()
            ├── validateAssets() when identity/revision changed
            └── validate scene draw RenderObjectIds
```

The producer promises to return a valid composition. The renderer protects its
own GPU boundary regardless of which producer supplied the assets. Neither
trust boundary requires a Vulkan device to test.

See [`scene_content_validation.cpp`][source-content-validation] and
[`render_preparation.cpp`][source-render-preparation].

## Keep one real asset in the repository

Release 0.8 keeps Khronos's public-domain AnimatedCube files beneath
`assets/AnimatedCube/`:

```text
assets/AnimatedCube/
├── AnimatedCube.gltf
├── AnimatedCube.bin
├── AnimatedCube_BaseColor.png
├── AnimatedCube_MetallicRoughness.png
└── README.md
```

Keeping the document, buffer, and images together makes path resolution part
of the test rather than a mocked assumption. It also keeps builds deterministic
and offline; neither CI nor a local run downloads sample content.

The test establishes the CPU-side result concretely: one mesh with 36 vertices
and 36 indices, two decoded images with the first measuring 512 by 512, two
textures, one material with a base-colour texture, one render object, one scene
root, and one three-sample rotation channel.

AnimatedCube contains data this slice does not consume, including normals,
tangents, and metallic-roughness material information. The source asset remains
intact while the importer selects only the semantics fireEngine can represent.
Preserving a real asset does not require pretending the engine supports all of
it.

CMake uses an `ALL` target to copy the asset directory beside the application
on every build. The executable loads AnimatedCube from that build-tree path,
while one smoke scenario runs from a different working directory to prove that
asset discovery does not depend on where the process starts.

See the [asset README][source-animated-cube-readme] and the upstream
[Khronos AnimatedCube model][animated-cube].

## Generalise the sRGB presentation choice

One related renderer change broadens swapchain selection. The old helper
preferred only `B8G8R8A8Srgb`. The new helper accepts the first supported
four-channel, eight-bit sRGB format in the nonlinear sRGB colour space:

```cpp
switch (format)
{
case vk::Format::eR8G8B8A8Srgb:
case vk::Format::eB8G8R8A8Srgb:
case vk::Format::eA8B8G8R8SrgbPack32:
    return true;
default:
    return false;
}
```

Single-channel sRGB and a four-channel sRGB format paired with the wrong colour
space are not treated as suitable. If no suitable pair exists, selection keeps
the established fallback of returning the first supported format.

This selection helper does not itself upload or sample imported textures. It
removes an unnecessary channel-order preference from the presentation side of
the complete 0.8 colour path.

See [`swapchain_selection.cpp`][source-swapchain-selection] and its expanded
[test case][source-test-swapchain].

## Test the contract without a device

Six focused Catch2 cases cover this contract. Five exercise the loader and one
exercises composition validation:

- a tiny fixture imports the selected hierarchy and its TRS values;
- AnimatedCube imports the expected CPU asset descriptions;
- AnimatedCube preserves its root, renderable child, animator, and reusable
  three-sample channel;
- a missing document reports a read failure;
- required extensions, non-triangle or non-indexed primitives, missing
  `TEXCOORD_0`, non-linear interpolation, and non-rotation targets report the
  unsupported feature; and
- scene-content validation rejects both a malformed asset graph and a dangling
  animator binding.

One small `.gltf` fixture isolates hierarchy import and six more isolate the
unsupported cases. They make each failure diagnostic independent of
AnimatedCube and avoid changing several variables at once when the supported
slice evolves.

All of this remains in the ordinary unit-test executable. Parsing documents,
decoding pixels, translating accessors, constructing hierarchy, and validating
the result require no window, Vulkan instance, physical device, or queue. The
release's bounded application scenarios separately exercise real loading,
animation, preparation, drawing, repeated preparation, untextured fallback,
and presentation replacement on a Vulkan device.

See [`test_gltf_loader.cpp`][source-test-loader] and
[`test_scene_content_validation.cpp`][source-test-content].

## Troubleshooting the narrow slice

### A file works in another viewer but the loader rejects it

A valid glTF file is not necessarily inside fireEngine's supported subset.
Check the first specific message. Required extensions, embedded or non-local
images, sparse attributes, missing `TEXCOORD_0`, non-indexed geometry, other
primitive modes, non-linear interpolation, and animation paths other than
rotation are intentionally unsupported here.

### An external file cannot be found

Resolve the URI relative to the `.gltf` document, not the shell's current
directory. Keep the external buffer and images at the paths named by the
document. The loader already supplies `path.parent_path()` to both fastgltf and
the image decoder.

### A primitive has positions but still fails attribute validation

This slice also requires `TEXCOORD_0`, with one float `VEC2` per float `VEC3`
position. Normals, tangents, and vertex colours do not substitute for that
attribute. Sparse accessors and normalised integer texture coordinates are not
accepted.

### An animation with valid quaternions is rejected

Check the surrounding channel contract: the target must be rotation,
interpolation must be `LINEAR`, timestamps and values must have equal counts,
and timestamps must increase strictly. Also check whether another channel or
animation already targets the same source node; one node can carry only one
`Animator` component at this stage.

### Composition validation passes but preparation rejects a scene draw

`validateSceneContent()` composes asset validation with animation-binding
validation. `RenderPreparation` separately validates the `RenderObjectId`
values emitted by the scene draw list. Check that a procedurally assigned ID
came from the same `RenderAssets` collection paired with the scene.

## What this part of release 0.8 gives us

This part of release 0.8 puts a file-backed content producer on the CPU side of
fireEngine's renderer boundary:

- `SceneContent` becomes the shared owner of render assets, hierarchy, and
  reusable animations;
- procedural construction and file import now target the same public shape;
- `GltfLoader` exposes one path-to-content operation without exposing fastgltf
  or stb;
- parsing, images, textures, materials, geometry, animation, and hierarchy are
  translated in explicit stages;
- external paths resolve relative to the source document;
- decoded images become tightly packed engine-owned RGBA8 values;
- filters, wraps, base-colour factors, and base-colour texture references map
  into format-neutral descriptions;
- accessor iteration preserves offsets and interleaved strides;
- unsigned 16-bit and 32-bit source indices converge on one engine format;
- one glTF mesh can produce several render objects, one per primitive;
- reusable rotation samples remain separate from their node-local animator
  bindings;
- selected scene roots, TRS hierarchy, mesh instances, and primitive children
  retain the engine's one-component-per-node rule;
- loader validation and renderer preparation retain independent trust
  boundaries;
- the public-domain AnimatedCube asset provides deterministic offline coverage;
- swapchain selection accepts the supported four-channel sRGB layouts; and
- focused device-free cases exercise successful import and explicit rejection.

Release 0.8 has a real path from a `.gltf` file to validated `SceneContent`, and
the result stops at the CPU side of the renderer boundary. Texture compilation,
camera and depth rendering, and playback consume that result without teaching
the loader about a device or teaching the renderer about glTF.

## Recommended reading

- [glTF 2.0 specification: Buffers, Buffer Views, and Accessors][reading-gltf-buffers] —
  the Khronos definitions behind offset, stride, component type, accessor
  shape, and sparse data.
- [glTF 2.0 specification: Scenes and Nodes][reading-gltf-scenes] — the selected
  scene, hierarchy, and local-transform rules translated by this loader.
- [glTF 2.0 specification: Animations][reading-gltf-animations] — the sampler,
  channel, target, and interpolation model narrowed to linear rotation here.
- [fastgltf][reading-fastgltf] — the parser and accessor-iteration library kept
  behind fireEngine's public loading operation.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[descriptions-post]: {% post_url 2026-08-23-extending-fireengines-descriptions-without-introducing-vulkan %}
[source-scene-content]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/content/scene_content.hpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-gltf-loader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/gltf/gltf_loader.hpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[source-gltf-loader-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/gltf/gltf_loader.cpp>
[source-image-decoder]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/gltf/detail/image_decoder.hpp>
[source-image-decoder-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/gltf/image_decoder.cpp>
[source-content-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/content/scene_content_validation.cpp>
[source-render-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/graphics/render_preparation.cpp>
[source-animated-cube-readme]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/assets/AnimatedCube/README.md>
[source-swapchain-selection]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/swapchain_selection.cpp>
[source-test-swapchain]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/render/test_swapchain_selection.cpp>
[source-test-loader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/gltf/test_gltf_loader.cpp>
[source-test-content]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/content/test_scene_content_validation.cpp>
[animated-cube]: <https://github.com/KhronosGroup/glTF-Sample-Models/tree/main/2.0/AnimatedCube>
[reading-gltf-buffers]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#buffers-and-buffer-views>
[reading-gltf-scenes]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#scenes>
[reading-gltf-animations]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations>
[reading-fastgltf]: <https://github.com/spnda/fastgltf>
[reading-page]: {% link _tabs/reading.md %}
