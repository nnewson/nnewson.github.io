---
title: Growing fireEngine into an animated glTF renderer
date: 2026-08-20 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", 3d-engine, architecture, gltf, textures, animation, rendering, cpp]
description: >-
  A high-level plan for taking fireEngine from a structured triangle to an
  imported, textured, animated glTF scene with replaceable presentation state.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.7 turned fireEngine's hard-coded triangle into a small rendering
architecture. Meshes and materials became Vulkan-free application data, a
scene graph owned transformable instances, render preparation selected stable
dependencies, and `Renderer` became the facade that compiled and drew them.

Those boundaries are useful, but one procedural triangle cannot prove that
they are sufficient. A real scene arrives through files rather than C++
initialisers. It brings hierarchy, texture coordinates, images, samplers,
materials, camera requirements, animation, and enough geometry to make depth
and culling visible. A resizable application must also replace presentation
resources without discarding the imported scene it has already compiled.

Release 0.8 applies that pressure through Khronos Group's public-domain
[AnimatedCube][animated-cube] sample. The normal application path will load its
`.gltf`, external buffer, and base-colour image, then render and animate the
cube while preserving the asset, scene, preparation, and renderer boundaries
established in 0.7.

Although release 0.8 is already complete, this post presents its finished
architecture as the plan that the detailed walkthrough series will follow.
Those posts can examine individual contracts and implementation choices
against the completed checkpoint without turning this overview into one very
large release walkthrough.

> Starting point: [fireEngine 0.7][release-0-7]
>
> Target source: [fireEngine 0.8][release-0-8]
>
> Released architecture: [fireEngine 0.8 architecture][architecture-0-8]
>
> [Turning fireEngine's renderer into the Vulkan facade][renderer-facade-post]
> completes the 0.7 architecture used here. Release 0.8 is fixed, but the exact
> boundaries between the detailed walkthrough posts may change as they are
> published.
{: .prompt-info }

## What the first imported scene must prove

The aim is not broad glTF compatibility. It is one complete, inspectable path
through the engine's existing layers:

```text
.gltf + external buffer + PNG
              |
              v
          GltfLoader
              |
              v
         SceneContent
     +--------+---------+
     |        |         |
     v        v         v
RenderAssets Scene  Animations
     |        |         |
     +--------+---------+
              |
      validate and animate
              |
              v
    RenderPreparationPlan
              |
              v
 compiled GPU resources + current draws
              |
              v
           present
```

The loader must stop at `SceneContent`. It will not receive a renderer, device,
allocator, command buffer, or upload context. Animation must change scene
transforms without pretending the mesh or texture changed. Presentation
recreation must replace extent- and format-dependent Vulkan objects without
reloading the file or recompiling stable content.

That produces five broad kinds of state:

- **source state** is the glTF document and its external files;
- **description state** is the Vulkan-free asset, scene, and animation data
  produced by loading;
- **compiled state** is the selected GPU representation of meshes, images,
  textures, materials, and render objects;
- **frame state** combines current animation, world transforms, camera data,
  and the commands recorded for one submission; and
- **presentation state** owns the swapchain-dependent images, depth target,
  compatible pipeline, and retirement synchronization that may be replaced
  together.

Keeping those reasons to change separate is the central goal of 0.8.

## Give imported transforms enough vocabulary

The completed work is covered in the [transforms post][transforms-post].

The 0.7 scene graph can translate and scale its triangle, but an imported scene
needs a fuller transform model. The first part of the sequence will add the
smallest mathematical vocabulary required by the selected content.

`Vec2` will represent texture coordinates. `Quaternion` will represent
orientation and provide the identity rotation, normalisation, shortest-arc
interpolation, and matrix conversion. A decomposed `Transform` will keep
translation, rotation, and scale as the source values for each node, while
`Mat4` will gain the look-at and perspective operations needed by a camera.

This is also the point to make numerical failure explicit. Quaternion and
vector normalisation should remain stable across extreme finite magnitudes,
and a value that cannot be normalised should produce a small recoverable error
rather than silently creating an invalid transform.

Imported animations need stable targets. `SceneNodeId` and scene-local lookup
will give animation bindings an identity that survives traversal and world
matrix updates without turning node names or memory addresses into keys.

The existing column-major, 16-byte-aligned matrix convention remains intact.
Projection will map depth into Vulkan's zero-to-one range and account for the
framebuffer Y direction explicitly, so later culling and shader code share one
documented convention.

## Extend descriptions without introducing Vulkan

The completed work is covered in the [descriptions post][descriptions-post].

Textures and animations belong on the same side of the boundary as meshes and
scene nodes.

`RenderAssets` will grow to own decoded `ImageData`, texture descriptions, and
material texture references. An image will contain tightly packed RGBA8 pixels
and dimensions. A texture will identify an image and describe filtering and
wrapping through engine enums rather than Vulkan sampler values. A material
will keep its base-colour factor and an optional texture ID.

The typed-ID pattern from 0.7 will extend to images and textures. Validation
will check image extents and byte counts, texture and material relationships,
finite colour factors, and the existing mesh and render-object rules before any
GPU work begins.

Render preparation must also follow transitive dependencies:

```text
RenderObject
├── Mesh
└── Material
    └── optional Texture
        └── ImageData
```

Only the image and sampler descriptions reachable from the current scene should
enter the preparation plan. Transform-only changes will continue to reuse that
plan.

Animation data will remain target-independent: reusable channels contain
timestamps and quaternion values, while an `Animator` binds one channel to a
scene node and owns playback state. No animation type should know how the
renderer uploads a mesh or records a command.

`SceneComponent` will give each node one role: transform-only, animator, or
render object. A mesh-bearing animated glTF node will therefore become an
animator parent with one renderable child per primitive, preserving the source
hierarchy while supporting several primitives from one source mesh.

## Introduce format-neutral scene content

The completed work is covered in the [scene-content post][scene-content-post].

The loader needs one result that is useful beyond glTF. `SceneContent` will
group the three application-owned collections that travel together:

```cpp
struct SceneContent
{
    RenderAssets assets;
    Scene scene;
    std::vector<Animation> animations;
};
```

This composition keeps file format out of the long-lived model. A procedural
builder, a different importer, or an editor can produce the same result without
emulating fastgltf types.

`GltfLoader` will coordinate separate stages for images, textures, materials,
geometry, transforms, animation, and hierarchy. fastgltf and stb will remain
private implementation dependencies. The public operation will accept a path
and either return complete, validated `SceneContent` or report why that content
cannot be represented by release 0.8.

Validation at the loader boundary will not replace preparation validation. The
loader must prove that its composed result is internally complete; the renderer
must remain safe when content comes from any producer.

The first producer of that result will be a deliberately narrow glTF loader,
and it should say exactly what it accepts. Release 0.8 will focus on JSON
`.gltf` files with external local buffers and PNG images, one selected scene,
reachable TRS nodes, indexed triangle primitives, positions, one set of texture
coordinates, base-colour materials, samplers, and linear rotation animation.

Accessor extraction must respect accessor offsets, buffer-view offsets, and
interleaved byte strides. Both unsigned 16-bit and unsigned 32-bit indices will
be converted into the engine's existing 32-bit representation. External paths
will resolve relative to the source document rather than the process working
directory.

Unsupported data should fail explicitly. Required extensions, sparse or
incorrectly typed accessors, non-indexed geometry, other primitive modes,
non-local images, unsupported animation targets, and unsupported interpolation
must not be partially ignored and allowed to fail later inside Vulkan.

AnimatedCube contains more than this renderer will use. Normals, tangents, and
metallic-roughness data can remain committed with the upstream asset while
lighting, normal mapping, and physically based shading stay outside the first
vertical slice.

## Compile and sample the first texture

The completed work is covered in the [texture-compilation post][texture-post].

Decoded pixels are still only descriptions. Crossing the existing preparation
boundary will turn them into renderer-owned resources.

The renderer will add a VMA-backed image owner, upload pixels through a staging
buffer, transition device-local sRGB images with Synchronization 2, create
image views, and compile engine filtering and wrapping choices into Vulkan
samplers. The preparation plan will ensure that only images and textures used
by the current scene receive those representations.

Uploads will reuse the single frame slot's command pool and fence after waiting
for any earlier GPU work using that frame slot to finish. That is acceptable
for this one-frame renderer; a dedicated upload context belongs to a later
resource compiler.

Materials without a base-colour texture need the same draw path. A persistent
one-pixel white image and sampler will provide a neutral fallback rather than
branching the shader and descriptor layout into textured and untextured
variants.

The scene shader will sample one combined image-sampler binding and multiply
that colour by the material and vertex factors. Imported vertices can begin
with white vertex colour, leaving the decoded texture and material factor to
produce the visible surface.

Release 0.8 needs only one mip level and no anisotropic filtering.
Mipmaps and richer sampling can wait until something in the tutorial needs
them. Both add resources and synchronisation work, and neither earns that while
a single unmipped texture is all that gets sampled.

## Add a camera, depth, and culling together

The completed work is covered in the [visibility post][visibility-post].

A rotating cube makes spatial mistakes visible in ways a single front-facing
triangle cannot. It needs a perspective camera, hidden-surface removal, and a
consistent winding convention.

The renderer will use a fixed camera looking towards the origin and derive its
projection aspect ratio from the current presentation extent. The frame
uniform remains the right home for the shared view-projection matrix, while
each draw continues to push its model transform.

Depth should be treated as presentation-dependent state. The renderer will
select a supported depth format, allocate an extent-matched image and view,
transition and clear it for each frame, and add it to dynamic rendering. The
pipeline will enable depth testing and writes with a less-than comparison.

Back-face culling will complete the first opaque 3D path. Its front-face choice
must agree with glTF's convention, the column-vector transform order, and the
projection-side Y inversion rather than being adjusted until one model happens
to look right.

## Animate transforms without rebuilding resources

The completed work is covered in the [animation post][animation-post].

The imported rotation channel is the test that the 0.7 cache boundary was
designed to pass.

Each frame, animation playback will advance time, locate the surrounding
keyframes, interpolate the shortest quaternion arc, and write the result to the
target node's local rotation. Looping clips will wrap; non-looping clips will
clamp. Scene traversal will then resolve current world matrices before drawing.

None of that should change asset revision or ordered render-object identity.
The preparation generation and compiled meshes, images, samplers, and material
bindings must therefore remain stable while the cube rotates.

Focused tests can exercise exact keyframe boundaries, interpolation,
normalisation, looping, clamping, invalid timelines, and broken bindings
without opening a window. The rendered scenario then proves that those CPU
values reach the real shader path.

## Make presentation state replaceable

The completed work is covered in the [presentation post][presentation-post].

Release 0.7 reports resize, suboptimal, and out-of-date conditions but leaves
recreation for later. Release 0.8 will make replacement a normal renderer
operation.

The swapchain, image views, per-image presentation semaphores, depth buffer,
format-compatible pipeline, and presentation-retirement fences share one
replacement lifetime. Grouping them as `PresentationState` makes that lifetime
visible. Device, allocator, frame slot, render-preparation cache, and compiled
scene resources remain outside it.

Recreation will pass the old swapchain to Vulkan, build a complete candidate
presentation state, refresh the camera projection for the new extent, then
replace the old group. A minimised zero-sized framebuffer will wait for events
instead of spinning or trying to construct an invalid swapchain.

Device idle alone is not a complete proof that the presentation engine has
released its resources. The renderer will require the KHR swapchain-maintenance
path or its equivalent EXT path and attach one presentation fence per image.
Those fences provide an explicit retirement boundary before an old swapchain
and its semaphores are destroyed or one image's fence is reused.

Resize callbacks, out-of-date acquisition, and suboptimal presentation can all
request the same replacement operation. The policy stays in the event loop;
the Vulkan lifetime protocol remains inside the renderer.

## Keep the facade public and its owners focused

Real content will grow the renderer implementation substantially. That is a
reason to strengthen the facade, not to expose its Vulkan helpers again.

Allocator, buffer, device, frame, pipeline, swapchain, upload, and other Vulkan
declarations will move under `render/detail`. The public documentation will
show supported engine interfaces, while a separate internal view retains the
tutorial's implementation detail. CI can verify that `detail` headers and
implementation sources do not leak into the public file index.

Once the complete ownership graph is visible, broad implementation code can be
split by lifetime. `CompiledResources` will own plan-scoped images, samplers,
meshes, fallback resources, upload machinery, and render-object lookup.
`DepthBuffer` will remain a direct owner inside replaceable presentation state.

Candidate graphs should be built locally and committed only after every
allocation succeeds. For example, each compiled render-object lookup borrows
pointers to its compiled mesh and texture. Those lookup entries must be
replaced before the mesh and texture owners are replaced, so no pointer is left
dangling even briefly. That ordering is the whole protocol: build the new
graph, swap the borrowers, then release the old owners. Writing it down makes
repeated preparation and exception safety reviewable, instead of resting on a
fortunate sequence of assignments in one large `renderer.cpp`.

## Verify complete application scenarios

The device-free suite will continue to cover maths, loading, validation,
animation, render planning, and Vulkan value-selection policy. The integration
tests must then prove the ownership transitions that only exist with a real
window and driver.

Four bounded application scenarios will cover the main paths:

- **basic** loads AnimatedCube, samples animation deterministically, prepares,
  and draws the textured scene;
- **prepare-twice** changes assets and dependencies after a submitted frame and
  replaces compiled state;
- **untextured** exercises the persistent white fallback through the normal
  descriptor and draw path; and
- **resize** repeatedly replaces presentation state while compiled scene
  resources survive.

Debug variants can enable synchronization validation for repeated preparation
and recreation. All Vulkan scenarios should fail when a validation error is
reported, and should share one CTest resource lock so they never contend for
the device. Warnings stay visible for diagnosis: a validation layer's
performance suggestion is not a correctness failure and should not fail the
run.

The basic scenario will run from an isolated working directory, away from the
executable and copied assets, to prove that compiled asset and shader paths do
not depend on the current working directory. Real window-manager resize,
minimise, restore, and display-move behaviour will remain manual checks where
CI cannot provide a suitable interactive desktop.

## Why this order

Each stage supplies the stable input required by the next. Imported transforms
need maths and scene identity. Textures and animation need Vulkan-free
descriptions before a loader can produce them. The constrained loader provides
validated data for image compilation, camera rendering, and playback.

Animation then proves that current transforms do not invalidate stable
resources. Presentation recreation proves that extent-dependent resources can
change without invalidating compiled scene content. Focused ownership types and
the scenario suite become easier to design once those complete lifetimes are
visible.

The implementation history may interleave tests and small refactors with every
stage. The architectural dependency direction should not change:

```text
file format -> engine descriptions -> preparation -> renderer -> Vulkan
```

No arrow points back towards the loader or scene.

## What remains outside this release

One complete imported path is more useful than many partial features. Release
0.8 will therefore avoid binary `.glb`, embedded resources, sparse accessors,
non-indexed primitives, multiple UV sets, vertex colours from glTF, and runtime
selection among several scenes.

Rendering will remain unlit. Metallic-roughness evaluation, normal maps,
alpha modes, double-sided materials, mipmaps, anisotropic filtering, skinning,
morph targets, and a general material system can wait for later vertical
slices.

Animation will support rotation only, with linear interpolation and no
blending, events, playback graphs, translation channels, scale channels, or
cubic splines. Rendering will still use one frame in flight, without a general
pipeline cache, resource graph, or render graph.

These are deliberate constraints, not accidental omissions. They keep the
release centred on proving that one real asset can pass through every existing
boundary without collapsing those boundaries.

## Where this leaves us

Release 0.7 made an imported scene possible in principle. Release 0.8 will make
that path concrete: load committed content, preserve its hierarchy, compile its
selected resources, sample its texture, animate its transform, render it with
depth, and keep it alive across presentation replacement.

The important result is not simply a rotating cube. AnimatedCube will travel
through the asset, scene, animation, preparation, compilation, frame, and
presentation layers without making glTF or Vulkan the owner of the whole path.

Once that vertical slice is complete, the next architectural challenge becomes
scheduling and ownership for concurrency rather than another rewrite of how
content reaches the renderer.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[architecture-0-8]: {% link _architecture/0.8.md %}
[renderer-facade-post]: {% post_url 2026-08-18-turning-fireengines-renderer-into-the-vulkan-facade %}
[transforms-post]: {% post_url 2026-08-22-giving-fireengine-imported-transforms-enough-vocabulary %}
[descriptions-post]: {% post_url 2026-08-23-extending-fireengines-descriptions-without-introducing-vulkan %}
[scene-content-post]: {% post_url 2026-08-27-introducing-format-neutral-scene-content-to-fireengine %}
[texture-post]: {% post_url 2026-08-28-compiling-and-sampling-fireengines-first-texture %}
[visibility-post]: {% post_url 2026-08-29-adding-camera-depth-and-culling-to-fireengine %}
[animation-post]: {% post_url 2026-08-30-animating-fireengines-transforms-without-rebuilding-resources %}
[presentation-post]: {% post_url 2026-08-31-making-fireengines-presentation-state-replaceable %}
[animated-cube]: <https://github.com/KhronosGroup/glTF-Sample-Models/tree/main/2.0/AnimatedCube>
