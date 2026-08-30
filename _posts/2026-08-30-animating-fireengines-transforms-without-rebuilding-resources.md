---
title: "Animating fireEngine's transforms without rebuilding resources"
date: 2026-08-30 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, animation, transforms, quaternions, scene-graph, caching, gltf, cpp]
description: >-
  Advance imported rotation channels into current scene transforms while
  keeping render preparation and compiled GPU resources unchanged.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

Release 0.8 can load AnimatedCube as a hierarchy, retain its reusable rotation
samples, and render the selected mesh through a textured, depth-tested Vulkan
pipeline. The remaining step is to make those samples affect what a frame
draws.

That sounds like a small interpolation problem. It is also an architectural
test. Animation changes a node's transform continually, while meshes,
materials, textures, and their device allocations usually remain exactly the
same. Treating every new matrix as a resource change would make the renderer
rebuild stable GPU state once per frame. Treating animation samples as mutable
node state would instead duplicate reusable source data and make two instances
of one clip difficult to advance independently.

Release 0.8 keeps the two concerns separate. An `AnimationChannel` owns
target-independent samples. An `Animator` binds one channel to one scene node
and owns its playback position. `advanceAnimations()` samples that binding into
the node's CPU-side local rotation, after which ordinary scene traversal
resolves a new world transform for drawing. Neither the asset revision nor the
ordered render-object dependencies changes, so preparation and compiled Vulkan
resources stay put while the cube turns.

This detailed post is based on release 0.8. The
[architectural overview][planning-post] describes the complete release. The
[descriptions post][descriptions-post] introduces the animation data and scene
binding, while the [transforms post][transforms-post] establishes the
quaternion operations used to sample it.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> The [descriptions post][descriptions-post] covers reusable animation data and
> `Animator` bindings. This post advances those bindings into current scene
> transforms without turning movement into a resource rebuild.
{: .prompt-info }

## Keep samples separate from playback state

An imported channel answers a reusable question: which rotations were sampled
at which times? It does not say which scene instance is currently playing it,
whether that instance loops, or where its clock has reached:

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

That runtime state belongs to the scene binding instead:

```cpp
struct Animator
{
    AnimationId animation;
    AnimationChannelId channel;
    AnimationTargetPath targetPath = AnimationTargetPath::eRotation;
    float playbackTime = 0.0f;
    bool looping = true;
};
```

The resulting split has three distinct responsibilities:

| Type | Owns | Changes during playback? |
| --- | --- | --- |
| `AnimationChannel` | ordered timestamps and quaternion samples | no |
| `Animator` | channel binding, playback time, and looping policy | yes |
| `SceneNode::localTransform()` | the node's current translation, rotation, and scale | rotation does |

Two nodes can therefore reference the same animation and channel while keeping
different playback times or looping policies. Shared samples remain immutable;
instance state does not leak back into imported content.

The imported hierarchy makes the ownership visible:

```text
animated source node -> Animator
└── primitive child  -> RenderObjectId
```

The `Animator` changes the source node's local transform. Its primitive child
inherits that transform during world resolution and continues to identify the
same render object. Animation behavior and render identity occupy different
nodes because `SceneComponent` gives each node one explicit role.

See [`animation.hpp`][source-animation] and
[`animator.hpp`][source-animator].

## Put playback behind one scene operation

The public playback operation accepts the mutable hierarchy, the reusable
animation table, and the elapsed time since the previous update:

```cpp
void advanceAnimations(Scene& scene,
                       std::span<const Animation> animations,
                       float elapsedSeconds);
```

It deliberately does not accept a renderer, device, asset catalogue, or clock.
Its whole data flow remains on the CPU side of the renderer boundary:

```text
AnimationChannel samples + Animator state
                  |
                  v
          advanceAnimations()
                  |
                  v
       SceneNode local rotation
                  |
                  v
        updateWorldTransforms()
                  |
                  v
        current DrawItem.world
```

The caller supplies time because measuring time is application policy. A game
might pause, scale, replay, or drive simulation with a fixed step. The small
tutorial application uses wall-clock frame duration for interactive playback
and a fixed value for its bounded smoke scenario. The animation operation need
not know which policy produced the number.

Its precondition is equally narrow. `elapsedSeconds` must be finite and
non-negative:

```cpp
if (!std::isfinite(elapsedSeconds) || elapsedSeconds < 0.0f)
{
    throw std::invalid_argument(
        "Animation elapsed time must be finite and non-negative");
}
```

A negative delta would run a forward-only policy backwards. NaN or infinity
would poison playback time and every later interpolation. Rejecting all three
at the entry point keeps the recursive update from partially changing a scene.

The animation table and bindings are expected to have passed content
validation before playback begins. The update still checks referenced IDs,
the supported target path, and the channel's basic shape defensively, but it
does not revalidate every timestamp and quaternion on every frame. Expensive
content invariants belong at the loading boundary; inexpensive state changes
belong in the frame loop.

See [`animation_playback.hpp`][source-playback-header],
[`animation_playback.cpp`][source-playback-cpp], and the validation boundary in
[`animation_validation.cpp`][source-animation-validation].

## Measure frame time without putting a clock in the engine

The normal application measures elapsed time with a monotonic clock:

```cpp
auto previousFrameTime = std::chrono::steady_clock::now();
while (!window.shouldClose())
{
    window.pollEvents();

    const auto currentFrameTime = std::chrono::steady_clock::now();
    const float elapsedSeconds =
        std::chrono::duration<float>{
            currentFrameTime - previousFrameTime}.count();
    previousFrameTime = currentFrameTime;

    fire_engine::advanceAnimations(
        content.scene, content.animations, elapsedSeconds);
    content.scene.updateWorldTransforms();
    renderer.drawFrame(content.scene);
}
```

`steady_clock` cannot move backwards as the system wall clock is corrected, so
its difference is suitable for measuring an interval. The duration is converted
to seconds at the application boundary because the imported timestamps and
`Animator::playbackTime` use seconds too.

This is variable-step visual playback, not a claim to be a complete game-loop
time model. Simulation that needs reproducibility, bounded catch-up, or exact
synchronisation would normally separate its simulation clock from rendering.
Keeping the clock outside `advanceAnimations()` leaves that choice open.

The ordering inside the frame matters more immediately:

```text
measure elapsed time
        |
        v
advance local rotations
        |
        v
resolve world transforms
        |
        v
build current draw items and record the frame
```

Resolving before playback would leave this frame's draw list with yesterday's
world matrix. Omitting resolution would update the local rotation correctly but
never propagate it to the renderable primitive child.

See the application loop in [`main.cpp`][source-main].

## Traverse every animator in hierarchy order

`advanceAnimations()` starts at each scene root and recursively visits the
complete forest:

```cpp
for (const std::unique_ptr<SceneNode>& root : scene.roots())
{
    advanceSubtree(*root, animations, elapsedSeconds);
}
```

Each subtree advances its current node before visiting its children:

```cpp
void advanceSubtree(SceneNode& node,
                    std::span<const Animation> animations,
                    float elapsedSeconds)
{
    advanceAnimator(node, animations, elapsedSeconds);
    for (const std::unique_ptr<SceneNode>& child : node.children())
    {
        advanceSubtree(*child, animations, elapsedSeconds);
    }
}
```

This traversal does not resolve matrices as it goes. Every animator writes
local state first; the following `updateWorldTransforms()` pass then computes
the hierarchy consistently from the roots downward. Keeping mutation and
resolution as two visible operations avoids mixing animation sampling with
scene-graph mathematics.

Most nodes do no work in this pass. `std::get_if<Animator>()` tests the node's
component role and returns immediately for render objects and empty nodes. A
scene can therefore combine structural, animated, and renderable nodes without
a parallel animation-only hierarchy.

## Advance every binding independently

Once an `Animator` is found, playback copies its state, resolves its typed IDs,
and selects the referenced channel:

```cpp
Animator animator = *component;
const Animation& animation = animations[animator.animation.value];
const AnimationChannel& channel =
    animation.channels[animator.channel.value];
```

The channel remains shared and read-only. Only the copied `Animator` advances:

```cpp
const double advancedTime =
    static_cast<double>(animator.playbackTime) + elapsedSeconds;
const float duration = channel.timestamps.back();

if (animator.looping && duration > 0.0f)
{
    animator.playbackTime =
        static_cast<float>(std::fmod(advancedTime, duration));
}
else
{
    animator.playbackTime = static_cast<float>(
        std::min(advancedTime, static_cast<double>(duration)));
}
```

Looping playback wraps into the clip's time range. One-shot playback clamps at
the final timestamp and continues to hold that pose. A zero-duration channel
also takes the clamping path, avoiding a modulo by zero.

For a channel ending at two seconds, the boundary policy is concrete:

| Starting time | Elapsed | Looping | Stored time |
| ---: | ---: | :---: | ---: |
| `0.0` | `0.5` | yes | `0.5` |
| `0.0` | `2.0` | yes | `0.0` |
| `0.0` | `2.5` | yes | `0.5` |
| `0.0` | `3.0` | no | `2.0` |

An exact loop duration returning to the first keyframe is intentional. It
gives the half-open looping interval `[0, duration)` one unambiguous
representation rather than retaining both zero and duration for the same loop
boundary.

The addition and modulo use `double`, but the persistent playback time remains
a `float`. Wrapping keeps a looping value small enough to continue advancing;
it does not eliminate gradual floating-point drift. Exact long-running
synchronisation would require a double-precision member or sampling from an
absolute playback clock. Release 0.8 chooses the smaller state suitable for its
single demonstration clip and names the limitation in the implementation.

## Find the surrounding keyframes

Sampling first handles both ends of the channel:

```cpp
if (playbackTime <= channel.timestamps.front())
{
    return normalize(channel.values.front());
}
if (playbackTime >= channel.timestamps.back())
{
    return normalize(channel.values.back());
}
```

Inside that range, `std::ranges::upper_bound` finds the first timestamp
strictly greater than the playback time:

```cpp
const auto rightTimestamp =
    std::ranges::upper_bound(channel.timestamps, playbackTime);
const std::size_t rightIndex = static_cast<std::size_t>(
    rightTimestamp - channel.timestamps.begin());
const std::size_t leftIndex = rightIndex - 1;

const float amount =
    (playbackTime - channel.timestamps[leftIndex]) /
    (channel.timestamps[rightIndex] - channel.timestamps[leftIndex]);
```

For samples at `0`, `1`, and `2` seconds, playback at `1.4` selects the second
interval:

```text
time       0.0             1.0             2.0
sample      q0              q1              q2
                             |------x--------|
                                  1.4

leftIndex = 1       rightIndex = 2       amount = 0.4
```

Strictly increasing timestamps make the denominator positive. An exact
internal keyframe becomes the left endpoint of the following interval with an
amount of zero, reproducing that stored value. The explicit end checks make
the first and final keyframes stable too.

This is why timeline validation is a loading concern rather than optional
defensive polish. Duplicate or descending timestamps would make interval
selection or its interpolation fraction ill-defined.

## Take the shortest normalized quaternion path

Quaternion samples have a useful complication: `q` and `-q` represent the
same orientation. Interpolating their components without accounting for that
equivalence can take the long route between two nearby orientations or even
pass through an unnormalizable zero quaternion.

`normalizedLerp()` first selects the hemisphere with the non-negative dot
product, then interpolates and normalizes:

```cpp
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
```

The sign choice gives the shortest quaternion arc. Normalisation returns a unit
quaternion suitable for matrix conversion even when imported endpoints contain
small numerical error. Exact endpoint branches are normalized for the same
reason rather than trusting source data only between samples.

This is normalized linear interpolation, or nlerp. It does not provide the
constant angular velocity of spherical interpolation. glTF describes spherical
interpolation for linear rotation channels, while allowing implementations to
approximate interpolation for their target accuracy and performance. Release
0.8's deliberately narrow slice uses shortest-arc nlerp for AnimatedCube;
adding slerp would be a separate improvement rather than something this code
quietly claims to implement.

The [transforms post][transforms-post] develops this quaternion contract in
more detail. See its implementation in [`quaternion.hpp`][source-quaternion].

## Replace only the driven local property

The selected 0.8 animation subset drives rotation only. Applying a sample must
not reset translation or scale that came from the imported node:

```cpp
Transform transform = node.localTransform();
transform.rotation = sampleRotation(channel, animator.playbackTime);
node.localTransform(transform);
node.component(animator);
```

The read-modify-write preserves every local property the channel does not own.
Writing the copied `Animator` back beside it retains the new playback time for
the following frame.

The subsequent scene pass composes local matrices with their parents:

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

For AnimatedCube, the primitive child receives the animated source node's
rotation through this multiplication. Its `RenderObjectId` remains unchanged;
only the `world` matrix copied into the current draw item differs.

See [`scene_node.cpp`][source-scene-node] and
[`scene.cpp`][source-scene].

## Keep preparation generation stable

Animation now reaches the draw without entering the cache key:

```text
changes every frame                         stays stable

Animator.playbackTime                       RenderAssets identity
        |                                   RenderAssets revision
        v                                   ordered RenderObjectIds
local rotation                                      |
        |                                           v
        v                              cached RenderPreparationPlan
world transform                                     |
        |                                           v
        v                                  CompiledResources
DrawItem.world                                      |
        |                                           |
        +------------------> record draw <----------+
```

`SceneDrawList::dependencyHash` deliberately hashes only the ordered
`RenderObjectId` sequence. The draw items still carry their current world
matrices, but transforms do not select meshes, materials, textures, or pipeline
state. Movement changes commands recorded for a frame, not the resource set
those commands use. `node.component(animator)` replaces the complete component
value, but it replaces an `Animator` with an `Animator`; no `RenderObjectId`
enters or leaves the draw traversal.

The focused regression test asks preparation to build before and after an
animation update:

```cpp
static_cast<void>(preparation.build(
    assets, scene.buildDrawItems()));
REQUIRE(preparation.generation() == 1);

fire_engine::advanceAnimations(scene, animations, 0.5f);
scene.updateWorldTransforms();
static_cast<void>(preparation.build(
    assets, scene.buildDrawItems()));

REQUIRE(preparation.generation() == 1);
REQUIRE(scene.buildDrawItems().drawItems.front().world !=
        fire_engine::Mat4::identity());
```

Both halves matter. The changed world matrix proves animation reached the draw.
The unchanged generation proves preparation recognized the same asset revision
and exact dependency sequence. If the renderer were asked to prepare again, it
would reuse the plan; in the normal application it prepares once and simply
draws the newly resolved scene each frame. In both cases the compiled buffers,
images, samplers, and render-object lookup survive the movement.

See [`scene_draw_list.hpp`][source-draw-list],
[`render_preparation.cpp`][source-preparation], and
[`test_animation_playback.cpp`][source-playback-test].

## Make the device scenario advance deterministically

An interactive loop should reflect real elapsed time. An automated Vulkan
scenario needs a different property: the same bounded run should exercise the
same animation regions regardless of machine speed.

The AnimatedCube smoke path therefore substitutes a fixed `0.8` seconds for
each of its three presented frames. Its clip ends at two seconds:

| Frame | Time before sampling | What it exercises |
| ---: | ---: | --- |
| 1 | `0.8` | interpolation in the first interval |
| 2 | `1.6` | interpolation in the second interval |
| 3 | `0.4` after wrapping `2.4` | loop boundary and first interval again |

This is not a fixed-timestep simulation hidden inside the engine. It is test
input chosen by the application scenario. The same `advanceAnimations()` path
receives measured time interactively and deterministic time under CTest.

The scenario loads AnimatedCube, prepares its selected resources once, advances
and resolves the hierarchy, then records three real Vulkan frames. Validation
errors fail the test. As with the other device scenarios, it proves that the
integrated path executes correctly; it does not compare rendered pixels.

## Verify playback at both boundaries

Three device-free cases cover the animation policy:

- midpoint sampling returns a unit quaternion and an exact internal keyframe
  remains stable;
- looping advances wrap, the exact duration returns to time zero, and
  non-looping playback holds the final sample; and
- a changed world transform leaves render-preparation generation unchanged.

The bounded AnimatedCube scenario then crosses the loader, hierarchy,
preparation, renderer, and Vulkan validation boundaries. Run the focused set
after configuring and building release 0.8:

```shell
cmake --preset vcpkg
cmake --build --preset default
ctest --preset default -R "^(Animation playback interpolates normalized rotations at stable keyframe boundaries|Animation playback wraps looping channels and clamps non-looping channels|Animation changes transforms without invalidating render preparation|fireEngineTutorialAnimatedCubeSmoke)$"
```

The unit tests prove timing, sampling, normalization, hierarchy propagation,
and cache behavior without a device. The smoke scenario proves those CPU
results can feed the complete draw path. Keeping the levels separate makes a
failure more informative than relying on a rotating cube alone.

See the cases in [`test_animation_playback.cpp`][source-playback-test] and the
scenario registration in [`CMakeLists.txt`][source-cmake].

## Diagnose animation playback failures

### The model never moves

Confirm that the chosen scene contains an `Animator`, that its IDs refer to the
loaded animation table, and that `advanceAnimations()` is called before
`updateWorldTransforms()`. Updating local rotation after world resolution
delays the visible result until another resolution pass.

### The animator node changes but its primitive does not

The renderable primitive must be a descendant of the animated source node for
the source transform to propagate. Inspect the imported hierarchy rather than
copying the sampled rotation onto mesh data or the render object.

### Playback chooses the wrong interval

Validate that timestamps are finite and strictly increasing, then confirm that
`upper_bound` searches for the first value greater than playback time. Using a
lower-bound policy changes which side owns an exact internal keyframe.

### A rotation takes the long route

Check the quaternion dot product before interpolation. A negative value means
one endpoint should be negated; the represented orientation stays the same but
the component path moves to the nearer hemisphere.

### The quaternion grows or shrinks

Normalize interpolated results and exact endpoint samples. Component-wise
linear interpolation does not remain on the unit hypersphere by itself, and an
invalid zero or non-finite quaternion should not reach matrix conversion.

### A loop never displays its final keyframe

At exactly the channel duration, looping playback wraps to zero. That is the
chosen half-open interval policy. A final pose that must be held should use
non-looping playback or content whose neighboring samples make the loop
continuous.

### Preparation generation changes while only the cube rotates

Check that animation changes only local transforms and `Animator` state.
Adding, replacing, or moving a `RenderObjectId` component changes the exact
dependency sequence; mutating `RenderAssets` changes its revision. Either is a
real preparation change, unlike a new world matrix.

### A long session gradually loses timing precision

The stored playback position is a `float`. Looping keeps it bounded but cannot
remove accumulated rounding. Requirements for long-running synchronisation,
scrubbing, or alignment to an external clock would justify double-precision or
absolute-time playback rather than more corrections in quaternion sampling.

### Playback reports a broken binding

`advanceAnimations()` assumes validated content, then guards against missing
animation or channel IDs, an unsupported target path, and malformed channel
shape. A `logic_error` means something invalidated that earlier content
contract; repair the construction or mutation path rather than treating the
frame as a recoverable missing pose.

## What this part of release 0.8 gives us

This part of release 0.8 establishes a deliberately small playback path:

- target-independent animation channels retain ordered quaternion samples;
- each scene `Animator` owns its channel binding, time, and looping policy;
- several animators can share samples while advancing independently;
- one public CPU operation advances every animator in the scene forest;
- finite non-negative elapsed time is validated before any node changes;
- interactive playback uses a monotonic application clock;
- loops wrap with `fmod`, while one-shot playback clamps at the final sample;
- `upper_bound` selects a stable pair around each interior playback time;
- shortest-arc normalized linear interpolation produces a unit rotation;
- applying a sample preserves the node's imported translation and scale;
- world-transform resolution propagates that rotation to renderable children;
- draw items carry current matrices while their render-object identities remain
  stable;
- unchanged asset revision and ordered dependencies preserve preparation
  generation and compiled Vulkan resources;
- focused CPU tests prove sampling and cache behavior; and
- deterministic elapsed input makes the bounded device scenario exercise both
  keyframe intervals and a wrap.

AnimatedCube can now rotate continuously without confusing dynamic pose with
static resource identity. That distinction is more valuable than this one
clip: later animation channels, instances, and playback controls can extend the
CPU update path while the renderer continues to compile resources only when
the things needed to draw actually change.

## Recommended reading

- [Foundations of Game Engine Development, Volume 1: Mathematics][reading-foundations] —
  quaternion interpolation, transform composition, and the mathematical basis
  for carrying a sampled local rotation through a hierarchy.
- [glTF 2.0 specification: Animations][reading-gltf-animation] — animation
  samplers, channels, target paths, timestamps, and interpolation requirements.
- [C++ `std::chrono::steady_clock`][reading-steady-clock] — the monotonic clock
  used to measure interactive frame intervals.
- [C++ `std::ranges::upper_bound`][reading-upper-bound] — the ordered search
  operation used to select the first keyframe after a playback time.
- [Fix Your Timestep!][reading-timestep] — a useful next step when variable
  visual playback grows into simulation with stronger timing requirements.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[transforms-post]: {% post_url 2026-08-22-giving-fireengine-imported-transforms-enough-vocabulary %}
[descriptions-post]: {% post_url 2026-08-23-extending-fireengines-descriptions-without-introducing-vulkan %}
[source-animation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/animation/animation.hpp>
[source-animator]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/scene/animator.hpp>
[source-playback-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/animation/animation_playback.hpp>
[source-playback-cpp]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/animation/animation_playback.cpp>
[source-animation-validation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/animation/animation_validation.cpp>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-quaternion]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/math/quaternion.hpp>
[source-scene-node]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/scene/scene_node.cpp>
[source-scene]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/scene/scene.cpp>
[source-draw-list]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/scene/scene_draw_list.hpp>
[source-preparation]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/graphics/render_preparation.cpp>
[source-playback-test]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/tests/animation/test_animation_playback.cpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[reading-foundations]: <https://foundationsofgameenginedev.com/#fged1>
[reading-gltf-animation]: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations>
[reading-steady-clock]: <https://en.cppreference.com/w/cpp/chrono/steady_clock>
[reading-upper-bound]: <https://en.cppreference.com/w/cpp/algorithm/upper_bound>
[reading-timestep]: <https://gafferongames.com/post/fix_your_timestep/>
[reading-page]: {% link _tabs/reading.md %}
