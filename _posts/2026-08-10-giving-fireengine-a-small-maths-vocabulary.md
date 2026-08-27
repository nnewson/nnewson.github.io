---
title: Giving fireEngine a small maths vocabulary
date: 2026-08-10 08:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, maths, vectors, matrices, transforms, scene-graph, cpp]
description: >-
  Add small Vec3, Vec4, and column-major Mat4 types so fireEngine can describe,
  compose, test, and upload its first scene transforms without Vulkan types.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

Release 0.6 could transform its triangle, but it could not yet express a scene
transform. The frame uniform stored a raw array of sixteen floats named
`transform` on both sides of the CPU/shader boundary, and an identity matrix was
enough because there was only one object in one fixed position.

Release 0.7 supplies more precise language. Scene nodes have local and world
transforms. A parent transform composes with its child's transform. Stable
frame-wide state is separate from the model matrix belonging to one draw.
Those relationships are much easier to state with a matrix type than with
arrays whose meaning exists only in the code that fills them.

fireEngine therefore gains its first maths layer: `Vec3`, `Vec4`, and `Mat4`.
It is deliberately small. The release adds only the storage and operations
required to position and scale the tutorial triangle, compose scene hierarchy,
and cross the existing CPU/shader boundary without repacking data.

This is the second post based on release 0.7. The
[first 0.7 post][testing-post] separated the engine into a reusable library and
added the device-free test target that verifies these new value types. The
other posts use them to describe render assets, build the scene graph, prepare
render data, and drive the refactored renderer.

The walkthrough follows the maths changes from [release 0.6][release-0-6] to
[release 0.7][release-0-7]. Every source link remains pinned to 0.7 so the
examples continue to match the release as the maths layer grows.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Testing fireEngine without a GPU][testing-post] for the library,
> Catch2, and CTest structure used here. This post concentrates on the value,
> layout, and composition rules established by the first maths types.
{: .prompt-info }

## Introduce only the vocabulary the scene needs

Release 0.7 introduces three connected types:

- **`Vec3`** stores three floating-point components for values such as a
  position, translation, or non-uniform scale;
- **`Vec4`** stores four components for homogeneous coordinates and provides the
  dot product used by matrix multiplication; and
- **`Mat4`** stores a four-by-four, column-major matrix with factories for zero,
  identity, translation, and scale transforms.

The types are Vulkan-free and live under the public maths include directory:

```text
include/fire_engine/math/
├── mat4.hpp
├── vec3.hpp
└── vec4.hpp

tests/math/
└── test_mat4.cpp
```

This is not intended to be a complete linear-algebra package. There are no
quaternions, rotations, projections, inverse matrices, cameras, normalisation
helpers, or general sets of vector operators in 0.7. Each can arrive with the
first engine feature that needs it, carrying a test and a reason to choose its
conventions.

That restraint matters in a tutorial. A large imported maths library would
solve more problems, but it would also hide the storage, ordering, and shader
interface decisions that scene traversal is about to depend on.

## Keep three-component values transparent

[`Vec3`][source-vec3] begins as an aggregate with named components and exact
equality:

```cpp
struct Vec3
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;

    [[nodiscard]] constexpr bool operator==(const Vec3&) const noexcept = default;
};
```

The default member initialisers make `Vec3{}` the zero vector. Aggregate
initialisation keeps call sites explicit without introducing constructors:

```cpp
const Vec3 translation{.x = 2.0f, .y = 3.0f, .z = 4.0f};
```

This is enough for the first scene. A translation and a scale both contain
three numbers, and the factory receiving the value supplies its meaning. The
type does not yet pretend that every useful three-dimensional operation has
been designed.

The defaulted equality operator compares components exactly. That is useful for
values constructed from the same exact inputs and for simple identity checks;
tests involving accumulated floating-point calculations should still use an
appropriate tolerance rather than assume all equivalent calculations produce
the same bits.

## Use a fourth component for homogeneous coordinates

A four-by-four transform operates naturally on a four-component column vector.
[`Vec4`][source-vec4] provides that value and the one operation `Mat4` needs:

```cpp
struct Vec4
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 0.0f;

    [[nodiscard]] constexpr float dot(Vec4 right) const noexcept
    {
        return x * right.x + y * right.y + z * right.z + w * right.w;
    }

    [[nodiscard]] constexpr bool operator==(const Vec4&) const noexcept = default;
};
```

The fourth component distinguishes positions from directions when affine
transforms are expressed as matrices:

- `(x, y, z, 1)` is a position, so the matrix's translation contributes to the
  result; and
- `(x, y, z, 0)` is a direction, so translation has no effect.

Release 0.7 only needs the first form. The test transforms a position with
`w = 1`, and the vertex shader extends each three-component mesh position to a
`float4` in the same way.

`Vec4::dot()` multiplies matching components and adds them. Matrix
multiplication will use that small operation repeatedly: one result element is
the dot product of one row from the left matrix and one column from the right.

## Give zero and identity different meanings

[`Mat4`][source-mat4] owns sixteen floats and deliberately defaults them all to
zero:

```cpp
class alignas(16) Mat4 final
{
public:
    constexpr Mat4() noexcept = default;

    [[nodiscard]] static constexpr Mat4 identity() noexcept
    {
        Mat4 result;
        result[0, 0] = 1.0f;
        result[1, 1] = 1.0f;
        result[2, 2] = 1.0f;
        result[3, 3] = 1.0f;
        return result;
    }

    // Element access, factories, and multiplication omitted here.

private:
    std::array<float, 16> values_{};
};
```

The zero matrix and identity matrix have different jobs. Multiplying by the
zero matrix removes every component; multiplying by identity leaves a value
unchanged. Keeping identity as a named factory makes that intention visible at
the call site:

```cpp
Mat4 localTransform = Mat4::identity();
```

It also leaves value-initialised storage predictably zero. Factory functions can
start from that known state and set only the entries they need, rather than
depending on a constructor that silently inserts a transform.

All current operations are `constexpr` and `noexcept`. The same type can be
used for compile-time constants and runtime scene values, and none of the first
operations allocates memory or has an exceptional failure mode.

## Separate logical indexing from physical storage

Matrix notation normally names an element by row and then column. The storage
layout answers a different question: which element appears next in memory?

fireEngine chooses column-major storage to keep its representation aligned with
the column-vector convention common in graphics texts. Matrices multiply column
vectors written on their right, so composition is evaluated from right to left:
in `translation * scale * position`, scale acts first. Row-major storage could
implement the same algebra, and Slang supports either layout; fireEngine
configures Slang to match the engine's column-major choice so matrices can cross
the shader boundary unchanged.

The class keeps the familiar logical access order while storing complete columns
contiguously:

```cpp
[[nodiscard]] constexpr float operator[](std::size_t rowIndex,
                                         std::size_t columnIndex) const noexcept
{
    return values_[columnIndex * 4 + rowIndex];
}

[[nodiscard]] constexpr float& operator[](std::size_t rowIndex,
                                          std::size_t columnIndex) noexcept
{
    return values_[columnIndex * 4 + rowIndex];
}
```

For a logical matrix whose final column contains translation:

```text
| m00 m01 m02 tx |
| m10 m11 m12 ty |
| m20 m21 m22 tz |
| m30 m31 m32 tw |
```

the contiguous column-major array is:

```text
m00 m10 m20 m30  m01 m11 m21 m31  m02 m12 m22 m32  tx ty tz tw
```

That is why `matrix[0, 3]` refers to the X translation while `data()[12]`
contains the same value. One is a row-and-column coordinate; the other is a
physical offset.

Neither overload performs bounds checking. Every current caller uses fixed
indices between zero and three, and the tight access path remains usable in
`constexpr` multiplication. A future general-purpose indexing API would need
to decide explicitly whether checked access belongs alongside it.

## Use C++23 multidimensional subscripting

The expression `matrix[row, column]` is a real two-argument subscript, not two
sequential one-dimensional lookups. C++23 allows `operator[]` to accept more
than one argument, so `Mat4` can express the matrix notation directly without a
proxy row type or a separate `at(row, column)` function.

The mutable overload returns a reference, allowing factories and multiplication
to assign an element. The const overload returns its value. Both share the same
column-major offset calculation, keeping reads and writes consistent.

This is one reason the tutorial's C++23 baseline is a design choice rather than
only a compiler setting. Building the tagged source as an older language
version will fail at this interface even though most of the surrounding class
looks like earlier C++.

## Name rows and columns for multiplication

`Mat4` can also return one logical row or column as a `Vec4`:

```cpp
[[nodiscard]] constexpr Vec4 row(std::size_t rowIndex) const noexcept
{
    return {
        .x = (*this)[rowIndex, 0],
        .y = (*this)[rowIndex, 1],
        .z = (*this)[rowIndex, 2],
        .w = (*this)[rowIndex, 3],
    };
}

[[nodiscard]] constexpr Vec4 column(std::size_t columnIndex) const noexcept
{
    return {
        .x = (*this)[0, columnIndex],
        .y = (*this)[1, columnIndex],
        .z = (*this)[2, columnIndex],
        .w = (*this)[3, columnIndex],
    };
}
```

These functions favour clarity over exploiting the fact that a stored column
is already contiguous. The first implementation can describe multiplication in
the same row-by-column language used to explain it, while the tests pin its
result. Optimisation can wait until measurement shows that this small scene
maths layer needs it.

## Build translation and scale explicitly

The first scene only needs two transform factories. Translation starts from
identity and places its three values in the final column:

```cpp
[[nodiscard]] static constexpr Mat4 translation(Vec3 translationValue) noexcept
{
    Mat4 result = identity();
    result[0, 3] = translationValue.x;
    result[1, 3] = translationValue.y;
    result[2, 3] = translationValue.z;
    return result;
}
```

Scale also starts from identity and replaces the first three diagonal entries:

```cpp
[[nodiscard]] static constexpr Mat4 scale(Vec3 scaleValue) noexcept
{
    Mat4 result = identity();
    result[0, 0] = scaleValue.x;
    result[1, 1] = scaleValue.y;
    result[2, 2] = scaleValue.z;
    return result;
}
```

Starting from identity preserves the bottom-right homogeneous component and the
unaffected axes. A default-constructed zero matrix would instead erase values
that these transforms are meant to leave alone.

These factories also make the role of a `Vec3` explicit. The same storage shape
becomes a translation or scale only when passed to the corresponding function.

## Compose transforms in the order they apply

Matrix multiplication fills each result element with a left-row/right-column
dot product:

```cpp
[[nodiscard]] constexpr Mat4 operator*(const Mat4& right) const noexcept
{
    Mat4 result;
    for (std::size_t rowIndex = 0; rowIndex < 4; ++rowIndex)
    {
        for (std::size_t columnIndex = 0; columnIndex < 4; ++columnIndex)
        {
            result[rowIndex, columnIndex] =
                row(rowIndex).dot(right.column(columnIndex));
        }
    }
    return result;
}
```

Matrix-vector multiplication follows the same rule:

```cpp
[[nodiscard]] constexpr Vec4 operator*(Vec4 right) const noexcept
{
    return {
        .x = row(0).dot(right),
        .y = row(1).dot(right),
        .z = row(2).dot(right),
        .w = row(3).dot(right),
    };
}
```

fireEngine uses column vectors, so the rightmost transform is applied first.
For `translation * scale * position`, the position is scaled and then
translated. Reversing the two matrices would translate first and then scale the
translation as well.

The maths test makes the chosen order observable:

```cpp
TEST_CASE("Mat4 composes parent and local transforms")
{
    const Mat4 transform =
        Mat4::translation(Vec3{.x = 2.0f, .y = 3.0f, .z = 4.0f}) *
        Mat4::scale(Vec3{.x = 2.0f, .y = 3.0f, .z = 4.0f});

    const Vec4 transformed =
        transform * Vec4{.x = 1.0f, .y = 1.0f, .z = 1.0f, .w = 1.0f};

    REQUIRE(transformed.x == Approx(4.0f));
    REQUIRE(transformed.y == Approx(6.0f));
    REQUIRE(transformed.z == Approx(8.0f));
    REQUIRE(transformed.w == Approx(1.0f));
}
```

The input position first becomes `(2, 3, 4)`, then the translation adds another
`(2, 3, 4)`, producing `(4, 6, 8)`. The assertion is more than a multiplication
check: it fixes the convention that scene traversal uses.

## Resolve parent and local transforms consistently

The [first scene graph][scene-post] stores an identity local transform and an
identity world transform on every new node. Resolving a node composes them in
the same order as the test:

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

The local transform is applied first, positioning the node relative to its
parent. The already-resolved parent transform then carries that result into
world space. A deeper hierarchy repeats the same rule from the roots downwards.

The [scene-graph post][scene-post] examines ownership and traversal in more
detail. For this maths layer, the important point is that the composition
convention has one implementation and one device-free test before hierarchy
depends on it.

## Match the CPU and shader layouts

Column-major storage is not only a scene convention. `Mat4` is also designed to
cross the shader boundary without a transpose or a repacking step.

The class has explicit 16-byte alignment, contains exactly sixteen floats, and
pins both facts at compile time:

```cpp
class alignas(16) Mat4 final
{
    // Public matrix operations omitted here.

private:
    std::array<float, 16> values_{};
};

static_assert(sizeof(Mat4) == 16 * sizeof(float));
static_assert(alignof(Mat4) == 16);
```

The Slang build already requests column-major matrix layout. Its frame constant
buffer uses `Std140DataLayout`, where a four-by-four float matrix occupies four
16-byte columns. `FrameUniforms` can therefore replace release 0.6's unnamed
array with the new type while retaining the same 64-byte allocation:

```cpp
struct alignas(16) FrameUniforms
{
    Mat4 viewProjection = Mat4::identity();
};

static_assert(sizeof(FrameUniforms) == 16 * sizeof(float));
static_assert(alignof(FrameUniforms) == 16);
```

`FrameInFlight` value-initialises that structure and uploads its bytes through
the existing uniform buffer. There is no camera yet, so `viewProjection`
remains identity. Renaming it still establishes its future responsibility:
world space to clip space, shared by every draw in the frame.

See [`frame_in_flight.hpp`][source-frame-header],
[`frame_in_flight.cpp`][source-frame], and the shader compiler options in
[`CMakeLists.txt`][source-cmake].

## Separate frame-wide and per-draw transforms

Release 0.6 had one matrix named `transform`, which was both the only frame
uniform and the only transform in the application. Release 0.7 gives the two
levels different names:

- `FrameUniforms::viewProjection` is frame-wide and will eventually describe
  the camera; and
- `DrawConstants::model` is per draw and carries one scene node from object
  space into world space.

The Slang vertex stage applies them in that order:

```hlsl
struct FrameUniforms
{
    float4x4 viewProjection;
};

struct DrawConstants
{
    float4x4 model;
    float4 baseColor;
};

[shader("vertex")]
FragmentInput vertexMain(VertexInput input)
{
    FragmentInput output;
    output.position = mul(
        frame.viewProjection,
        mul(draw.model, float4(input.position, 1.0))
    );
    output.color = input.color * draw.baseColor;
    return output;
}
```

The nested multiplication first transforms the mesh position by its model
matrix, then transforms the world-space result by the frame's view-projection
matrix. The model matrix changes between draws through push constants; the
frame uniform can remain bound for the complete group of draws.

The material colour beside `model` belongs to the Vulkan-free
render-description work covered by the [render-assets post][assets-post].
Its presence here demonstrates why the two transform levels are not merely
different names for the same data.

See [`draw_constants.hpp`][source-draw-constants] and the complete
[`triangle.slang`][source-shader].

## Make the tutorial triangle exercise the maths

Leaving every new matrix as identity would prove its layout but not its
composition. The tutorial scene therefore gives its triangle a non-identity
local transform:

```cpp
fire_engine::SceneNode& node = content.scene.addRoot("Tutorial triangle");
node.localTransform(fire_engine::Mat4::translation({.x = 0.12f, .y = 0.0f, .z = 0.0f}) *
                    fire_engine::Mat4::scale({.x = 0.9f, .y = 0.9f, .z = 1.0f}));
node.renderObject(triangle);
```

The rightmost scale reduces the triangle to 90 per cent of its original width
and height. The translation then moves it slightly to the right without scaling
that offset. The displayed subject remains the familiar coloured triangle, but
its path now proves that application data, scene composition, C++ storage, push
constants, and the shader agree about the matrix convention.

See the complete [`main.cpp`][source-main].

## Test the contract without a device

[`test_mat4.cpp`][source-test-mat4] contributes four of release 0.7's 24
device-free Catch2 cases:

- a default `Mat4` contains sixteen zeroes;
- `Vec3` and `Vec4` preserve their aggregate components and `Vec4::dot()`
  produces the expected result;
- translation appears in the final logical column and at contiguous storage
  offsets 12, 13, and 14; and
- matrix composition applies scale before translation and preserves the
  homogeneous `w` component.

The storage test checks both views of the same matrix:

```cpp
const Mat4 matrix =
    Mat4::translation(Vec3{.x = 2.0f, .y = 3.0f, .z = 4.0f});

REQUIRE(matrix[0, 3] == 2.0f);
REQUIRE(matrix[1, 3] == 3.0f);
REQUIRE(matrix[2, 3] == 4.0f);
REQUIRE(matrix.data()[12] == 2.0f);
REQUIRE(matrix.data()[13] == 3.0f);
REQUIRE(matrix.data()[14] == 4.0f);
```

This catches a common failure that a visual smoke test may only show as a
distorted or missing triangle: logical access can look correct while the byte
order uploaded to the shader is transposed.

Values that are stored and read back unchanged are compared exactly, including
the zero matrix and the translation entries at `[0, 3]` and `data()[12]`.
Values produced by arithmetic use Catch2's `Approx`, even where the current
inputs happen to make the result exact, so the assertions survive the first
non-integral transform.

No test opens a window or constructs Vulkan. The size and alignment assertions
are compile-time checks, while Catch2 verifies storage and multiplication as
ordinary CPU values.

## Run the maths tests

Clone, configure, build, and run release 0.7 as described in the
[first 0.7 post][testing-post]. During focused maths work, CTest can select only
the four relevant cases by name:

```shell
ctest --preset default -R "Mat4|Vector aggregates"
```

The filter matches the zero-matrix, vector-aggregate, column-major storage, and
transform-composition cases. It leaves the other device-free areas and the
Vulkan smoke test out of this focused run without changing their registration.

## Diagnose the new failure boundaries

The maths layer is small, but a convention error can propagate through every
node and vertex that follows it.

### The compiler rejects `matrix[row, column]`

Confirm that the project is configured through its C++23 CMake target. The
multi-argument subscript is a C++23 language feature; treating the source as
C++20 or earlier changes how that syntax is parsed.

### Translation appears on the wrong axis or not at all

Check the distinction between logical and physical layout. Translation belongs
in logical elements `[0, 3]`, `[1, 3]`, and `[2, 3]`, which are contiguous
offsets 12, 13, and 14 in column-major storage.

### Translation is scaled unexpectedly

Check multiplication order. With column vectors, `translation * scale` applies
scale first. `scale * translation` also scales the translation and represents a
different transform.

### Parent and child nodes move in the wrong space

The scene convention is `parentWorld * local`. Reversing it applies the parent
inside the child's local space and becomes increasingly visible as hierarchy
deepens.

### CPU tests pass but the rendered transform is wrong

Check both sides of the data boundary. C++ stores `Mat4` column-major with
64-byte size and 16-byte alignment; Slang compilation must retain the
`-matrix-layout-column-major` option, and the shader must multiply the model and
view-projection matrices in the matching order.

### An operation expected from a maths library is missing

That may be intentional. Release 0.7 implements the operations required by its
first scene, not a general-purpose package. Add a new operation with the feature
that supplies its conventions and tests rather than guessing at the future API.

## What this part of release 0.7 gives us

The first 0.7 post established a device-free test boundary. This second part
gives scene and rendering code a small, shared mathematical language:

- `Vec3` represents three-component scene values with transparent aggregate
  storage;
- `Vec4` represents homogeneous coordinates and supplies the dot product needed
  by matrix multiplication;
- `Mat4{}` creates a predictable zero matrix;
- `Mat4::identity()` expresses a transform that changes nothing;
- translation and non-uniform scale have named factories;
- C++23 multidimensional subscripting keeps logical row-and-column access clear;
- contiguous storage remains column-major for the Slang interface;
- row, column, matrix-matrix, and matrix-vector operations share one convention;
- multiplication order is fixed by a device-free composition test;
- `parentWorld * local` gives scene hierarchy an object-to-world rule;
- 64-byte size and 16-byte alignment are compile-time requirements;
- `FrameUniforms::viewProjection` replaces an unnamed float array without
  changing the uniform allocation;
- per-frame view-projection and per-draw model transforms have distinct jobs;
  and
- the tutorial triangle exercises a real scale and translation through the
  complete CPU/shader path.

The layer is intentionally incomplete. That is what keeps its contract clear.
The [render-assets post][assets-post] uses `Vec3` for vertex positions while
introducing Vulkan-free meshes, materials, render objects, typed identifiers,
and the separate `Color4` value that keeps colour-domain data out of the maths
API.

## Recommended reading

- [Foundations of Game Engine Development, Volume 1: Mathematics][reading-foundations] —
  Eric Lengyel's focused treatment of vectors, matrices, transforms, geometry,
  and the mathematical conventions used by game engines.
- [Real-Time Rendering][reading-real-time-rendering] — the classic rendering
  reference, whose transform chapter connects homogeneous coordinates and
  composition order to the rest of the real-time graphics pipeline.
- [C++ subscript operator][reading-cpp-subscript] — cppreference's language
  reference for overloaded subscripting, including the multi-argument
  `operator[]` syntax added in C++23 and used by `Mat4`.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[assets-post]: {% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %}
[scene-post]: {% post_url 2026-08-14-building-fireengines-first-scene-graph %}
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/CMakeLists.txt>
[source-vec3]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/math/vec3.hpp>
[source-vec4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/math/vec4.hpp>
[source-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/math/mat4.hpp>
[source-test-mat4]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/math/test_mat4.cpp>
[source-frame-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/frame_in_flight.hpp>
[source-frame]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/render/frame_in_flight.cpp>
[source-draw-constants]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/draw_constants.hpp>
[source-shader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/shaders/triangle.slang>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/src/main.cpp>
[reading-foundations]: <https://foundationsofgameenginedev.com/#fged1>
[reading-real-time-rendering]: <https://www.realtimerendering.com/>
[reading-cpp-subscript]: <https://en.cppreference.com/w/cpp/language/operators.html#Array_subscript_operator>
[reading-page]: {% link _tabs/reading.md %}
