---
title: "Preparing fireEngine's scene data explicitly"
date: 2026-08-16 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.7", rendering, preparation, caching, assets, scene-graph, architecture, cpp]
description: >-
  Validate fireEngine's render assets, select the subset required by a scene,
  and cache a Vulkan-free preparation plan across transform-only changes.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

The previous post gave fireEngine a Vulkan-free draw list. Scene traversal now
produces one `DrawItem` for every drawable instance, pairing a reusable
`RenderObjectId` with its current world transform. That describes what the
scene wants to draw, but it does not yet identify the durable resources the
renderer must compile.

Release 0.7 makes that missing boundary explicit. `RenderPreparation` validates
the complete asset catalogue, checks every scene reference, selects the
distinct meshes, materials, and render objects required by the current draw
list, and returns a `RenderPreparationPlan`. Repeating the same work reuses the
cached plan instead of treating every frame as a new compilation request.

This is the fifth post based on release 0.7. The [first][testing-post]
established the device-free test boundary, the [second][maths-post] introduced
the transform vocabulary, the [third][assets-post] described reusable render
assets, and the [fourth][scene-post] built the hierarchy that instances them.
This post connects the asset and scene layers through preparation. It stops
before the renderer turns that plan into Vulkan buffers and draw commands.

The walkthrough follows the preparation changes from [release 0.6][release-0-6]
to [release 0.7][release-0-7]. Every source link remains pinned to 0.7 so the
examples continue to match the release.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Building fireEngine's first scene graph][scene-post] for the draw
> list consumed here. This post produces a validated, Vulkan-free compilation
> plan; the [renderer-facade post][renderer-post] covers allocating and
> drawing its GPU resources.
{: .prompt-info }

## Define the compilation boundary

The asset catalogue and scene draw list arrive with different shapes and
lifetimes:

- `RenderAssets` contains every CPU-side mesh, material, and render-object
  description known to the application;
- `SceneDrawList` contains the render-object instances required by one current
  traversal; and
- world transforms change command data, but do not change which durable mesh
  and material resources exist.

Preparation combines only the stable parts of those inputs:

```text
RenderAssets ------------------------+
  meshes, materials, objects         |
  collection identity and revision   v
                              RenderPreparation
SceneDrawList --------------------->  validate + select + cache
  ordered RenderObjectIds            |
  dependency hash                    v
                              RenderPreparationPlan
                                distinct MeshIds
                                distinct MaterialIds
                                validated object relationships
```

The world transform carried by each `DrawItem` does not enter the plan. It
remains transient input for command recording after preparation has completed.

This is compiler-shaped work. The catalogue and draw list are source
descriptions, validation rejects invalid programs, and the plan is a compact
intermediate representation for the renderer. It is not a command buffer:
commands still depend on the acquired swapchain image, the current frame slot,
and each instance's latest transform.

The preparation layer adds two files and extends the existing graphics tests:

```text
include/fire_engine/graphics/
└── render_preparation.hpp

src/graphics/
└── render_preparation.cpp

tests/graphics/
└── test_render_preparation.cpp
```

These files contain no Vulkan types. Plan construction and all of its failure
paths can therefore run without a window, device, allocator, or queue.

## Separate state by its reason to change

The cache works because release 0.7 distinguishes three kinds of change:

| Input | Example change | Preparation result |
| --- | --- | --- |
| Asset catalogue | Add a mesh, material, or render object | Revalidate and rebuild |
| Draw dependencies | Add, remove, or reorder an instanced render object | Rebuild the selected plan |
| Per-instance state | Move a node while retaining its render object | Reuse the plan |

The distinction is semantic rather than simply based on update frequency. A
scene may move rarely, and an importer may add several assets at startup, but a
world transform still cannot invalidate a vertex buffer. Conversely, adding
one currently unused material advances the catalogue revision because the
complete input has changed and must be validated as a new version.

`SceneDrawList` already carries the two scene views preparation needs:

```cpp
struct SceneDrawList
{
    std::vector<DrawItem> drawItems; ///< Current instances in depth-first scene order.
    std::size_t dependencyHash = 0;  ///< Hash of the ordered render-object dependencies.
};
```

Each draw item contains a `RenderObjectId` and world matrix. The dependency
hash covers the ordered ID sequence, including duplicates, while deliberately
excluding those matrices. See the complete
[`scene_draw_list.hpp`][source-scene-draw-list].

## Describe a Vulkan-free preparation plan

The output has enough information for a later renderer stage without deciding
how that stage allocates memory:

```cpp
struct PreparedRenderObject
{
    RenderObjectId id;
    MeshId mesh;
    MaterialId material;
};

struct RenderPreparationPlan
{
    std::vector<MeshId> meshes;
    std::vector<MaterialId> materials;
    std::vector<PreparedRenderObject> renderObjects;
    std::size_t assetRevision = 0;
    std::size_t dependencyHash = 0;
};
```

The three vectors represent different compilation jobs:

- `meshes` identifies each distinct geometry resource that needs a GPU form;
- `materials` identifies each distinct appearance description required by the
  selected objects; and
- `renderObjects` retains the validated mesh/material relationship for every
  distinct render object the scene uses.

The plan keeps typed source IDs rather than replacing them with new plan-local
indices. The renderer can therefore build lookup tables addressed by the same
IDs already carried by draw items. Unused catalogue entries remain absent from
the plan, but required entries keep their original identity.

`dependencyHash` participates in cache lookup beside the exact dependency
sequence. `assetRevision` records the catalogue revision represented by a
successfully compiled plan. The
[selection section](#select-distinct-resources-in-stable-id-order) shows where
both values are attached to the completed plan.

See the complete
[`render_preparation.hpp`][source-render-preparation-header].

## Validate the catalogue before selecting from it

The cache-input check comes from
[`render_preparation.cpp`][source-render-preparation-cpp].

Preparation first decides whether it has already validated this exact
catalogue version:

```cpp
const bool assetsChanged = validatedAssets_ != &assets ||
                           !validatedRevision_.has_value() ||
                           *validatedRevision_ != assets.revision();
if (assetsChanged)
{
    detail::validateAssets(assets);
    validatedAssets_ = &assets;
    validatedRevision_ = assets.revision();
}
```

Both collection identity and revision matter. Two `RenderAssets` instances may
each be at revision three while owning unrelated descriptions, so comparing the
counter alone would reuse validation across different ID spaces. The address
distinguishes the owners; the revision distinguishes supported mutations of
one owner.

Validation covers the complete catalogue before subset selection. An unused
mesh with an out-of-range index is still malformed input, and an unused render
object with a missing material still breaks the catalogue's relationship
contract. This keeps `RenderAssets` meaningful as one valid graph rather than
allowing errors to remain hidden until a particular scene happens to reference
them.

If validation throws, the cached validated identity and revision are not
advanced. A corrected input must pass the complete check before it can become
the new trusted version.

The [render-assets post][assets-post] covers the validation rules themselves.
Here the important addition is their placement: they run before the first plan
lookup or GPU allocation, and only a new catalogue identity or revision causes
them to run again.

## Keep the exact dependency sequence beside its hash

The dependency extraction and comparison come from
[`render_preparation.cpp`][source-render-preparation-cpp].

The draw-list hash provides a quick transform-independent summary, but hashes
can collide. Preparation therefore extracts the exact ordered render-object
sequence as its authoritative scene key:

```cpp
std::vector<RenderObjectId> dependencies(const SceneDrawList& drawList)
{
    std::vector<RenderObjectId> result;
    result.reserve(drawList.drawItems.size());
    for (const DrawItem& drawItem : drawList.drawItems)
    {
        result.push_back(drawItem.renderObject);
    }
    return result;
}
```

The cache hit requires every stable input to agree:

```cpp
std::vector<RenderObjectId> currentDependencies = dependencies(drawList);
if (!assetsChanged && cachedPlan_.has_value() &&
    cachedPlan_->dependencyHash == drawList.dependencyHash &&
    cachedDependencies_ == currentDependencies)
{
    return *cachedPlan_;
}
```

`currentDependencies` is extracted once because both the cache check and the
miss path need it. When the hashes differ, short-circuit evaluation avoids the
element-by-element vector comparison. When they match, the exact ID sequence
remains authoritative. Retaining both is more deliberate than treating the
hash as proof of equality.

Order and repetition remain part of the key:

```text
[object 2]             differs from [object 2, object 2]
[object 1, object 2]   differs from [object 2, object 1]
```

The eventual selected resource subset may be identical for the reordered
case, but the input dependency sequence has changed. Release 0.7 chooses the
simple conservative rule and recompiles the plan. A later renderer can refine
that policy if profiling shows a useful distinction between membership and
draw order.

World transforms never appear in `currentDependencies`. Moving either instance
in `[object 2, object 2]` leaves both the hash and exact key unchanged, so the
same plan remains valid.

## Reject scene references before indexing the catalogue

The checked-selection excerpt comes from
[`render_preparation.cpp`][source-render-preparation-cpp].

Asset validation proves that each `RenderObject` refers to an existing mesh
and material. It cannot prove that a scene's `RenderObjectId` belongs to this
catalogue, because the scene is an independent owner.

Preparation checks that second relationship while marking the objects the draw
list uses:

```cpp
std::vector<bool> usedRenderObjects(assets.renderObjects().size(), false);
for (const RenderObjectId renderObject : currentDependencies)
{
    if (!renderObject.valid() ||
        renderObject.value >= assets.renderObjects().size())
    {
        throw std::invalid_argument(
            "A scene draw refers to a missing render object");
    }
    usedRenderObjects[renderObject.value] = true;
}
```

The validity check catches the default sentinel. The range check prevents an
out-of-bounds index before the value indexes `renderObjects()`; any in-range
value is treated as an index into the supplied catalogue.

An empty draw list is valid. It produces an empty selected subset after the
catalogue passes validation. A non-empty list, however, must resolve every
instance; preparation never silently drops a missing object.

## Select distinct resources in stable ID order

The boolean marker vector serves two purposes. It deduplicates repeated scene
instances, and walking it by index gives the resulting render objects stable
catalogue order regardless of traversal order:

```cpp
RenderPreparationPlan plan;
plan.assetRevision = assets.revision();
plan.dependencyHash = drawList.dependencyHash;
std::vector<bool> usedMeshes(assets.meshes().size(), false);
std::vector<bool> usedMaterials(assets.materials().size(), false);

for (std::size_t index = 0; index < usedRenderObjects.size(); ++index)
{
    if (!usedRenderObjects[index])
    {
        continue;
    }

    const RenderObject& renderObject = assets.renderObjects()[index];
    usedMeshes[renderObject.mesh.value] = true;
    usedMaterials[renderObject.material.value] = true;
    plan.renderObjects.push_back({
        .id = RenderObjectId{.value = index},
        .mesh = renderObject.mesh,
        .material = renderObject.material,
    });
}
```

Mesh and material markers are then walked in the same way:

```cpp
for (std::size_t index = 0; index < usedMeshes.size(); ++index)
{
    if (usedMeshes[index])
    {
        plan.meshes.push_back(MeshId{.value = index});
    }
}
```

The material loop is identical apart from its ID type.

Suppose a scene draws render objects `4`, `1`, and `4` in that order. Object
`4` appears twice as an instance, but its durable relationship enters the plan
once. If objects `1` and `4` share mesh `0`, that mesh also enters the plan
once. Unreferenced objects and their otherwise unused assets do not enter at
all.

This separates instance multiplicity from resource multiplicity:

| Value | Preserves draw repetition? | Deduplicated for preparation? |
| --- | --- | --- |
| `DrawItem` | Yes | No |
| `PreparedRenderObject` | No | Yes, by `RenderObjectId` |
| `MeshId` and `MaterialId` | No | Yes, by typed ID |

The plan is deterministic because its output vectors use ascending dense-ID
order. That makes it easier to test and gives the renderer predictable
allocation input without changing the scene's separate draw order.

See the complete
[`render_preparation.cpp`][source-render-preparation-cpp].

## Cache one current plan

The cache commit comes from
[`render_preparation.cpp`][source-render-preparation-cpp].

After successful compilation, `RenderPreparation` replaces its cached input
and output and increments a generation counter:

```cpp
cachedDependencies_ = std::move(currentDependencies);
cachedPlan_ = std::move(plan);
++generation_;
return *cachedPlan_;
```

`generation()` counts successful plan cache misses, not calls to `build()`.
The renderer can compare the generation it has already compiled with the
current one; an unchanged value means there is no new resource plan to consume.

This is deliberately a single-entry cache. Returning to a plan used two scene
configurations ago rebuilds it rather than searching a history. That keeps
ownership, invalidation, and memory use obvious for the first implementation.

The returned reference remains valid until a later `build()` call changes the
plan. Callers should not retain it across an input change. `RenderPreparation`
itself is movable but not copyable, preserving one owner for its cached
collection identity, exact dependency key, plan, and generation.

The collection identity uses an address, so its lifetime is part of the cache
contract. If a catalogue is destroyed and another is constructed at the same
address with the same revision, a fresh `RenderPreparation` is required. This
is a narrow consequence of the simple identity scheme, documented in the
public header rather than hidden as an implementation assumption.

## Put preparation before the frame loop

The tutorial application exposes the stable/transient split in its control
flow:

```cpp
fire_engine::Renderer renderer{glfw, window, applicationName};
TutorialContent content = makeTriangleScene();
renderer.prepare(content.assets, content.scene);

// Renderer information and startup logging are omitted.

std::uint64_t renderedFrameCount = 0;
bool swapchainNeedsRecreation = false;
while (!window.shouldClose() && (!frameLimit.has_value() || renderedFrameCount < *frameLimit))
{
    window.pollEvents();
    if (window.shouldClose())
    {
        break;
    }

    content.scene.updateWorldTransforms();
    const fire_engine::RenderResult result = renderer.drawFrame(content.scene);
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

The `--frames` limit belongs to the smoke-test contract covered in the
[first 0.7 post][testing-post], while the presentation-result handling follows
the [first-triangle post][triangle-post].

The explicit call says that validation, dependency compilation, allocation,
and upload may happen before drawing starts. The loop then resolves current
world transforms and draws without pretending that movement requires stable
asset preparation.

Applications should call `prepare()` again after adding assets or changing
which render objects the scene instances. Repeating it with unchanged catalogue
and dependencies is allowed: the cached plan generation lets the renderer
return without replacing GPU resources. Transform-only changes do not require
another preparation call because their values are consumed later by
`drawFrame()`.

This post stops at the CPU plan and its invalidation rules. The
[renderer-facade post][renderer-post] follows
[`Renderer::prepare()`][source-renderer] as it consumes the plan, uploads the
selected meshes, and establishes the contract checked by `drawFrame()`.

See the complete [`main.cpp`][source-main].

## Test preparation without a device

[`test_render_preparation.cpp`][source-test-preparation] contributes five cases
to this boundary:

- two render objects sharing one mesh and material produce one mesh entry, one
  material entry, and two prepared object relationships;
- incomplete mesh data is rejected when preparation invokes catalogue
  validation;
- dangling asset and scene relationships are rejected;
- transform-only changes reuse a plan, while exact dependency or asset-revision
  changes advance its generation; and
- scene hierarchy changes do not advance the independent asset revision.

The cache test exercises all three change categories in one sequence:

```cpp
RenderPreparation preparation;
const auto firstDrawList = scene.buildDrawItems();
const auto& firstPlan = preparation.build(assets, firstDrawList);
REQUIRE(preparation.generation() == 1);

root.localTransform(fire_engine::Mat4::translation({.x = 2.0f}));
scene.updateWorldTransforms();
const auto movedDrawList = scene.buildDrawItems();
const auto& reusedPlan = preparation.build(assets, movedDrawList);

REQUIRE(movedDrawList.dependencyHash == firstDrawList.dependencyHash);
REQUIRE(&reusedPlan == &firstPlan);
REQUIRE(preparation.generation() == 1);

SceneNode& second = scene.addRoot("second triangle");
second.renderObject(object);
auto expandedDrawList = scene.buildDrawItems();
// Simulate a hash collision: the exact dependency sequence must still
// distinguish one instance from two.
expandedDrawList.dependencyHash = firstDrawList.dependencyHash;
static_cast<void>(preparation.build(assets, expandedDrawList));
REQUIRE(preparation.generation() == 2);

static_cast<void>(assets.addMaterial(Material{}));
static_cast<void>(preparation.build(assets, expandedDrawList));
REQUIRE(preparation.generation() == 3);
```

The forced hash value simulates a collision between the one- and two-instance
sequences. The exact dependency vector still detects the change and advances
the generation to two. Adding an otherwise unused material then advances the
asset revision and generation to three.

That collision simulation is important. A test that only compared naturally
different hashes would prove the fast path, but not the correctness fallback.

## Run the preparation tests

Clone, configure, and build release 0.7 as described in the
[first 0.7 post][testing-post]. During focused preparation work, CTest can
select the five relevant cases by their shared prefixes:

```shell
ctest --preset default -R "^(Render preparation|Render asset revisions)"
```

The filter leaves the `Color4` case in the same source file, direct asset
validation, maths, scene traversal, swapchain policy, SPIR-V loading, and the
Vulkan smoke test outside this focused run.

## Diagnose the new failure boundaries

Preparation deliberately reports CPU-description problems before Vulkan work
begins. The input that changed determines where to look.

### A scene draw refers to a missing render object

Check that the node's ID came from the same `RenderAssets` instance passed to
preparation. A default ID is invalid, and a numerically plausible ID from a
different catalogue does not carry its original owner with it.

### An unused malformed asset prevents preparation

This is intentional in release 0.7. Validation establishes that the complete
catalogue is internally valid before selecting a subset. Remove or correct the
malformed description rather than relying on the current scene not to use it.

### Moving a node increments the preparation generation

Check the dependency hash and exact ID sequence produced by scene traversal.
`DrawItem::world` must remain outside both. Movement should update transforms,
not detach and reattach a different render object.

### The dependency hash is unchanged but the plan rebuilds

The hash is only one part of the key. A different exact ID sequence, a changed
catalogue revision, or a different catalogue instance correctly forces a
rebuild even when the numeric hash matches.

### A repeated instance appears only once in the plan

That is the intended distinction between draws and resources. The draw list
retains every instance and transform. The plan retains one durable
`PreparedRenderObject` per object ID and one entry per required mesh and
material.

### Plan entries appear in a different order from scene traversal

Plans use ascending dense-ID order for deterministic resource compilation.
Scene traversal order remains in `SceneDrawList` and is consumed later when
recording draws. Do not use plan-vector order as draw order.

### A retained plan reference changes after another build

The returned reference is valid only until a `build()` call replaces the
cached plan. Copy the information needed for longer-lived work, or consume the
plan before asking the same `RenderPreparation` to compile changed inputs.

### Returning to an older scene configuration causes a rebuild

Release 0.7 keeps one current plan, not a multi-entry cache. Reusing a historic
plan would require an additional ownership and eviction policy that this first
boundary does not yet need.

## What this part of release 0.7 gives us

The first four 0.7 posts established testability, maths, render descriptions,
and scene traversal. This fifth part turns their stable relationships into an
explicit compilation input:

- `RenderPreparationPlan` remains Vulkan-free while describing the required
  resource subset;
- `PreparedRenderObject` retains each validated object-to-mesh-and-material
  relationship;
- catalogue identity and revision control repeated whole-asset validation;
- validation completes before subset selection or GPU allocation;
- scene render-object IDs are checked independently of asset relationships;
- the dependency hash excludes world transforms and includes ordered object
  identity;
- an exact dependency vector prevents hash collisions from becoming false
  cache hits;
- repeated instances collapse to one prepared render object;
- shared meshes and materials collapse to one resource-plan entry;
- unused valid assets remain outside the selected plan;
- plan output uses stable dense-ID order while draw order remains separate;
- transform-only changes reuse the current plan;
- asset, instance-membership, and instance-order changes rebuild it;
- the generation counter exposes successful plan cache misses to the renderer;
- a documented single-entry cache keeps the first invalidation policy small;
- application control flow separates explicit preparation from per-frame
  transform updates and drawing; and
- five focused Catch2 cases verify selection, validation, caching, collision
  handling, and revision independence without a device.

The plan still does not own a vertex buffer, material lookup, command buffer,
or Vulkan handle. The [renderer-facade post][renderer-post] shows how
`Renderer` consumes this plan during `prepare()`, retains compiled GPU
resources, and uses current draw items during `drawFrame()`.

## Recommended reading

- [C++ Software Design][reading-cpp-software-design] — Klaus Iglberger's guide
  to dependency direction, change isolation, and explicit architectural
  boundaries in modern C++.
- [Game Engine Architecture][reading-game-engine-architecture] — Jason
  Gregory's treatment of resource managers, runtime representations, scene
  submission, and rendering architecture.
- [Real-Time Rendering][reading-real-time-rendering] — the broader rendering
  context for separating persistent resources from per-frame and per-draw
  state.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[triangle-post]: {% post_url 2026-08-05-rendering-fireengines-first-triangle %}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[maths-post]: {% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %}
[assets-post]: {% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %}
[scene-post]: {% post_url 2026-08-14-building-fireengines-first-scene-graph %}
[renderer-post]: {% post_url 2026-08-18-turning-fireengines-renderer-into-the-vulkan-facade %}
[source-scene-draw-list]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/scene/scene_draw_list.hpp>
[source-render-preparation-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/render_preparation.hpp>
[source-render-preparation-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/graphics/render_preparation.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/main.cpp>
[source-renderer]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/render/renderer.cpp>
[source-test-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/graphics/test_render_preparation.cpp>
[reading-cpp-software-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-game-engine-architecture]: <https://www.gameenginebook.com/>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-page]: {% link _tabs/reading.md %}
