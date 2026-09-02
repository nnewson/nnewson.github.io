---
title: "Giving fireEngine's imported transforms enough vocabulary"
date: 2026-08-22 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", maths, transforms, quaternions, scene-graph, gltf, cpp]
description: >-
  Extend fireEngine with robust vector normalisation, quaternion rotation,
  decomposed TRS transforms, Vulkan camera matrices, and stable scene-node IDs.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.7 gave fireEngine just enough maths to position its tutorial triangle.
`Vec3` and `Vec4` represented coordinates, while a column-major `Mat4` supplied
identity, translation, scale, composition, and the CPU/shader layout shared by
the first scene graph.

An imported glTF scene asks more of that vocabulary. Texture coordinates need
two components. Nodes can rotate as well as translate and scale. Animation must
change one transform channel without first recovering it from a matrix. The
camera also needs view and projection conventions that agree with Vulkan before
any geometry is culled or drawn.

Release 0.8 supplies those contracts through `Vec2`, robust `Vec3`
normalisation, quaternions, decomposed TRS transforms, camera matrices, and
stable scene-local node identities. The loader, animation system, camera, and
renderer all consume this vocabulary; this article concentrates on the maths
and scene-identity layer they share.

This is the first detailed post based on release 0.8. The
[architectural overview][planning-post] describes the complete path from the
structured triangle to AnimatedCube. The code and commands below target the
completed [fireEngine 0.8 release][release-0-8], while keeping the discussion
focused on imported transforms.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> Start with [Growing fireEngine into an animated glTF renderer][planning-post]
> for the release plan. This post examines the mathematical and scene-identity
> vocabulary used by imported transforms throughout version 0.8.
{: .prompt-info }

## Extend the existing layer instead of replacing it

The release 0.7 maths types already fixed the important representation rules:

- matrices multiply column vectors written on their right;
- transform composition is evaluated from right to left;
- matrices use column-major storage;
- `parentWorld * local` resolves scene hierarchy; and
- a `Mat4` crosses the Slang boundary without transposition or repacking.

Release 0.8 keeps those choices while extending the public CPU layer, scene
resolution, import path, animation playback, and device-free tests around them:

```text
include/fire_engine/
├── math/
│   ├── mat4.hpp
│   ├── normalize_error.hpp
│   ├── quaternion.hpp
│   ├── transform.hpp
│   ├── vec2.hpp
│   └── vec3.hpp
└── scene/
    ├── scene.hpp
    ├── scene_node.hpp
    └── scene_node_id.hpp

src/
├── main.cpp
└── scene/
    ├── scene.cpp
    └── scene_node.cpp

tests/
├── graphics/
│   └── test_render_preparation.cpp
├── math/
│   └── test_mat4.cpp
└── scene/
    └── test_scene.cpp
```

The new types remain Vulkan-free. They can be populated by an importer, changed
by animation, resolved by the scene, and tested without creating a window or a
device.

## Add the two-component value the next asset step needs

glTF texture coordinates arrive as pairs. `Vec3` would store a spare component
and blur the distinction between a position and a UV value, so the maths layer
adds the smallest matching aggregate:

```cpp
struct Vec2
{
    float x = 0.0f;
    float y = 0.0f;

    [[nodiscard]] constexpr bool operator==(const Vec2&) const noexcept = default;
};
```

`Vec2{}` is predictably zero, designated initialisers keep both components
visible, and exact equality has the same limited role as it does for `Vec3` and
`Vec4`: values copied from the same source can be compared directly, while
results of floating-point arithmetic need a tolerance.

In release 0.8, `Vertex::textureCoordinate` uses `Vec2` directly. Keeping the
pair as a small maths aggregate lets mesh descriptions and the glTF loader
share it without exposing a parser or graphics-API type.

See [`vec2.hpp`][source-vec2].

## Give three-component vectors geometric operations

The original `Vec3` only stored components. Building a camera basis requires
subtraction, dot and cross products, a squared length, and normalisation, so the
type gains that focused set rather than becoming a general vector library.

The right-handed cross product establishes the orientation used by the later
view matrix:

```cpp
[[nodiscard]] constexpr Vec3 cross(Vec3 right) const noexcept
{
    return {
        .x = y * right.z - z * right.y,
        .y = z * right.x - x * right.z,
        .z = x * right.y - y * right.x,
    };
}
```

`lengthSquared()` retains the direct dot product for comparisons that do not
need a square root:

```cpp
[[nodiscard]] constexpr float lengthSquared() const noexcept
{
    return dot(*this);
}
```

That fast operation is not used as the route to normalisation. Squaring very
large finite components can overflow to infinity, while squaring very small
ones can underflow to zero. A vector that was finite and non-zero would then be
misclassified before division even began.

## Report normalisation failure as a value

Normalisation has two recoverable failure categories in release 0.8:

```cpp
enum class NormalizeError : std::uint8_t
{
    eZeroLength,
    eNonFinite,
};
```

A zero vector has no direction. A non-finite magnitude cannot produce a useful
unit vector. `Vec3::normalized()` returns either the unit value or one of those
reasons through C++23 `std::expected`:

```cpp
[[nodiscard]] std::expected<Vec3, NormalizeError> normalized() const noexcept
{
    // hypot is slower than sqrt(lengthSquared()), but avoids its avoidable overflow and
    // underflow. Normalization favors accuracy; lengthSquared() remains the faster comparison.
    const float magnitude = std::hypot(x, y, z);
    if (magnitude == 0.0f)
    {
        return std::unexpected{NormalizeError::eZeroLength};
    }
    if (!std::isfinite(magnitude))
    {
        return std::unexpected{NormalizeError::eNonFinite};
    }
    return Vec3{.x = x / magnitude, .y = y / magnitude, .z = z / magnitude};
}
```

`std::hypot` scales its calculation to avoid the avoidable intermediate
overflow and underflow of `sqrt(x * x + y * y + z * z)`. The operation is a
little more expensive than the direct sum, but normalisation favours a stable
answer while `lengthSquared()` remains available for ordinary comparisons.

`std::expected` makes failure part of the function's type without requiring
dynamic allocation, logging, throwing, or an invented fallback direction.
Callers decide whether a degenerate runtime value should be rejected, repaired,
or propagated.

See [`normalize_error.hpp`][source-normalize-error] and
[`vec3.hpp`][source-vec3].

## Store rotations in glTF component order

glTF stores quaternion rotations as `(x, y, z, w)`: three imaginary components
followed by the real component. fireEngine adopts the same public order so a
loader will not need to shuffle fields at the boundary:

```cpp
struct Quaternion
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 1.0f;

    [[nodiscard]] static constexpr Quaternion identity() noexcept
    {
        return {};
    }

    // Normalisation, interpolation, dot product, negation, and equality follow.
};
```

The default value is the identity rotation rather than an all-zero quaternion.
That makes a default `Transform` useful immediately and avoids requiring every
scene-node constructor to repeat the neutral rotation.

Quaternion normalisation uses the same `NormalizeError` domain as `Vec3`. Four
components require pairwise `std::hypot` calls:

```cpp
const float magnitude = std::hypot(std::hypot(x, y), std::hypot(z, w));
if (magnitude == 0.0f)
{
    return std::unexpected{NormalizeError::eZeroLength};
}
if (!std::isfinite(magnitude))
{
    return std::unexpected{NormalizeError::eNonFinite};
}
return Quaternion{
    .x = x / magnitude,
    .y = y / magnitude,
    .z = z / magnitude,
    .w = w / magnitude,
};
```

The public value can therefore represent imported components exactly, while
the operation that needs a unit quaternion reports when those components do not
define a usable rotation.

## Interpolate equivalent rotations along the short arc

A quaternion and its negation encode the same spatial rotation. Treating their
four stored components as unrelated endpoints can nevertheless interpolate the
long way around, or pass through the zero quaternion when the endpoints are
opposites.

`normalizedLerp()` checks the dot product first. A negative result means the
two values lie on opposite quaternion hemispheres, so negating the right value
selects the equivalent endpoint on the shorter arc:

```cpp
[[nodiscard]] std::expected<Quaternion, NormalizeError>
normalizedLerp(Quaternion right, float amount) const noexcept
{
    if (dot(right) < 0.0f)
    {
        right = -right;
    }

    return Quaternion{
        .x = x + (right.x - x) * amount,
        .y = y + (right.y - y) * amount,
        .z = z + (right.z - z) * amount,
        .w = w + (right.w - w) * amount,
    }
        .normalized();
}
```

Linear interpolation does not preserve unit length, so the result is
normalised before it is returned. The `amount` is normally between zero and
one, but this function does not clamp it; choosing the playback interval and
interpolation amount belongs to the animation playback layer.

This is normalised linear interpolation rather than spherical interpolation.
It is sufficient for the selected 0.8 animation and gives playback one small,
tested rotation operation instead of embedding quaternion policy in an
animation class.

See [`quaternion.hpp`][source-quaternion].

## Preserve translation, rotation, and scale as source values

Release 0.7 stored a node's local transform only as a `Mat4`. That was enough
when the application composed one translation and scale once, but it is a poor
source representation for animation. Updating one imported rotation channel
would require retaining the original TRS values elsewhere or decomposing the
matrix back into them every frame.

`Transform` keeps the three channels explicit:

```cpp
struct Transform
{
    Vec3 translation{};
    Quaternion rotation = Quaternion::identity();
    Vec3 scale{.x = 1.0f, .y = 1.0f, .z = 1.0f};

    [[nodiscard]] constexpr Mat4 matrix() const noexcept
    {
        return Mat4::translation(translation) * Mat4::rotation(rotation) * Mat4::scale(scale);
    }

    [[nodiscard]] constexpr bool operator==(const Transform&) const noexcept = default;
};
```

Its default is the identity transform: zero translation, identity rotation, and
unit scale. `matrix()` composes glTF's TRS order. Because matrices multiply
column vectors on their right, a point is scaled first, then rotated, then
translated.

`Mat4::rotation()` converts the unit quaternion into the existing column-major
matrix representation. It deliberately accepts the public value directly and
documents that the quaternion is normalised; it does not hide another
normalisation or error path inside a `constexpr`, `noexcept` matrix factory.

See [`transform.hpp`][source-transform] and the rotation factory in
[`mat4.hpp`][source-mat4].

## Keep source transforms separate from resolved matrices

`SceneNode` now owns both representations, but for different reasons:

```cpp
std::string name_;
std::optional<SceneNodeId> id_;
Transform localTransform_;
Mat4 worldTransform_ = Mat4::identity();
std::optional<RenderObjectId> renderObject_;
std::vector<std::unique_ptr<SceneNode>> children_;
```

The local `Transform` is editable source state. The world `Mat4` is derived
state cached for drawing. Resolution converts TRS only when it walks the scene:

```cpp
void SceneNode::resolve(const Mat4& parentWorld) noexcept
{
    worldTransform_ = parentWorld * localTransform_.matrix();
    for (const std::unique_ptr<SceneNode>& child : children_)
    {
        child->resolve(worldTransform_);
    }
}
```

This preserves the 0.7 hierarchy rule. Animation playback can replace a node's
rotation without changing its translation or scale, then the ordinary world
update rebuilds the matrices consumed by draw traversal. No renderer or render
asset needs to know which channel changed.

See [`scene_node.hpp`][source-scene-node-header] and
[`scene_node.cpp`][source-scene-node].

## Fix camera conventions at the maths boundary

The release 0.8 camera uses matrix operations defined in the maths layer, where
their coordinate rules can be tested without a renderer or device.

`Mat4::lookAt()` builds a right-handed view matrix. It normalises the direction
from `eye` to `target`, derives a right vector from the supplied up direction,
and reconstructs an orthogonal camera-up vector:

```cpp
const std::expected<Vec3, NormalizeError> forwardResult = (target - eye).normalized();
if (!forwardResult)
{
    return std::unexpected{forwardResult.error()};
}

const Vec3 forward = *forwardResult;
const std::expected<Vec3, NormalizeError> rightResult = forward.cross(up).normalized();
if (!rightResult)
{
    return std::unexpected{rightResult.error()};
}

const Vec3 right = *rightResult;
const Vec3 cameraUp = right.cross(forward);
```

Equal eye and target positions have no forward direction. An up vector parallel
to the viewing direction cannot produce a right vector. Those are plausible
runtime camera states, so `lookAt()` returns
`std::expected<Mat4, NormalizeError>` rather than fabricating a basis.

Perspective configuration has a different failure boundary. A non-finite field
of view, aspect ratio, or clipping distance, a field of view outside zero to
pi, a non-positive aspect ratio or near plane, or a far plane no farther than
the near plane is rejected with `std::invalid_argument`. These are setup errors
rather than momentary geometric degeneracies.

The resulting projection fixes two Vulkan-facing conventions explicitly:

```cpp
const float focalLength = 1.0f / std::tan(verticalFieldOfView * 0.5f);
Mat4 result;
result[0, 0] = focalLength / aspectRatio;
// A positive-height Vulkan viewport maps positive NDC Y downward. Flip here so the
// projection retains the conventional view-space direction where positive Y is up.
result[1, 1] = -focalLength;
result[2, 2] = farPlane / (nearPlane - farPlane);
result[2, 3] = farPlane * nearPlane / (nearPlane - farPlane);
result[3, 2] = -1.0f;
return result;
```

Right-handed view space looks along negative Z. After perspective division, the
near plane maps to depth zero and the far plane to one. Negating the Y scale in
the projection compensates for a positive-height Vulkan viewport, keeping
positive view-space Y visually upward.

These choices remain ordinary maths tests. The renderer decides when to build
and upload the camera matrix, but it does not own the conventions encoded by
the maths type.

See the camera factories in [`mat4.hpp`][source-mat4].

## Give scenes stable node identities

Scene tools and systems need a stable way to find a node after loading. Names
are diagnostic text and need not be unique. Traversal positions can shift as
hierarchies grow. Memory addresses are awkward public keys and would expose
ownership details to callers.

`SceneNodeId` follows the typed-ID pattern already used by render assets:

```cpp
struct SceneNodeId
{
    std::size_t value = std::numeric_limits<std::size_t>::max();

    [[nodiscard]] constexpr bool valid() const noexcept
    {
        return value != std::numeric_limits<std::size_t>::max();
    }

    [[nodiscard]] constexpr bool operator==(const SceneNodeId&) const noexcept = default;
};
```

The value is a dense index owned by one `Scene`. The scene keeps the lookup
table that gives it meaning:

```cpp
std::vector<std::unique_ptr<SceneNode>> roots_;
std::vector<SceneNode*> nodes_;
```

Registered nodes must remain at stable addresses, so `SceneNode` remains
non-copyable and becomes non-movable. Moving a `unique_ptr` while its owning
vector grows does not move the node it points to, and the append-only hierarchy
offers no node-removal operation that could leave a dangling lookup entry.

`findNode()` returns an optional reference rather than transferring ownership:

```cpp
std::optional<SceneNodeRef> Scene::findNode(SceneNodeId id) noexcept
{
    if (!id.valid() || id.value >= nodes_.size())
    {
        return std::nullopt;
    }
    return std::ref(*nodes_[id.value]);
}
```

C++23 has no `std::optional<T&>`, so `SceneNodeRef` and `SceneNodeConstRef`
isolate the `std::reference_wrapper` substitute. Mutable and const overloads
retain the scene's ownership while letting callers update a found node or
inspect it read-only.

See [`scene_node_id.hpp`][source-scene-node-id] and
[`scene.hpp`][source-scene-header].

## Register complete subtrees without changing traversal identity

Adding a root registers its detached subtree immediately. The registration walk
is pre-order, appending each previously unregistered node it encounters to the
dense lookup:

```cpp
void Scene::registerSubtree(SceneNode& node)
{
    if (!node.id().has_value())
    {
        node.assignId(SceneNodeId{.value = nodes_.size()});
        nodes_.push_back(&node);
    }

    for (const std::unique_ptr<SceneNode>& child : node.children())
    {
        registerSubtree(*child);
    }
}
```

Calling the function again skips nodes that already have IDs, so repeated world
updates do not renumber animation targets. Invalid-sentinel and out-of-range
IDs return no node.

There is one deliberate looseness in release 0.8. A child added after its root
has entered the scene does not receive an ID at mutation time. The next
`updateWorldTransforms()` discovers and registers it before resolving the
hierarchy:

```cpp
void Scene::updateWorldTransforms()
{
    for (const std::unique_ptr<SceneNode>& root : roots_)
    {
        registerSubtree(*root);
        root->resolve(Mat4::identity());
    }
}
```

That registration can grow `nodes_`, so the function is no longer `noexcept`.
Code that needs a newly added child's ID must run the world update first. A
stricter mutation-time registration invariant remains later work.

`SceneNodeId` is also scene-local by contract rather than by encoded provenance.
An in-range ID copied from another scene can name the same dense slot in this
one. Callers must therefore retain the owning scene alongside the ID instead of
treating it as a process-wide identity.

See the complete [`scene.cpp`][source-scene].

## Carry TRS from loading into animation

The final 0.8 application loads AnimatedCube rather than constructing a
triangle. `GltfLoader` converts each selected glTF node into a decomposed
`Transform`, preserving translation, normalised rotation, and scale as
independent source values.

Animation playback can then replace only the rotation:

```cpp
Transform transform = node.localTransform();
transform.rotation = sampleRotation(channel, animator.playbackTime);
node.localTransform(transform);
```

The frame loop calls `updateWorldTransforms()` afterwards, resolving the
current local TRS values into the matrices used for drawing. Neither animation
nor ordinary movement changes the asset revision or render-object dependency
list, so prepared GPU resources remain reusable while the cube rotates.

See [`gltf_loader.cpp`][source-gltf-loader] and
[`animation_playback.cpp`][source-animation-playback].

## Test the new contracts without a device

The release's device-free tests cover quaternion operations, numerical
stability, TRS composition, camera conventions, scene identities, and the
`Vec2` aggregate contract.

The magnitude test uses values that expose the difference between robust
normalisation and a direct sum of squares:

```cpp
constexpr float kTiny = 1.0e-30f;
constexpr float kLarge = 1.0e20f;

const auto tinyVector = Vec3{.x = kTiny, .y = 0.0f, .z = 0.0f}.normalized();
REQUIRE(tinyVector.has_value());
REQUIRE(*tinyVector == Vec3{.x = 1.0f, .y = 0.0f, .z = 0.0f});

const auto largeVector = Vec3{.x = kLarge, .y = kLarge, .z = kLarge}.normalized();
REQUIRE(largeVector.has_value());
REQUIRE(largeVector->lengthSquared() == Approx(1.0f));
```

The quaternion case checks identity normalisation, a halfway rotation, the
shortest path to an equivalent negated identity, zero length, and non-finite
input. The TRS case proves that scale, rotation, and translation apply in that
order.

The camera case fixes the conventions numerically: near depth is zero, far
depth is one, projection flips Y, and an origin viewed from positive Z lands at
negative view-space Z. It also distinguishes invalid perspective configuration
from a recoverable degenerate view basis.

The scene case proves immediate root registration, delayed child registration,
stable IDs across repeated updates, invalid and out-of-range rejection, mutable
lookup, and const lookup. Existing scene and preparation cases migrate to
`Transform` as well, preserving their hierarchy and cache assertions.

See the complete [`test_mat4.cpp`][source-test-mat4],
[`test_scene.cpp`][source-test-scene], and
[`test_render_preparation.cpp`][source-test-preparation].

## Run the transform and identity tests

Configure and build release 0.8 through its vcpkg preset. CTest can select six
focused transform and identity cases by their anchored prefixes:

```shell
ctest --preset default -R "^(Vector aggregates|Quaternion normalization|Normalization remains|Transform composes|Mat4 camera|Scene assigns)"
```

The filter selects those six cases in release 0.8. The remaining maths, scene,
asset, loading, animation, rendering, and Vulkan scenarios remain outside the
focused run.

## Diagnose the new failure boundaries

The new vocabulary makes numerical and identity failures explicit, but each
still needs to be interpreted at the layer that owns it.

### A finite non-zero value fails normalisation

Check that the implementation uses `std::hypot`, not
`sqrt(lengthSquared())`. The direct sum can underflow or overflow before the
square root even when the original components are finite and normalisable.

### Normalisation returns `eZeroLength` or `eNonFinite`

Do not substitute an arbitrary direction silently. Zero length means the input
has no direction; non-finite means at least one component produced an unusable
magnitude. Let the importer, camera, or animation caller decide how that source
should fail.

### Quaternion interpolation rotates the long way around

Check the sign of the endpoint dot product. When it is negative, negate the
right quaternion before interpolation; the negated value represents the same
rotation on the nearer hemisphere. Normalise the interpolated result as well.

### A quaternion matrix stretches or shears geometry

`Mat4::rotation()` expects a unit quaternion and does not normalise internally.
Normalise imported or calculated input before asking for its matrix, and handle
the possible `NormalizeError` at that boundary.

### Translation or rotation happens in the wrong order

The local convention is `translation * rotation * scale`. With column vectors
written on the right, scale applies first, then rotation, then translation.
Changing the multiplication order changes the transform rather than its style.

### The camera is upside down or depth leaves the zero-to-one range

Keep the negative projection Y scale used with fireEngine's positive-height
Vulkan viewport, and retain the Vulkan depth coefficients. OpenGL-style
negative-one-to-one depth or a second Y flip will violate the tested contract.

### `lookAt()` cannot build a basis

Check whether eye equals target or the supplied up vector is parallel to the
view direction. Either makes one required direction zero-length. Choose a
different target or up vector rather than hiding the degeneracy inside the
matrix.

### A newly added child has no `SceneNodeId`

In release 0.8, adding a child beneath an already registered node does not
register it immediately. Call `updateWorldTransforms()` before requesting its
ID. Roots and complete detached subtrees passed to `addRoot()` are registered
at once.

### A valid-looking ID finds the wrong scene's node

`SceneNodeId` is a dense scene-local index, not a globally unique handle. Keep
it associated with the `Scene` that assigned it. The value alone cannot detect
that it came from another scene when both scenes contain the same slot.

## What this part of release 0.8 gives us

The 0.8 overview established the path to one imported, textured, animated
scene. This part of the release supplies the values and identities shared by
that path:

- `Vec2` represents the two-component coordinates needed by textured meshes;
- `Vec3` gains subtraction, dot, right-handed cross, squared-length, and
  normalisation operations without becoming a general-purpose maths package;
- `NormalizeError` distinguishes zero-length from non-finite input;
- C++23 `std::expected` keeps recoverable numerical failure in the return type;
- `std::hypot` keeps finite extreme magnitudes normalisable;
- `Quaternion` uses glTF's `(x, y, z, w)` component order and defaults to
  identity;
- shortest-arc normalised linear interpolation becomes one tested maths
  operation rather than animation-owned policy;
- `Transform` retains translation, rotation, and scale as independently
  editable source values;
- TRS composition preserves fireEngine's column-vector and column-major matrix
  conventions;
- scene traversal resolves decomposed local values into cached world matrices;
- right-handed look-at reports degenerate runtime bases explicitly;
- perspective validates setup and fixes Vulkan's zero-to-one depth and Y
  direction;
- `SceneNodeId` gives callers a typed, stable, scene-local lookup key;
- dense lookup returns optional mutable or const references without transferring
  ownership;
- nodes become immovable so registered pointer identity remains stable;
- world updates discover descendants added after initial scene registration;
- the glTF loader preserves imported TRS values in this shared vocabulary; and
- animation playback changes rotation without rebuilding stable resources.

The rest of release 0.8 builds on these contracts. The
[descriptions post][descriptions-post] concentrates on Vulkan-free texture and
animation descriptions, while the loader, camera, playback, and renderer remain
consumers of the same maths and scene model.

## Recommended reading

- [Foundations of Game Engine Development, Volume 1: Mathematics][reading-foundations] —
  Eric Lengyel's focused treatment of vectors, quaternions, matrices, and
  transform composition in a game-engine context.
- [Real-Time Rendering][reading-real-time-rendering] — the broader rendering
  reference for transform hierarchies, viewing, projection, interpolation, and
  the conventions that connect CPU maths to the graphics pipeline.
- [glTF 2.0 specification: Transformations][reading-gltf-transforms] — the Khronos
  definition of node TRS properties, matrix composition, hierarchy, and the
  transform rules an importer must preserve.
- [C++ `std::expected`][reading-cpp-expected] — cppreference's description of
  the C++23 vocabulary type used to return either a normalised value or a small
  recoverable error.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[descriptions-post]: {% post_url 2026-08-23-extending-fireengines-descriptions-without-introducing-vulkan %}
[source-normalize-error]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/normalize_error.hpp>
[source-quaternion]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/quaternion.hpp>
[source-transform]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/transform.hpp>
[source-vec2]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/vec2.hpp>
[source-vec3]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/vec3.hpp>
[source-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/mat4.hpp>
[source-scene-node-id]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/scene/scene_node_id.hpp>
[source-scene-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/scene/scene.hpp>
[source-scene-node-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/scene/scene_node.hpp>
[source-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/scene/scene.cpp>
[source-scene-node]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/scene/scene_node.cpp>
[source-gltf-loader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/gltf/gltf_loader.cpp>
[source-animation-playback]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/animation/animation_playback.cpp>
[source-test-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/math/test_mat4.cpp>
[source-test-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/scene/test_scene.cpp>
[source-test-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/graphics/test_render_preparation.cpp>
[reading-foundations]: <https://foundationsofgameenginedev.com/#fged1>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-gltf-transforms]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#transformations>
[reading-cpp-expected]: <https://en.cppreference.com/w/cpp/utility/expected.html>
[reading-page]: {% link _tabs/reading.md %}
