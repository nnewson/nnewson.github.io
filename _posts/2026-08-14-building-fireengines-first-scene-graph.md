---
title: "Building fireEngine's first scene graph"
date: 2026-08-14 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.7", scene-graph, hierarchy, transforms, rendering, architecture, cpp]
description: >-
  Build a Vulkan-free scene graph that owns transformable nodes, resolves world
  transforms, and emits stable draw items for fireEngine's renderer.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

The previous post moved fireEngine's triangle into reusable render descriptions.
A mesh now owns geometry, a material describes appearance, and a render object
connects the two. None of those values says where an instance belongs in a
scene, how it relates to another instance, or which transform applies this
frame.

Release 0.7 gives that changing placement its own model. A `Scene` owns
`SceneNode` hierarchies. Each node has a local transform, a cached world
transform, and an optional `RenderObjectId`. Traversing the hierarchy produces a
flat list of Vulkan-free `DrawItem` values for the renderer to consume.

This is the fourth post based on release 0.7. The [first][testing-post]
established the device-free test boundary, the [second][maths-post] introduced
the transform vocabulary, and the [third][assets-post] described reusable
render assets. This post joins those pieces through scene ownership and
traversal. It will not repeat their implementation, and it stops before render
preparation decides which GPU resources the draw list requires.

The walkthrough follows the scene changes from [release 0.6][release-0-6] to
[release 0.7][release-0-7]. Every source link remains pinned to 0.7 so the
examples continue to match the release.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Describing fireEngine's render assets without Vulkan][assets-post]
> for the IDs instanced by scene nodes. This post produces a current draw list;
> the [render-preparation post][preparation-post] covers how that list
> selects durable resources.
{: .prompt-info }

## Introduce the scene-graph vocabulary

"Scene graph" is a broad name, so it helps to establish exactly what release
0.7 means by it:

- a **scene** owns all the placement state submitted together;
- a **node** is one named, transformable position in that scene;
- a **root** has no parent, while a **child** is owned beneath another node;
- a node and all of its descendants form a **subtree**;
- a node's **local transform** is relative to its parent;
- its **world transform** is the resolved object-to-world transform;
- an **instance** is a node that refers to a reusable render object; and
- **traversal** visits the hierarchy and emits a flat **draw list**.

The public structure is deliberately a forest of owned trees rather than an
arbitrary graph:

```text
Scene
├── root "environment"                 (transform only)
│   ├── child "triangle A"             (RenderObjectId 0)
│   └── child "triangle B"             (RenderObjectId 0)
└── root "independent object"          (RenderObjectId 1)
```

There may be several roots, but each child has exactly one owner. The same
`RenderObjectId` may appear on several nodes because asset reuse does not imply
shared transform ownership.

There is no visibility system, spatial partition, component model, animation,
or editor metadata yet. The first scene graph establishes only the hierarchy,
transform, instancing, and traversal contracts required by the tutorial.

The source tree gains one graphics value and a small scene layer:

```text
include/fire_engine/
├── core/
│   └── hash.hpp
├── graphics/
│   └── draw_item.hpp
└── scene/
    ├── scene.hpp
    ├── scene_draw_list.hpp
    └── scene_node.hpp

src/scene/
├── scene.cpp
└── scene_node.cpp

tests/scene/
└── test_scene.cpp
```

The files under `scene` contain no Vulkan types. The hierarchy can therefore
be created, moved, transformed, traversed, and tested without a window or GPU.

## Separate reusable content from changing placement

The asset catalogue and scene answer different questions:

| Layer | Question | Typical lifetime |
| --- | --- | --- |
| `RenderAssets` | What meshes, materials, and render objects exist? | Stable across many frames |
| `Scene` | Which instances exist, and how are they arranged? | Changes with application state |
| `DrawItem` | What should this traversal submit, and with which world transform? | Rebuilt from current scene state |

A `RenderObject` identifies reusable geometry and appearance. A `SceneNode`
references that object and supplies placement. Moving the node changes its
world transform without changing the mesh, material, or render-object
description.

That distinction is already useful for one triangle. It becomes essential when
several nodes instance one mesh, a parent moves a complete subtree, or an
importer constructs a hierarchy before any Vulkan device exists.

The dependency continues to point towards plain descriptions:

```text
SceneNode
    -> optional RenderObjectId
        -> RenderObject
            -> MeshId
            -> MaterialId

SceneNode
    -> local Mat4
    -> cached world Mat4
```

The scene stores IDs rather than pointers into `RenderAssets`. It does not own
the catalogue and cannot upload or destroy its resources. Validating that an ID
actually belongs to a supplied catalogue is intentionally deferred to the
preparation boundary.

## Let one scene own several roots

[`Scene`][source-scene-header] is the top-level owner:

```cpp
class Scene final
{
public:
    Scene() = default;
    ~Scene() = default;

    Scene(const Scene&) = delete;
    Scene& operator=(const Scene&) = delete;
    Scene(Scene&&) noexcept = default;
    Scene& operator=(Scene&&) noexcept = default;

    SceneNode& addRoot(std::unique_ptr<SceneNode> root);
    SceneNode& addRoot(std::string name);

    void updateWorldTransforms() noexcept;
    [[nodiscard]] SceneDrawList buildDrawItems() const;

    [[nodiscard]] const std::vector<std::unique_ptr<SceneNode>>& roots() const noexcept;

private:
    std::vector<std::unique_ptr<SceneNode>> roots_;
};
```

The scene is movable but not copyable. Copying a hierarchy would need a policy
for duplicating node identity and every owned subtree; release 0.7 has no use
for that operation. Moving transfers the existing ownership without inventing
a second scene.

Several roots are supported directly. Formats such as glTF define a scene as
an ordered list of root nodes, so fireEngine does not need to manufacture an
identity parent merely to force every imported hierarchy under one object.

Applications may supply an already allocated root or ask the scene to create a
named one. Both paths reach the same ownership operation:

```cpp
SceneNode& Scene::addRoot(std::unique_ptr<SceneNode> root)
{
    if (!root)
    {
        throw std::invalid_argument("A scene root cannot be null");
    }

    SceneNode& result = *root;
    roots_.push_back(std::move(root));
    return result;
}

SceneNode& Scene::addRoot(std::string name)
{
    return addRoot(std::make_unique<SceneNode>(std::move(name)));
}
```

The returned reference addresses the heap-allocated `SceneNode`, not the
`unique_ptr` stored in the vector. Growing `roots_` may move its smart pointers,
but it does not move the nodes they own. The API therefore documents that the
reference remains stable until the scene is destroyed.

Rejecting null at the ownership boundary keeps traversal simple. Once a root
has entered a `Scene`, later code can dereference every stored pointer without
repeating a defensive check.

## Make each node own its complete subtree

[`SceneNode`][source-scene-node-header] applies the same ownership rule below a
root. Its state keeps hierarchy, placement, and optional visual identity
together:

```cpp
std::string name_;                                 ///< Human-readable node name.
Mat4 localTransform_ = Mat4::identity();           ///< Transform relative to the parent.
Mat4 worldTransform_ = Mat4::identity();           ///< Cached resolved world transform.
std::optional<RenderObjectId> renderObject_;       ///< Optional visual attached to this node.
std::vector<std::unique_ptr<SceneNode>> children_; ///< Owned child hierarchy.
```

The name is for diagnostics and future importers; it is not an identity key.
Two nodes may have the same name, and traversal does not search by it.

Children follow the same two construction paths as roots:

```cpp
SceneNode& SceneNode::addChild(std::unique_ptr<SceneNode> child)
{
    if (!child)
    {
        throw std::invalid_argument("A scene child cannot be null");
    }

    SceneNode& result = *child;
    children_.push_back(std::move(child));
    return result;
}

SceneNode& SceneNode::addChild(std::string name)
{
    return addChild(std::make_unique<SceneNode>(std::move(name)));
}
```

Unique ownership makes the lifetime chain explicit. Destroying a scene destroys
its roots; destroying each root recursively destroys its children. It also
prevents one node from being inserted beneath two parents through the public
API. There is no parent pointer because the current operations need the
parent's resolved transform during traversal, not persistent upward navigation.

Like `Scene`, a node is movable but not copyable. Its default destructor can
delegate recursive cleanup to `std::unique_ptr` and `std::vector`.

The two matrices retain the 16-byte alignment established in the maths post.
Combining them with smaller standard-library members gives `SceneNode`
intentional padding, so the header scopes an MSVC C4324 suppression around the
class rather than weakening the matrix layout.

## Allow transform-only nodes

Not every useful point in a hierarchy has geometry. A parent may group several
objects, provide a shared transform, or reserve a named attachment point. The
render-object reference is therefore optional:

```cpp
[[nodiscard]] std::optional<RenderObjectId> renderObject() const noexcept;
void renderObject(RenderObjectId renderObject) noexcept;
void clearRenderObject() noexcept;
```

A node with no value still participates in transform resolution and child
traversal. It simply emits no draw item of its own. Attaching an ID makes the
node an instance; clearing it returns the node to a hierarchy-only role without
discarding its transform or children.

The optional distinguishes absence from an invalid ID. A present but
default-constructed `RenderObjectId` still contains the sentinel described in
the asset post and will be rejected when the scene and catalogue meet during
render preparation.

## Resolve transforms from roots towards leaves

Changing a local transform does not immediately walk the hierarchy. The
application first updates whichever nodes it needs, then asks the scene to
resolve all cached world transforms in one top-down pass:

```cpp
void Scene::updateWorldTransforms() noexcept
{
    for (const std::unique_ptr<SceneNode>& root : roots_)
    {
        root->resolve(Mat4::identity());
    }
}
```

Each root begins beneath the identity transform. A node combines the resolved
parent transform with its own local transform, then passes that result to every
child:

```cpp
void SceneNode::resolve(const Mat4& parentWorld) noexcept
{
    worldTransform_ = parentWorld * localTransform_;
    for (const std::unique_ptr<SceneNode>& child : children_)
    {
        child->resolve(worldTransform_);
    }
}
```

The maths post used this same function to establish composition order. Here,
the important point is when resolution runs and how the result propagates
through the owned hierarchy. The scene consumes that multiplication contract
rather than defining another one, so a parent's translation affects its
descendants while a child's local transform remains relative to that parent.

Caching `worldTransform_` makes later traversal a read-only operation. It also
makes update timing explicit: after changing any local transform, the cached
world values remain from the previous resolution until
`updateWorldTransforms()` runs again.

This implementation always visits the complete forest. Dirty flags and partial
subtree updates would add state and invalidation rules that one triangle does
not yet justify.

## Flatten one hierarchy into draw items

A renderer records a linear command stream, so it should not need to understand
tree ownership. Scene traversal emits one small value for every node with a
render object:

```cpp
struct DrawItem
{
    RenderObjectId renderObject;   ///< Prepared mesh/material relationship to draw.
    Mat4 world = Mat4::identity(); ///< Current object-to-world transform.
};
```

[`DrawItem`][source-draw-item] contains exactly the information that varies by
instance: which reusable render object to use and its current world transform.
It contains no mesh pointer, Vulkan buffer, pipeline, descriptor, or command
buffer.

Because `DrawItem` also embeds an aligned `Mat4` beside a smaller member, its
header scopes the same MSVC C4324 suppression around the structure.

The surrounding [`SceneDrawList`][source-scene-draw-list] adds one value used by
the next boundary:

```cpp
struct SceneDrawList
{
    std::vector<DrawItem> drawItems; ///< Current instances in depth-first scene order.
    std::size_t dependencyHash = 0;  ///< Hash of the ordered render-object dependencies.
};
```

The draw items are current frame data. The hash summarises the ordered asset
dependencies independently of their transforms. The scene still knows nothing
about how a consumer will turn either value into GPU resources.

## Preserve stable depth-first traversal

A node appends itself before visiting its children:

```cpp
void SceneNode::appendDrawItems(std::vector<DrawItem>& output) const
{
    if (renderObject_.has_value())
    {
        output.push_back({.renderObject = *renderObject_, .world = worldTransform_});
    }
    for (const std::unique_ptr<SceneNode>& child : children_)
    {
        child->appendDrawItems(output);
    }
}
```

`Scene::buildDrawItems()` applies that traversal to each root in insertion
order:

```cpp
SceneDrawList output;
for (const std::unique_ptr<SceneNode>& root : roots_)
{
    root->appendDrawItems(output.drawItems);
}
```

The result is a stable pre-order, depth-first list:

1. visit the first root;
2. emit it if it has a render object;
3. visit each of its child subtrees in insertion order; and
4. repeat for the remaining roots in insertion order.

Transform-only nodes do not appear in the output, but their children still do.
Two nodes that reference the same `RenderObjectId` produce two draw items with
independent world transforms. Nothing is deduplicated because those are two
instances even when their durable asset dependency is shared.

Stable order gives tests and future rendering policy a deterministic input. It
does not yet promise transparency sorting, material batching, frustum culling,
or any other optimisation that might deliberately reorder draws later.

## Hash dependencies without hashing movement

After collecting the draw items, the scene hashes their ordered
`RenderObjectId` sequence:

```cpp
constexpr std::size_t kHashCombineConstant = static_cast<std::size_t>(
    sizeof(std::size_t) == sizeof(std::uint64_t) ? hash::k64BitGoldenRatio
                                                 : hash::k32BitGoldenRatio);
output.dependencyHash = output.drawItems.size();
for (const DrawItem& drawItem : output.drawItems)
{
    const std::size_t value = std::hash<std::size_t>{}(drawItem.renderObject.value);
    output.dependencyHash ^= value + kHashCombineConstant + (output.dependencyHash << 6U) +
                             (output.dependencyHash >> 2U);
}
```

The loop locally reproduces the classic `boost::hash_combine` mixing expression
instead of adding Boost for one small operation. fireEngine also seeds it with
the list length before combining any IDs, making the number of dependencies
part of the input from the start. Mixing IDs in traversal order means `[A, B]`,
`[B, A]`, and `[A, A]` describe different inputs.

World transforms are deliberately absent. Moving an existing instance changes
the commands recorded for the current frame, but it does not require a new mesh
or material representation. Attaching, removing, or reordering render objects
does change the dependency input.

The constants in [`hash.hpp`][source-hash] provide the mixing expression with
an appropriately sized golden-ratio value for 32- or 64-bit `std::size_t`. The
result is a fast, non-cryptographic summary, not proof that two lists are equal.
The [render-preparation post][preparation-post] shows how preparation uses
the hash as a quick check while retaining the exact IDs needed to reject a
collision.

See the complete [`scene.cpp`][source-scene] and
[`scene_node.cpp`][source-scene-node].

## Make the application own assets and scene together

The application now owns reusable descriptions and the hierarchy that
instances them:

```cpp
struct TutorialContent
{
    fire_engine::RenderAssets assets; ///< Mesh, material, and render-object descriptions.
    fire_engine::Scene scene;         ///< Transform hierarchy referencing those descriptions.
};
```

These are adjacent owners rather than one owning the other. The scene contains
typed IDs, not references whose lifetime depends on vector storage. Destruction
therefore needs no Vulkan work and no recursive coordination with the asset
catalogue.

The [render-assets post][assets-post] covered construction of the triangle's
mesh, material, and render object. Once that work returns a `RenderObjectId`,
the scene-specific half of [`makeTriangleScene()`][source-main] is small:

```cpp
fire_engine::SceneNode& node = content.scene.addRoot("Tutorial triangle");
node.localTransform(fire_engine::Mat4::translation({.x = 0.12f, .y = 0.0f, .z = 0.0f}) *
                    fire_engine::Mat4::scale({.x = 0.9f, .y = 0.9f, .z = 1.0f}));
node.renderObject(triangle);
content.scene.updateWorldTransforms();
```

The triangle is a root because it has no parent in this tutorial scene. Its
render object supplies reusable content; its node supplies the transform. A
future loader can build deeper hierarchies with the same public operations.

The initial call resolves the scene's world transforms before returning. The
main loop repeats that update before every draw so later application-side
changes have an explicit point at which they become visible:

```cpp
content.scene.updateWorldTransforms();
const fire_engine::RenderResult result = renderer.drawFrame(content.scene);
```

`main()` does not build a Vulkan draw description. It updates ordinary scene
state and hands the scene to the renderer facade. How the renderer prepares and
records those draw items remains outside this post.

## Test hierarchy and traversal without a device

The testing post established the Catch2 executable. Scene behaviour contributes
three cases without creating a window or Vulkan device:

- parent and child transforms resolve correctly and emit draw items depth
  first;
- several roots retain stable insertion order; and
- null roots and children are rejected at their ownership boundaries.

The first case exercises ownership, transform propagation, optional instances,
and flattening together:

```cpp
TEST_CASE("Scene resolves transforms and emits draw items depth first")
{
    Scene scene;

    auto root = std::make_unique<SceneNode>("root");
    root->localTransform(Mat4::translation(Vec3{.x = 1.0f}));
    root->renderObject(RenderObjectId{.value = 0});

    auto child = std::make_unique<SceneNode>("child");
    child->localTransform(Mat4::translation(Vec3{.y = 2.0f}));
    child->renderObject(RenderObjectId{.value = 1});
    SceneNode& childReference = root->addChild(std::move(child));

    scene.addRoot(std::move(root));
    scene.updateWorldTransforms();

    REQUIRE(childReference.worldTransform()[0, 3] == 1.0f);
    REQUIRE(childReference.worldTransform()[1, 3] == 2.0f);

    const auto drawList = scene.buildDrawItems();
    REQUIRE(drawList.drawItems.size() == 2);
    REQUIRE(drawList.drawItems[0].renderObject == RenderObjectId{.value = 0});
    REQUIRE(drawList.drawItems[1].renderObject == RenderObjectId{.value = 1});
    REQUIRE(drawList.drawItems[1].world == childReference.worldTransform());
}
```

The child receives the root's x translation and its own y translation. The
same traversal then proves that the root draw precedes its child and that the
resolved matrix copied into the `DrawItem` matches the node's cached value.

The several-roots case is separate because a one-root hierarchy cannot prove
the forest contract. The null case checks both ownership entry points rather
than relying on a later traversal crash.

See the complete [`test_scene.cpp`][source-test-scene].

## Run the scene tests

Clone, configure, and build release 0.7 as described in the
[first 0.7 post][testing-post]. During focused scene work, CTest can select the
three directly relevant cases by their common prefix:

```shell
ctest --preset default -R "^Scene "
```

The anchored prefix selects exactly the three scene cases. Asset validation,
maths, render preparation, swapchain policy, SPIR-V loading, and the Vulkan
smoke test remain outside this focused run.

## Diagnose the new failure boundaries

The hierarchy moves scene mistakes into CPU-owned code, where their ownership
and transform contracts can be inspected directly.

### A root or child is rejected as null

Pass ownership of a real `SceneNode`, or use the named `addRoot()` and
`addChild()` overloads to construct one in place. Null entries are not retained
as empty hierarchy slots.

### A world transform remains stale after changing a node

`localTransform()` updates only the node's local value. Call
`updateWorldTransforms()` after application changes and before building or
drawing the current scene.

### A child moves in the wrong coordinate space

Check that resolution remains `parentWorld * localTransform`. Reversing those
operands changes the meaning under fireEngine's column-vector convention. The
[maths post][maths-post] contains the focused composition test.

### A node does not produce a draw item

Check whether it has an attached `RenderObjectId`. Transform-only nodes are
valid and deliberately omitted while their children continue to be traversed.
If an ID is present but invalid or out of range, render preparation will report
the catalogue mismatch.

### Draw items appear in an unexpected order

Traversal is pre-order and depth first. Roots and children retain insertion
order, and a visual node is emitted before any visual descendants. Release 0.7
does not sort by material, depth, or transparency.

### Moving an instance changes the dependency hash

Only the ordered `RenderObjectId` sequence belongs in the hash. Do not include
`DrawItem::world`: transform-only movement changes per-frame constants, not the
durable assets required to render the scene.

### A node must be shared by two parents

That relationship is outside this first scene model. Children have unique
ownership, so shared nodes and cycles cannot be expressed through its public
API. Instance the same `RenderObjectId` from two separate nodes when the intent
is to reuse render content with different placement.

## What this part of release 0.7 gives us

The first three 0.7 posts established testability, maths, and reusable render
descriptions. This fourth part adds the placement and traversal layer between
application content and rendering:

- scene-graph terminology has a precise meaning for this tutorial;
- `Scene` owns a movable, non-copyable forest with any number of roots;
- `SceneNode` owns one movable, non-copyable subtree;
- roots and children reject null ownership at their public boundaries;
- names support diagnostics without becoming identity keys;
- returned node references remain stable for the lifetime documented by their
  owner;
- local transforms default to identity and remain relative to the parent;
- world transforms are cached explicitly by a top-down update;
- transform-only nodes can group children without producing draws;
- visual nodes instance reusable render objects through typed IDs;
- traversal emits a flat Vulkan-free `DrawItem` for every visual instance;
- roots and children produce a deterministic pre-order, depth-first sequence;
- repeated render-object IDs remain separate instances;
- the dependency hash includes ordered render-object identity but excludes
  world transforms;
- application code owns `RenderAssets` and `Scene` side by side; and
- three focused Catch2 cases verify hierarchy, traversal, multiple roots, and
  invalid ownership without a device.

The draw list still does not say which meshes and materials need durable GPU
representations, whether those representations can be reused, or how scene
references are checked before indexing the asset catalogue. The
[render-preparation post][preparation-post] makes that boundary explicit by
turning the scene's current draws into a render-preparation plan.

## Recommended reading

- [Game Engine Architecture][reading-game-engine-architecture] — Jason
  Gregory's broad treatment of scene management, object models, resource
  ownership, and the boundaries between application state and rendering.
- [Foundations of Game Engine Development, Volume 1: Mathematics][reading-foundations] —
  Eric Lengyel's focused treatment of transforms and the composition rules
  behind parent-child hierarchies.
- [glTF 2.0 specification: Scenes and Nodes][reading-gltf-scenes] — the Khronos
  definition of scenes, ordered root nodes, child hierarchies, and local
  transforms that informs fireEngine's forest-shaped model.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[maths-post]: {% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %}
[assets-post]: {% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %}
[preparation-post]: {% post_url 2026-08-16-preparing-fireengines-scene-data-explicitly %}
[source-hash]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/core/hash.hpp>
[source-draw-item]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/graphics/draw_item.hpp>
[source-scene-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/scene/scene.hpp>
[source-scene-node-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/scene/scene_node.hpp>
[source-scene-draw-list]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/scene/scene_draw_list.hpp>
[source-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/scene/scene.cpp>
[source-scene-node]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/scene/scene_node.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/main.cpp>
[source-test-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/scene/test_scene.cpp>
[reading-game-engine-architecture]: <https://www.gameenginebook.com/>
[reading-foundations]: <https://foundationsofgameenginedev.com/#fged1>
[reading-gltf-scenes]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#scenes>
[reading-page]: {% link _tabs/reading.md %}
