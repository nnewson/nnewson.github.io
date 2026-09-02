---
title: Refactoring fireEngine for what comes next
date: 2026-08-08 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.7", 3d-engine, architecture, refactoring, testing, scene-graph, cpp]
description: >-
  A high-level plan for turning fireEngine's first triangle into a testable,
  Vulkan-free scene and rendering architecture that can grow with the tutorial.
---

Release 0.6 completed fireEngine's first full rendering path. The application
can upload a triangle, record commands, submit graphics work, and present the
result until the window closes.

That is an important checkpoint, but it is not yet a scalable engine design. The
triangle is still part of the renderer, application setup knows about most of
the Vulkan ownership tree, and testing the interesting decisions generally
means creating a window and a device.

The next stage will keep the visible result deliberately familiar. Rather than
adding more effects immediately, it will move the same triangle through the
boundaries that future models and scenes will use. This gives us a chance to
separate application data, scene state, render preparation, and Vulkan work
while the complete result is still small enough to understand.

> Starting point: [fireEngine 0.6][release-0-6]
>
> Released architecture: [fireEngine 0.7 architecture][architecture-0-7]
>
> The [first-triangle post][triangle-post] covers the rendering path we are
> about to restructure. This is a planning post rather than a release
> walkthrough, so the exact checkpoint boundaries may change as the work is
> published.
{: .prompt-info }

## What scaling means for fireEngine

Scalability here does not mean predicting every feature the engine may
eventually need. It means making the next feature possible without forcing it
through an unrelated part of the codebase.

A scene loader will be able to create meshes and nodes without knowing about
Vulkan. A scene node will describe its place in a hierarchy without recording
commands. The renderer will decide how stable descriptions become GPU
resources, while each frame will still record the work required for the current
image and current transforms.

That gives the next phase four broad kinds of state:

- **render assets** describe reusable meshes, materials, and render objects;
- **scene state** owns transformable instances of those objects;
- **prepared state** represents the validated assets needed by the scene and
  the GPU resources compiled from them; and
- **frame state** combines those resources with current transforms and the
  acquired swapchain image.

Keeping those responsibilities distinct is the central goal of the refactor.
The following posts will introduce each boundary without hiding it inside a
single large renderer rewrite.

## Build an engine that can be tested without a GPU

The completed work is covered in the [testing post][testing-post].

The first post will separate the reusable engine code from the small
application that owns `main()` and the event loop. That creates a natural place
for fast unit tests alongside the existing one-frame Vulkan smoke test.

[Catch2](https://catch2.org) will exercise maths, asset validation, scene
traversal, render planning, and other CPU-side decisions without opening a
window or creating a Vulkan device. Small Vulkan-independent choices currently
buried in implementation files will also move behind focused internal
interfaces and receive direct tests.

This is useful groundwork rather than testing for its own sake. Every later
part of the refactor introduces rules about transforms, identifiers,
dependencies, or caching. Establishing the test boundary first lets those rules
be verified as soon as they appear.

## Give scenes a small maths vocabulary

The completed work is covered in the [maths post][maths-post].

The next post will add only the maths needed to describe the first scene:
three- and four-component vectors, a column-major matrix, and the operations
required to combine translation and scale.

The aim is not to copy a complete mathematics library into the tutorial.
Cameras, projections, quaternions, and inverse matrices will wait until a real
use case needs them. Starting with compact value types keeps their memory layout
and behaviour visible, while giving scene transforms a clearer meaning than a
raw array of floats.

This also gives us an opportunity to distinguish mathematical vectors from
graphics-domain values. A colour may have four components, but treating it as a
colour rather than a generic vector makes the public interface easier to read
and harder to misuse.

## Describe render assets without Vulkan

The completed work is covered in the [render-assets post][assets-post].

Once the basic data types exist, a post will move the triangle out of the Vulkan
renderer and describe it as ordinary application data.

Meshes with their vertices and triangle indices, materials, and render objects
will not need command buffers, descriptor writes, or Vulkan handles. A
render-asset collection will own those descriptions and connect them with small
typed identifiers, keeping a mesh identifier distinct from a material
identifier even if both are stored as dense indexes internally.

This is the boundary that a future glTF loader will target. Importing a model
will produce engine descriptions, not allocate GPU resources as a side effect.
It also creates a clear validation point for empty meshes, invalid indices, and
missing relationships before Vulkan becomes involved.

## Build the first scene graph

The completed work is covered in the [scene-graph post][scene-post].

Render assets describe reusable things; a scene describes where instances of
those things appear. The scene-graph post will introduce nodes with local and
world transforms, optional render-object references, parent-child ownership,
and support for more than one root.

Traversal will produce a simple draw list containing the objects visible to this
first version of the renderer and their current world transforms. That list
remains Vulkan-free. It says what the scene wants drawn, but not how command
buffers, pipelines, or synchronization should implement it.

The separation matters even for one triangle. A transform may change every
frame while the mesh and material remain stable. Treating scene placement and
render assets as different kinds of state prevents movement from looking like a
reason to rebuild an otherwise unchanged GPU resource.

## Prepare scene data explicitly

The completed work is covered in the [render-preparation post][preparation-post].

There is still a gap between a Vulkan-free draw list and the resources a GPU can
use. A dedicated render-preparation post will make that boundary explicit.

Preparation will validate the asset catalogue and select the subset required by
the current scene. Repeating the operation with unchanged assets and draw
dependencies will reuse the previous plan, while a meaningful asset or scene
dependency change will produce a new one. Transform-only changes will not
invalidate stable mesh and material preparation.

This stage is best understood as a small compiler rather than a permanently
recorded command buffer. It turns durable application descriptions into a plan
for durable render resources. Commands still depend on the current frame slot,
swapchain image, and world transforms, so they remain transient and are
recorded each frame.

## Turn the renderer into the Vulkan facade

The completed work is covered in the [renderer-facade post][renderer-post].

The final refactoring post will bring the earlier boundaries together. The
application will create a window, a renderer, render assets, and a scene; it
will not have to assemble the Vulkan device, allocator, swapchain, pipeline, and
frame resources itself.

The renderer will expose an explicit preparation operation for stable assets and
a draw operation for current scene state. Internally, it will upload each needed
mesh once, retain the compiled resources, and record indexed draws using the
current transforms and material data. The Vulkan ownership tree remains
important, but it becomes an implementation detail behind a public interface
that contains no Vulkan types.

That draw path will also separate frame-wide data from per-draw data at the
shader boundary. The frame uniform will hold the view-projection transform,
while push constants will carry each object's model transform and material base
colour. Vertices will expand to three-dimensional positions and four-component
colours, and the vertex stage will combine each vertex colour with the material
factor before interpolation. That split lets many objects share the same frame
state while varying their placement and appearance from one draw to the next.

At the end of this post, the same coloured triangle will still appear. The
important difference is where it came from: application-owned mesh and material
data, instanced by a scene node, prepared into GPU resources, and consumed by a
renderer that no longer owns the idea of a triangle.

## Why this order

Each topic supplies the vocabulary needed by the next one. Tests make the new
CPU-side rules cheap to verify. Maths gives scene transforms a foundation.
Vulkan-free assets describe reusable render content, and the scene graph
instances that content. Render preparation connects those descriptions to GPU
resources, after which the renderer can become a smaller and more coherent
facade.

The topics are natural release checkpoints, although the final split can follow
what proves buildable and useful in isolation. What matters is preserving the
dependency direction: scene and graphics descriptions must not begin depending
on Vulkan merely because the renderer eventually consumes them.

## What remains outside this refactor

Holding the on-screen result steady keeps this architectural work teachable.
The first pass will therefore avoid glTF parsing, textures, lighting, cameras,
animation, swapchain recreation, multiple frames in flight, and a general
render graph.

Those omissions also point towards the posts that can follow. Once the public
data model is stable, a glTF loader can populate it without knowing about the
renderer. Window resizing can replace presentation-dependent resources behind
the renderer boundary. A true render graph can arrive when there are multiple
passes or intermediate images whose ordering and lifetimes need to be planned.

The refactor succeeds if it makes those additions local rather than if it tries
to implement them all at once.

## Where this leaves us

The first triangle proved that fireEngine can render. The next sequence will
prove that the path can grow: CPU-side behaviour can be tested independently,
assets can exist without Vulkan, scenes can express hierarchy and transforms,
and the renderer can compile those descriptions without taking ownership of
the application's world.

It is a larger change behind the screen than on it. That is intentional. Once
the same triangle travels through these boundaries, adding the first imported
scene will be a content problem rather than another rewrite of the rendering
architecture.

[release-0-6]: https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6
[architecture-0-7]: {% link _architecture/0.7.md %}
[triangle-post]: {% post_url 2026-08-05-rendering-fireengines-first-triangle %}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[maths-post]: {% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %}
[assets-post]: {% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %}
[scene-post]: {% post_url 2026-08-14-building-fireengines-first-scene-graph %}
[preparation-post]: {% post_url 2026-08-16-preparing-fireengines-scene-data-explicitly %}
[renderer-post]: {% post_url 2026-08-18-turning-fireengines-renderer-into-the-vulkan-facade %}
