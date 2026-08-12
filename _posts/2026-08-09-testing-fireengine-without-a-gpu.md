---
title: Testing fireEngine without a GPU
date: 2026-08-09 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, testing, catch2, cmake, architecture, refactoring, cpp]
description: >-
  Split fireEngine into reusable library, application, and Catch2 test targets,
  then test CPU-side decisions without opening a window or creating a GPU device.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.6"
---

Release 0.6 gave fireEngine one valuable test: launch the application, render a
frame, present it, and exit. That smoke test crosses the complete Vulkan path,
which makes it good evidence that the pieces work together. It is much less
helpful when one small decision is wrong.

Testing a matrix calculation should not require a window. Checking an invalid
mesh should not need a swapchain. Choosing between two supported presentation
formats should not depend on whichever surface and driver happen to be present
on the test machine.

Release 0.7 therefore separates the engine from its executable and adds a
Catch2 test target. Twenty-four test cases now exercise CPU-side behaviour
without creating a Vulkan device, while the original rendered-frame test stays
in place as the twenty-fifth CTest entry.

This is the first of several posts based on the same 0.7 source. The release
also introduces maths, render assets, a scene graph, render preparation, and a
new renderer facade; those contracts will receive their own walkthroughs. This
post concentrates on the build and design boundaries that make them testable.

The walkthrough follows those changes from [release 0.6][release-0-6] to
[release 0.7][release-0-7]. Code links remain pinned to 0.7 so each excerpt
continues to match the published checkpoint as fireEngine evolves.

> Source: [fireEngine 0.7]({{ page.release_url }})
>
> Start with [Refactoring fireEngine for what comes next][roadmap-post] for the
> full architectural plan. All source links in this post are pinned to 0.7,
> even though later posts will examine other parts of the same release.
{: .prompt-info }

## Introduce three levels of feedback

The new test suite does not replace the rendering smoke test. It gives each kind
of failure a more appropriate place to appear:

- **build and policy checks** catch formatting, warnings, documentation errors,
  terminology drift, and platform-specific compilation failures;
- **device-free unit tests** exercise deterministic engine behaviour with
  controlled inputs; and
- **the Vulkan smoke test** still creates the real ownership tree and proves one
  acquired, rendered, submitted, and presented frame.

The distinction is about scope rather than importance. A unit test can say that
surface-format selection chose the wrong fallback. The smoke test can say that
the complete application no longer presents. Both are useful, but only the
first points directly at the policy that failed.

"Device-free" also needs a precise meaning. Some tests use Vulkan value types
such as `vk::SurfaceCapabilitiesKHR`, and the test executable links the engine
library. They do not initialise GLFW, open a window, query a physical device, or
submit GPU work. Vulkan remains part of the renderer's vocabulary without
becoming a runtime precondition for every test.

## Split the build into three targets

Release 0.6 compiled the whole project, including `main.cpp`, into one
`fireEngineTutorial` executable. There was no reusable target for a test
executable to consume.

Release 0.7 introduces this target relationship:

```text
fireEngineTutorial
    -> fireEngineTutorialEngine

fireEngineTutorialTests
    -> fireEngineTutorialEngine
    -> Catch2::Catch2WithMain
```

The static library owns the engine implementation. The application owns only
`main.cpp`, tutorial scene construction, and the platform event loop. The test
executable links the same library as the application, so a test exercises the
production implementation rather than a copied or test-specific version.

The first part of [`CMakeLists.txt`][source-cmake] now expresses that split:

```cmake
# Build the reusable engine separately from the application entry point. This
# lets CPU-only unit tests exercise maths, scene traversal, and render planning
# without creating a window or Vulkan device.
add_library(fireEngineTutorialEngine STATIC
    src/core/debug.cpp
    src/graphics/asset_validation.cpp
    src/graphics/render_assets.cpp
    src/graphics/render_preparation.cpp
    # Platform, rendering, and scene sources omitted here.
)

target_include_directories(fireEngineTutorialEngine PUBLIC include)

# The application owns only its event loop and high-level scene construction.
add_executable(fireEngineTutorial src/main.cpp)
target_link_libraries(fireEngineTutorial PRIVATE fireEngineTutorialEngine)
```

Making `include` public means a consumer of the library automatically receives
the include path needed by fireEngine headers. The C++23 requirement and the
Vulkan-Hpp compile definitions also propagate where a public header requires
them, while implementation-only definitions and linked dependencies stay
private where possible.

The shader target still belongs to the runnable application. Unit tests can
test the SPIR-V loader with temporary input and do not need the tutorial shader
to be compiled before they start.

This separation is small in CMake and significant in design. `main.cpp` can no
longer be the only place where useful engine behaviour is reachable. New systems
need interfaces that the application and tests can both use, which naturally
pushes platform policy towards the edge of the program.

## Add Catch2 through the existing toolchain

Catch2 joins the other reproducible dependencies in [`vcpkg.json`][source-vcpkg].
The pinned vcpkg registry resolves the same package version locally and in CI,
and CMake requests Catch2's version-three package explicitly:

```cmake
find_package(Catch2 3 CONFIG REQUIRED)
```

The test target contains six source files arranged around the engine areas they
exercise:

```text
tests/
├── graphics/
│   ├── test_asset_validation.cpp
│   └── test_render_preparation.cpp
├── math/
│   └── test_mat4.cpp
├── render/
│   ├── test_spirv_loader.cpp
│   └── test_swapchain_selection.cpp
└── scene/
    └── test_scene.cpp
```

[`Catch2::Catch2WithMain`][catch2-cmake-integration] supplies the test program's
entry point, so the project only needs to provide test cases:

```cmake
add_executable(fireEngineTutorialTests
    tests/graphics/test_asset_validation.cpp
    tests/graphics/test_render_preparation.cpp
    tests/math/test_mat4.cpp
    tests/render/test_spirv_loader.cpp
    tests/render/test_swapchain_selection.cpp
    tests/scene/test_scene.cpp
)
target_link_libraries(fireEngineTutorialTests
    PRIVATE
        Catch2::Catch2WithMain
        fireEngineTutorialEngine
)

include(Catch)
catch_discover_tests(fireEngineTutorialTests)
```

`catch_discover_tests()` asks the built Catch2 executable which test cases it
contains and registers each one with CTest. A failure therefore appears under a
descriptive case name instead of being hidden behind one generic
`fireEngineTutorialTests` process.

Catch2 `SECTION`s remain branches inside their owning test case. They are useful
when several invalid inputs share setup, but CTest still reports the surrounding
`TEST_CASE` as one of the 24 discovered entries.

## Keep tests under the same compiler policy

The original warning logic applied only to the application target. With three
first-party targets, repeating that platform-specific block would make it easy
for their settings to drift.

Release 0.7 turns it into one CMake function:

```cmake
function(fire_engine_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /external:W0)
        if(FIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE /WX)
        endif()
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
        if(FIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE -Werror)
        endif()
    endif()
endfunction()

fire_engine_enable_warnings(fireEngineTutorialEngine)
fire_engine_enable_warnings(fireEngineTutorial)
fire_engine_enable_warnings(fireEngineTutorialTests)
```

Tests are first-party code. Compiling them with a weaker warning policy would
allow errors in fixtures and assertions that production code is not allowed to
contain. The formatting job likewise expands from `src` and `include` to cover
`tests`.

The release is explicit about one exception: clang-tidy still checks production
`.cpp` files only. Catch2's generated macros need a test-aware configuration,
and silently weakening the production analysis to accommodate them would hide
the trade-off. The CI comment records that limitation until the test target can
be added cleanly.

## Extract decisions from their environment

A test target is only useful when important behaviour can be called without
constructing the whole application around it. In 0.6, several deterministic
decisions were file-local functions inside larger Vulkan owners:

- swapchain construction chose a format, presentation mode, extent, image
  count, and composite-alpha mode;
- pipeline construction loaded and validated a SPIR-V file; and
- the new render-preparation path needed to validate meshes, materials, and
  their relationships.

Release 0.7 moves those decisions into focused `detail` interfaces:

```text
include/fire_engine/
├── graphics/detail/
│   └── asset_validation.hpp
└── render/detail/
    ├── spirv_loader.hpp
    └── swapchain_selection.hpp
```

These are not new public engine features. The `detail` namespace says they are
implementation contracts: reusable by the production owner and directly
testable, but free to change with that implementation.

This avoids two poor testing seams. The renderer does not expose private Vulkan
owners merely for inspection, and the tests do not reproduce its decisions in
parallel helper code. They call the same small functions that production code
calls.

## Test swapchain policy without a surface

Swapchain choice is an especially useful example. Selecting an image extent is
pure policy once two pieces of data are known: the capabilities reported by the
surface and the framebuffer extent reported by the window.

In 0.6, the selection helper accepted a `Window` and fetched the framebuffer
extent itself. In 0.7, the caller performs that environmental query and passes
the resulting value into [`chooseExtent()`][source-swapchain-selection]:

```cpp
[[nodiscard]] vk::Extent2D
chooseExtent(const vk::SurfaceCapabilitiesKHR& capabilities,
             const vk::Extent2D framebufferExtent);
```

The production swapchain still queries the real window. The helper now receives
plain input values, which lets a test describe fixed, oversized, undersized, and
zero-area framebuffers directly.

The same approach tests surface-format preference without creating a surface:

```cpp
TEST_CASE("Swapchain format selection prefers sRGB")
{
    const vk::SurfaceFormatKHR fallback{
        .format = vk::Format::eR8G8B8A8Unorm,
        .colorSpace = vk::ColorSpaceKHR::eSrgbNonlinear,
    };
    const vk::SurfaceFormatKHR preferred{
        .format = vk::Format::eB8G8R8A8Srgb,
        .colorSpace = vk::ColorSpaceKHR::eSrgbNonlinear,
    };

    REQUIRE(selection::chooseSurfaceFormat({fallback}) == fallback);
    REQUIRE(selection::chooseSurfaceFormat({fallback, preferred}) == preferred);
}
```

The Vulkan structures here are ordinary values. No loader, driver, physical
device, or queue is involved. The test states the policy clearly: choose the
preferred sRGB pair when it is available and preserve the supported fallback
when it is not.

Five swapchain-selection cases cover format, presentation mode, fixed and
variable extents, image-count limits, and composite-alpha preference. Errors
such as a zero-area variable extent or an empty recognised alpha set become
small reproducible inputs instead of platform-dependent startup failures.

See the complete [`test_swapchain_selection.cpp`][source-test-swapchain].

## Test file handling without creating a pipeline

SPIR-V loading had a similar boundary problem. The loader was a file-local
function inside `pipeline.cpp`, so testing malformed input meant reaching it
through graphics-pipeline creation.

The new [`loadSpirv()` detail interface][source-spirv-loader] owns only the file
contract: a module must exist, contain at least one complete 32-bit word, and be
read successfully. Pipeline creation consumes its returned words exactly as
before.

The test creates temporary files and exercises the failure modes with Catch2
sections:

```cpp
// The TemporaryPath RAII helper is omitted here.
TEST_CASE("SPIR-V loading rejects unusable files")
{
    const TemporaryPath temporary;

    SECTION("missing file")
    {
        REQUIRE_THROWS_AS(
            fire_engine::detail::loadSpirv(temporary.path().string()),
            std::runtime_error);
    }
    SECTION("empty file")
    {
        std::ofstream file{temporary.path(), std::ios::binary};
        file.close();
        REQUIRE_THROWS_AS(
            fire_engine::detail::loadSpirv(temporary.path().string()),
            std::runtime_error);
    }
    SECTION("partial word")
    {
        std::ofstream file{temporary.path(), std::ios::binary};
        constexpr std::array bytes = {'S', 'P', 'V'};
        file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        file.close();
        REQUIRE_THROWS_AS(
            fire_engine::detail::loadSpirv(temporary.path().string()),
            std::runtime_error);
    }
}
```

Each section starts again from the test-case setup, and `TemporaryPath` removes
its file through RAII even when an assertion fails. A separate success case
writes known 32-bit words and checks that their value and order survive the
round trip.

The test is about binary input, not Vulkan pipeline creation. That narrower
scope makes a failure explain whether file validation changed without asking a
driver to accept the resulting shader.

See the complete [`test_spirv_loader.cpp`][source-test-spirv].

## Cover the new CPU-side systems

The other four test files exercise systems introduced elsewhere in release
0.7. Their implementation details belong in the posts that follow, but their
distribution shows the breadth of the device-free boundary:

| Area | Test cases | Contract covered |
| --- | ---: | --- |
| Asset validation | 4 | Complete geometry, finite colours, and valid resource references |
| Render preparation | 6 | Validation, resource sharing, revision tracking, and plan reuse |
| Maths | 4 | Value construction, matrix storage, and transform composition |
| Scene | 3 | Hierarchy, stable traversal, world transforms, and invalid ownership |
| SPIR-V loading | 2 | Complete word loading and rejected file states |
| Swapchain selection | 5 | Formats, modes, extents, image counts, and composition policy |
| **Total** | **24** | **No window or Vulkan device creation** |

The table counts Catch2 `TEST_CASE`s, not individual assertions or section
paths. A single case may deliberately try several related invalid inputs.

This test layout also reinforces the architecture planned for 0.7. Maths,
assets, scenes, and preparation expose CPU-side contracts that can be exercised
directly. Vulkan orchestration stays behind the renderer, while deterministic
rendering policies are passed values instead of reaching into the environment
themselves.

## Keep the rendered-frame smoke test

The existing bounded application test is renamed from `fireEngineTutorial` to
`fireEngineTutorialSmoke`, making its scope visible next to the new unit cases:

```cmake
add_test(
    NAME fireEngineTutorialSmoke
    COMMAND fireEngineTutorial --frames 1
)
set_tests_properties(fireEngineTutorialSmoke PROPERTIES TIMEOUT 30)
```

It still opens a GLFW window, creates Vulkan through the selected driver,
allocates the rendering resources, records one frame, submits it, presents it,
and shuts down safely. A unit suite cannot prove those components agree at
runtime, so retaining this test prevents architectural cleanup from weakening
the end-to-end contract established by release 0.6.

## Document internal test seams honestly

Moving a helper into a header makes it reachable, but it does not automatically
make it supported public API. Release 0.7 marks the `detail` declarations and
implementation-only regions with Doxygen's `INTERNAL` conditional section.

The normal [`Doxyfile`][source-doxyfile] remains the public API view. A second
[`Doxyfile.internal`][source-doxyfile-internal] includes those settings, changes
the project identity and output folder, and enables the internal section:

```text
@INCLUDE_PATH          = docs
@INCLUDE               = Doxyfile

PROJECT_NAME           = "Fire Engine Tutorial — Internal Implementation"
PROJECT_BRIEF          = "The implementation details behind the tutorial renderer"
OUTPUT_DIRECTORY       = build/docs-internal
ENABLED_SECTIONS       = INTERNAL
```

CI builds both views and places the internal site under `internals/` in the
published documentation artefact. Readers can inspect why the engine makes a
choice without mistaking a test seam for a stable application-facing contract.

This is a useful distinction for a tutorial. Hiding every implementation detail
would make the design harder to study; presenting every implementation detail
as public API would make future refactoring needlessly expensive.

## Configure, build, and run release 0.7

The compiler, build-tool, vcpkg, and Vulkan prerequisites remain the same as in
the [foundation post][foundation-post]. Clone the release checkpoint directly
with:

```shell
git clone --branch 0.7 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

Configure and build the engine library, application, test executable, and
shader through the existing presets:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

Run the application interactively on macOS or Linux with:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

The application still displays the same coloured triangle introduced in
release 0.6. Its mesh, material, and scene now travel through the refactored 0.7
architecture, which the later posts in this sequence will examine.

Running the normal preset now executes both kinds of test:

```shell
ctest --preset default
```

A successful local run reports 25 independently named entries:

```text
Test project /path/to/fireEngine-tutorial/build
      Start  1: Asset validation accepts complete descriptions
 1/25 Test  #1: Asset validation accepts complete descriptions ... Passed
      ... 22 device-free test results omitted ...
      Start 24: Vector aggregates preserve their components
24/25 Test #24: Vector aggregates preserve their components .... Passed
      Start 25: fireEngineTutorialSmoke
25/25 Test #25: fireEngineTutorialSmoke ........................ Passed

100% tests passed out of 25
```

When no usable display or Vulkan driver is available, CTest's exclusion filter
can run only the device-free cases:

```shell
ctest --preset default -E fireEngineTutorialSmoke
```

That command is also useful while changing one CPU-side contract: the feedback
does not need to wait for window and driver startup.

## Extend continuous integration without overstating it

The Linux build-and-test job continues to run CTest under Xvfb with Lavapipe.
It now executes all 24 device-free cases before the rendered-frame smoke test in
the same preset.

macOS and Windows compile the engine, application, and test executable, catching
compiler and header differences across AppleClang and MSVC. Release 0.7 does not
run CTest on those hosted jobs, so the unit cases receive cross-platform build
coverage while runtime execution remains on Linux. Running the device-free
subset on all three platforms is a reasonable later CI improvement.

The platform-independent checks grow with the new code as well:

- clang-format now includes the `tests` directory;
- compiler warnings apply to all three first-party targets;
- clang-tidy remains strict over production sources while its Catch2-macro
  limitation is documented;
- Doxygen builds public and internal views with warnings treated as errors; and
- a terminology gate rejects the UK English variants that the project chose to
  remove from first-party code and comments.

The vcpkg baseline used by the manifest and CI checkout is also aligned. That
keeps Catch2 and the existing build dependencies reproducible instead of letting
the new test setup resolve against a different registry snapshot on each
machine.

See the complete [`ci.yml`][source-ci].

## Diagnose the new failure boundaries

The broader test surface creates more useful failures, but only if we read them
at the right level.

### CMake cannot find Catch2

Configure through the vcpkg preset and check that its baseline has been fetched.
The build requests Catch2 3's CMake package; a separately installed Catch2 2
does not satisfy that contract.

### CTest reports only the smoke test

`catch_discover_tests()` runs after the test executable is built. Confirm that
`include(Catch)` is present, the vcpkg Catch2 module is on CMake's module path,
and `fireEngineTutorialTests` built successfully before inspecting CTest's list.

### A supposedly device-free test opens a window

The test seam still owns an environmental query. Move the query to the
production caller and pass its result into the decision, as the swapchain does
with `Window::framebufferExtent()` and `chooseExtent()`.

### Unit tests pass but the smoke test fails

The CPU-side rules are intact, but their Vulkan integration is not. Check the
validation output, selected driver, display server, synchronization path, and
the complete application error rather than weakening the unit assertions.

### The smoke test cannot run on the current machine

Use CTest's `-E fireEngineTutorialSmoke` filter for the 24 device-free cases.
That preserves useful local feedback without pretending the skipped integration
path has passed.

### clang-tidy does not inspect the test files

That is the deliberate 0.7 policy, not a discovery failure. Test sources still
receive formatting checks and strict compiler warnings; adding them to
clang-tidy requires a configuration that handles Catch2's generated macros
without weakening analysis of the production sources.

## What this part of release 0.7 gives us

Release 0.6 proved one complete frame. This first part of release 0.7 adds fast,
focused evidence around the decisions that feed that frame:

- `fireEngineTutorialEngine` contains the reusable production implementation;
- `fireEngineTutorial` becomes a small application linked to that library;
- `fireEngineTutorialTests` links the same implementation with Catch2's test
  runner;
- CTest discovers 24 device-free cases under descriptive names;
- the existing one-frame Vulkan check remains as a separately named smoke test;
- all 25 tests run through the existing CTest preset;
- swapchain selection accepts explicit input values instead of querying a
  window inside every decision;
- SPIR-V file validation can be exercised without creating a pipeline;
- asset validation has one production-and-test implementation;
- `detail` headers expose internal contracts without promoting them to supported
  public API;
- public and internal Doxygen views document that distinction;
- tests share the production compiler-warning policy and formatting gate;
- Linux CI executes the full suite, while macOS and Windows compile every
  target; and
- the pinned vcpkg baseline keeps the new dependency reproducible.

The visible application still draws the same triangle. What changes is the cost
of understanding a failure: most new engine rules can now be checked in
milliseconds, with a controlled input and a name that describes the broken
contract.

The next 0.7 post can build on that boundary by introducing fireEngine's small
maths vocabulary. `Vec3`, `Vec4`, and `Mat4` will be able to establish their
layout and transform rules through the test target before scene traversal or
the renderer depends on them.

## Recommended reading

- [Catch2 tutorial][reading-catch2] — the official introduction to test cases,
  assertions, sections, behaviour-driven aliases, and data- and type-driven
  tests.
- [C++ Software Design][reading-cpp-software-design] — Klaus Iglberger's guide
  to dependencies, design principles, and patterns for building maintainable
  modern C++ systems.
- [Professional CMake][reading-professional-cmake] — Craig Scott's detailed
  guide to target relationships, usage requirements, dependency discovery,
  testing, and CTest integration in modern CMake projects.
- [Refactoring][reading-refactoring] — Martin Fowler's guide to improving an
  existing design through small, behaviour-preserving changes backed by tests.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-6]: {{ page.previous_release_url }}
[release-0-7]: {{ page.release_url }}
[roadmap-post]: {% post_url 2026-08-08-refactoring-fireengine-for-what-comes-next %}
[foundation-post]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/CMakeLists.txt>
[source-vcpkg]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/vcpkg.json>
[source-ci]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/.github/workflows/ci.yml>
[source-doxyfile]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/docs/Doxyfile>
[source-doxyfile-internal]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/docs/Doxyfile.internal>
[source-swapchain-selection]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/detail/swapchain_selection.hpp>
[source-test-swapchain]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/render/test_swapchain_selection.cpp>
[source-spirv-loader]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/include/fire_engine/render/detail/spirv_loader.hpp>
[source-test-spirv]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.7/tests/render/test_spirv_loader.cpp>
[catch2-cmake-integration]: <https://github.com/catchorg/Catch2/blob/devel/docs/cmake-integration.md>
[reading-catch2]: <https://github.com/catchorg/Catch2/blob/devel/docs/tutorial.md>
[reading-cpp-software-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-professional-cmake]: <https://crascit.com/professional-cmake/>
[reading-refactoring]: <https://martinfowler.com/books/refactoring.html>
[reading-page]: {% link _tabs/reading.md %}
