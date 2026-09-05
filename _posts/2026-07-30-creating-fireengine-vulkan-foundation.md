---
title: "Creating fireEngine's Vulkan foundation"
date: 2026-07-30 22:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, cmake, vcpkg, cpp]
description: >-
  Set up a reproducible C++23 and Vulkan build with vcpkg and CMake, then
  create and destroy the first Vulkan instance with Vulkan-Hpp RAII.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.1"
---

The first step in rebuilding fireEngine is deliberately small: create a Vulkan
instance, prove that it was created, and let C++ destroy it safely.

There is no window or rendered triangle yet. That is useful. It gives us room
to establish the toolchain, dependency management, build rules, and Vulkan
object-lifetime conventions before rendering code makes failures harder to
isolate.

This post walks through the first version of the
[fireEngine tutorial repository][repository]. The links and code snippets refer
to release 0.1, so the explanation remains tied to the published source even as
the engine evolves.

> Source: [fireEngine 0.1]({{ page.release_url }})
>
> This is a foundation release. A successful run proves that the compiler,
> vcpkg, CMake, the platform's Vulkan loader, and a Vulkan driver can all work
> together.
{: .prompt-info }

## Introducing the foundation

This release introduces three pieces that solve different parts of the same
startup problem:

- **vcpkg** records the third-party packages fireEngine needs and restores
  repeatable versions of them on each development machine and CI runner;
- **CMake** turns the source and dependency declarations into the native build
  rules used by Linux, macOS, and Windows; and
- a **Vulkan instance** establishes the application's connection to the Vulkan
  loader before any physical device, queue, or rendering resource can be used.

Together they create a narrow but complete foundation: dependencies can be
restored, the program can be built consistently, and the executable can prove
that Vulkan is available without introducing a window or rendering loop yet.

## What we are building

The repository is intentionally compact:

```text
fireEngine-tutorial/
├── .clang-format
├── .clang-tidy
├── .github/
│   └── workflows/
│       └── ci.yml
├── CMakeLists.txt
├── CMakePresets.json
├── vcpkg.json
├── vcpkg-configuration.json
└── src/
    └── main.cpp
```

Each file owns one part of the build:

| File | Responsibility |
| --- | --- |
| `vcpkg.json` | Declares the third-party packages the project needs. |
| `vcpkg-configuration.json` | Pins the package registry to a known revision. |
| `CMakePresets.json` | Gives everyone the same configure, build, and test commands. |
| `CMakeLists.txt` | Describes the executable and how it is compiled and linked. |
| `src/main.cpp` | Creates and destroys the first Vulkan object. |
| `.clang-format` | Fixes the source formatting so it is never a review topic. |
| `.clang-tidy` | Selects the static-analysis checks the code must pass. |
| `.github/workflows/ci.yml` | Runs those checks and the build on every push. |

The usual `README.md`, `LICENSE`, and `.gitignore` are present too, but they
are supporting documentation and repository metadata rather than build inputs,
so they are omitted from this walkthrough.

Two separate chains connect those files to a running program. At build time:

```text
CMake preset
    -> vcpkg toolchain
        -> vcpkg manifest
            -> Vulkan headers
                -> fireEngineTutorial executable
```

At run time:

```text
fireEngineTutorial executable
    -> platform Vulkan loader
        -> installed Vulkan driver
```

Keeping them apart matters, because vcpkg appears in only one of them. It
supplies the headers needed to compile the application, but it no longer
installs or links a Vulkan loader. Vulkan-Hpp loads the platform's loader
dynamically when the executable starts, and that loader still needs an
installed Vulkan implementation.

## Supported platforms

fireEngine's supported platforms for this tutorial are:

- Linux with a Vulkan 1.4 loader and implementation;
- Windows with a Vulkan 1.4 loader and graphics driver; and
- Apple Silicon running macOS 26 or later, using KosmicKrisp from the LunarG
  Vulkan SDK.

KosmicKrisp is a technical preview at the time of writing, so expect its
behaviour and packaging to change between SDK releases.

Intel Macs, earlier versions of macOS, and MoltenVK are not supported. The
engine therefore does not enable Vulkan portability enumeration.

Release 0.1 only creates a Vulkan instance. It does not enumerate, select, or
use a physical device, but stating the platform policy now keeps later
GPU-selection code focused on the configurations the engine intends to
support.

## Set up the development environment

You will need:

- Git;
- CMake 3.20 or newer;
- Ninja;
- a compiler with C++23 support;
- vcpkg; and
- a Vulkan implementation for your platform.

The project uses vcpkg's
[manifest mode][vcpkg-manifest-mode]. Instead of asking every developer to run
a growing list of package-install commands, the dependencies are checked into
the repository as JSON. The vcpkg CMake toolchain sees that manifest and
restores the packages during CMake configuration.

### Install vcpkg

Clone vcpkg somewhere outside the engine repository and bootstrap its command
line tool. On macOS or Linux:

```shell
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
./bootstrap-vcpkg.sh

export VCPKG_ROOT="$PWD"
export PATH="$VCPKG_ROOT:$PATH"
```

On Windows, from a Visual Studio Developer PowerShell:

```powershell
git clone https://github.com/microsoft/vcpkg.git C:\dev\vcpkg
C:\dev\vcpkg\bootstrap-vcpkg.bat

$env:VCPKG_ROOT = "C:\dev\vcpkg"
$env:Path = "$env:VCPKG_ROOT;$env:Path"
```

Either way, those environment changes affect only the current shell. Add
equivalent lines to the appropriate shell profile if you want them to persist,
and make sure the compiler environment, CMake, and Ninja are available in the
same shell.

Keeping vcpkg outside the project is intentional: `VCPKG_ROOT` tells the preset
where the toolchain is, while each project keeps control of its own dependency
manifest.

### Configure Vulkan for your platform

#### macOS

Install the LunarG Vulkan SDK 1.4.357.0, then load its environment and select
KosmicKrisp:

```shell
source "$HOME/VulkanSDK/1.4.357.0/setup-env.sh"
export VK_DRIVER_FILES="$VULKAN_SDK/share/vulkan/icd.d/libkosmickrisp_icd.json"
```

`VK_DRIVER_FILES` changes driver discovery for the current process. The
[Vulkan loader documentation][vulkan-driver-discovery] describes it as an
override. Selecting KosmicKrisp explicitly makes the command-line setup
deterministic when more than one Vulkan implementation is installed.

#### Linux

On an Ubuntu-based system, install the remaining host tools, the Vulkan loader,
and a software Vulkan implementation with:

```shell
sudo apt-get update
sudo apt-get install -y \
  build-essential cmake ninja-build libvulkan1 mesa-vulkan-drivers
```

`libvulkan1` supplies the system loader. Mesa's software driver is what allows
the Linux CI smoke test to create a Vulkan instance without a physical GPU.

#### Windows

The platform's Vulkan loader and a driver must be installed before the
executable will run, normally through the graphics driver package or the LunarG
Vulkan SDK. Nothing else needs to be configured for this release.

### Clone the tutorial

With the tools in place, clone the engine separately:

```shell
git clone --branch 0.1 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

## Describe the dependencies with vcpkg

The project has one direct dependency:

```json
{
  "name": "fire-engine-tutorial",
  "version-string": "0.1.0",
  "dependencies": [
    "vulkan-headers"
  ]
}
```

The full file is
[`vcpkg.json`][source-vcpkg-manifest].

`vulkan-headers` provides both the Vulkan C headers and Vulkan-Hpp, the C++
bindings used by `main.cpp`. There is deliberately no `vulkan-loader`
dependency: the executable dynamically loads the platform's existing loader
instead of linking one installed by vcpkg.

The package names alone do not make a build reproducible. vcpkg's port
definitions change over time, so the repository also records which revision of
the registry should be used:

```json
{
  "default-registry": {
    "kind": "git",
    "baseline": "aa2d37682e3318d93aef87efa7b0e88e81cd3d59",
    "repository": "https://github.com/microsoft/vcpkg"
  }
}
```

The full file is
[`vcpkg-configuration.json`][source-vcpkg-configuration].

The `baseline` is a Git commit in the vcpkg registry. It fixes the default
versions used to resolve ports, which prevents a future registry update from
silently changing this build.

## Make configuration repeatable with CMake presets

It is possible to configure this project with a long CMake command containing
the generator, output directory, build type, and vcpkg toolchain path. A preset
records those choices once:

```json
{
  "version": 2,
  "configurePresets": [
    {
      "name": "vcpkg",
      "displayName": "vcpkg (C++23 / Vulkan 1.4)",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug",
        "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
        "CMAKE_TOOLCHAIN_FILE": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
      }
    }
  ],
  "buildPresets": [
    {
      "name": "default",
      "configurePreset": "vcpkg"
    }
  ],
  "testPresets": [
    {
      "name": "default",
      "configurePreset": "vcpkg",
      "output": {
        "outputOnFailure": true
      }
    }
  ]
}
```

See the complete [`CMakePresets.json`][source-cmake-presets].

There are three related presets:

- `cmake --preset vcpkg` configures a Debug build in `build/` using Ninja, and
  restores dependencies;
- `cmake --build --preset default` compiles and links that configured tree; and
- `ctest --preset default` runs the result and prints useful output on failure.

`CMAKE_EXPORT_COMPILE_COMMANDS` creates
`build/compile_commands.json`. Editors and tools such as `clang-tidy` can then
see the exact include paths, language standard, definitions, and flags used for
each translation unit. CI depends on that file directly, as we will see below.

The important line for dependency management is:

```json
"CMAKE_TOOLCHAIN_FILE": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
```

CMake loads a toolchain while it is discovering the compiler. The
[vcpkg CMake integration][vcpkg-cmake-integration] hooks into that stage,
detects `vcpkg.json`, installs the declared packages into the build tree, and
makes them visible to normal CMake commands such as `find_package()`.

The preset therefore keeps machine-specific information in `VCPKG_ROOT`
instead of committing one developer's absolute path.

## Walk through `CMakeLists.txt`

The complete build description is roughly 70 lines, a good share of them
comments. We can read it from top to bottom in the same order CMake processes
it.

### Establish the project and language baseline

The build excerpt comes from [`CMakeLists.txt`][source-cmake].

```cmake
cmake_minimum_required(VERSION 3.20)

project(fire_engine_tutorial
    VERSION 0.1.0
    DESCRIPTION "A development tutorial to building your own fireEngine"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
```

`cmake_minimum_required()` rejects a CMake version too old for the project and
selects the corresponding CMake policy behaviour. `project()` gives the build
an identity and enables only C++, because no first-party C sources are needed.

The next three lines request C++23, prohibit a silent fallback to an older
standard, and turn off compiler-specific dialects such as `gnu++23`.

### Find Vulkan and expose one policy switch

The package and compile-definition excerpt comes from
[`CMakeLists.txt`][source-cmake].

```cmake
find_package(VulkanHeaders 1.4 CONFIG REQUIRED)

option(FIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS
    "Treat first-party compiler warnings as errors"
    ON
)
```

`find_package()` asks for the Vulkan 1.4 headers through the CMake package
configuration installed by vcpkg. `CONFIG` selects that package configuration
directly, while `REQUIRED` stops at configuration time if it cannot be found.
No loader library is requested.

The option keeps strict warnings on by default while providing an escape hatch
for a developer using a compiler version that reports a new warning:

```shell
cmake --preset vcpkg \
  -DFIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS=OFF
```

That changes only the warning policy; the normal warning level remains active.

### Create the executable

The target definition and application-info excerpts come from
[`CMakeLists.txt`][source-cmake] and [`main.cpp`][source-main].

```cmake
add_executable(fireEngineTutorial
    src/main.cpp
)

target_compile_features(fireEngineTutorial PRIVATE cxx_std_23)

target_compile_definitions(fireEngineTutorial PRIVATE
    VULKAN_HPP_NO_CONSTRUCTORS
)
```

`add_executable()` creates a CMake target from `main.cpp`. From this point on,
properties are attached to the target instead of being applied globally.

The target-level `cxx_std_23` requirement may look redundant beside
`CMAKE_CXX_STANDARD`. It keeps the requirement attached to this executable if
the target is later moved into a larger parent project.

`VULKAN_HPP_NO_CONSTRUCTORS` disables Vulkan-Hpp's constructors for Vulkan
structures. They remain aggregates, so the code can use C++20 designated
initializers:

```cpp
constexpr vk::ApplicationInfo applicationInfo{
    .pApplicationName = "Fire Engine Vulkan Tutorial",
    .applicationVersion = VK_MAKE_API_VERSION(0, 0, 1, 0),
    .pEngineName = "No Engine",
    .engineVersion = VK_MAKE_API_VERSION(0, 0, 1, 0),
    .apiVersion = vk::ApiVersion14,
};
```

This style names each field at the call site, avoiding the ambiguity of
positional constructor arguments. C++ still requires the designators to follow
member declaration order.

### Attach the Vulkan headers

The link declaration comes from [`CMakeLists.txt`][source-cmake].

```cmake
target_link_libraries(fireEngineTutorial PRIVATE
    Vulkan::Headers
)
```

`Vulkan::Headers` is an imported interface target created by `find_package()`.
Despite appearing in `target_link_libraries()`, it does not represent a binary
library. It propagates the Vulkan include path and related usage requirements
to the executable without linking a Vulkan loader.

`PRIVATE` describes the relationship accurately: the executable needs the
headers to compile, but it does not publish them as an interface for another
target to consume.

### Apply strict warnings on each compiler family

The warning policy comes from [`CMakeLists.txt`][source-cmake].

```cmake
if(MSVC)
    target_compile_options(fireEngineTutorial PRIVATE /W4)
    if(FIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS)
        target_compile_options(fireEngineTutorial PRIVATE /WX)
    endif()
else()
    target_compile_options(fireEngineTutorial PRIVATE -Wall -Wextra -Wpedantic)
    if(FIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS)
        target_compile_options(fireEngineTutorial PRIVATE -Werror)
    endif()
endif()
```

MSVC and Clang/GCC express equivalent policies with different flags. The outer
branch selects a high warning level; the inner branch optionally promotes
those warnings to errors.

These options are target-local. Third-party packages built by vcpkg are not
forced to satisfy the tutorial's warning policy.

### Turn the executable into a smoke test

```cmake
enable_testing()
add_test(NAME fireEngineTutorial COMMAND fireEngineTutorial)
```

`enable_testing()` activates CTest for this build tree. `add_test()` registers
the executable as a test, and CMake resolves the target name to the correct
executable path on the current platform.

This is not yet a unit test. It is still valuable: an exit code of zero proves
that the application dynamically loaded Vulkan, found a driver, and completed
the Vulkan instance lifecycle.

The snippets in this section come from the complete
[`CMakeLists.txt`][source-cmake].

## Walk through the Vulkan code

The executable contains one translation unit. It uses Vulkan-Hpp's RAII layer
so C++ object scope controls Vulkan object lifetime.

### Include the RAII API

The translation-unit excerpt comes from [`main.cpp`][source-main].

```cpp
#include <exception>
#include <iostream>

#include <vulkan/vulkan_raii.hpp>
```

The standard headers provide exception handling and console output.
`vulkan_raii.hpp` provides the Vulkan-Hpp types under `vk::raii`.

### Catch startup failures at the edge

The entry-point excerpt comes from [`main.cpp`][source-main].

```cpp
int main()
try
{
    // ...
}
catch (const std::exception& error)
{
    std::cerr << "Vulkan instance creation failed: " << error.what() << '\n';
    return 1;
}
```

This is a function try block: the `try` covers the whole body of `main()`.
Vulkan-Hpp represents many Vulkan failures as C++ exceptions, so a failure
becomes a readable diagnostic and a non-zero result for the shell and CTest.

### Load Vulkan entry points

The context construction comes from [`main.cpp`][source-main].

```cpp
vk::raii::Context context;
```

The context dynamically loads the Vulkan entry points exposed by the
platform's loader and initializes the Vulkan-Hpp RAII dispatch machinery. It
must outlive every RAII object created from it. That dependency is made obvious
here because `context` is declared before the instance.

### Describe the application

The application metadata comes from [`main.cpp`][source-main].

```cpp
constexpr vk::ApplicationInfo applicationInfo{
    .pApplicationName = "Fire Engine Vulkan Tutorial",
    .applicationVersion = VK_MAKE_API_VERSION(0, 0, 1, 0),
    .pEngineName = "No Engine",
    .engineVersion = VK_MAKE_API_VERSION(0, 0, 1, 0),
    .apiVersion = vk::ApiVersion14,
};
```

`vk::ApplicationInfo` gives the Vulkan implementation metadata about the
application and the API version it intends to use. This tutorial requests
Vulkan 1.4. It does not select a GPU or create a logical device; those are
later stages of initialization.

The engine is deliberately named `"No Engine"` at this point. We have a
Vulkan bootstrap program, not an engine abstraction.

### Describe the instance

The instance declaration comes from [`main.cpp`][source-main].

```cpp
const vk::InstanceCreateInfo instanceCreateInfo{
    .pApplicationInfo = &applicationInfo,
};
```

The create-info structure points at the application metadata. No instance
extensions or validation layers are enabled yet.

Release 0.1 stops before physical-device enumeration, so this code neither
selects nor uses a GPU.

### Create and destroy with scope

```cpp
{
    [[maybe_unused]] const vk::raii::Instance instance{
        context,
        instanceCreateInfo
    };
    std::cout << "Vulkan 1.4 instance created.\n";
}

std::cout << "Vulkan instance destroyed.\n";
return 0;
```

Constructing `vk::raii::Instance` calls `vkCreateInstance`. When execution
leaves the inner scope, its destructor calls `vkDestroyInstance`.

The explicit scope exists to make that lifetime visible and to print after
destruction. `[[maybe_unused]]` tells the compiler that the variable is owned
only for its lifetime; this milestone does not query it yet.

This is the central convention the engine will build upon: if a Vulkan object
has one clear owner, its cleanup should follow from that owner's C++ lifetime,
including when an exception interrupts startup.

See the complete [`src/main.cpp`][source-main] and the
[Khronos Vulkan-Hpp RAII instance guide][vulkan-instance-guide].

## Configure, build, and run

All dependency restoration and configuration is triggered by the preset:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

Then run the executable directly:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

A successful run prints:

```text
Vulkan 1.4 instance created.
Vulkan instance destroyed.
```

That first line is a statement of intent rather than a capability report.
`vk::ApplicationInfo::apiVersion` declares the highest Vulkan version the
application is designed to use; it is not a negotiated result.
`context.enumerateInstanceVersion()` reports the instance-level version
supported by the loader. After physical-device enumeration,
`vk::PhysicalDeviceProperties::apiVersion` reports the version supported by
each GPU. Instance creation succeeding therefore does not prove that either the
loader or a physical device supports Vulkan 1.4.

The same program can be run as the registered smoke test:

```shell
ctest --preset default
```

## Prove it in CI

[`ci.yml`][source-ci] runs on every push to `main` and every pull request. It
uses the same presets a developer would, which is the point of having them.

Two jobs guard the source itself:

- **clang-format** checks `src/` with `clang-format --dry-run -Werror`, so
  formatting is decided by `.clang-format` and never by review comments; and
- **clang-tidy** configures and builds the project, then runs
  `clang-tidy -p build src/main.cpp`. The `-p build` argument is where
  `compile_commands.json` earns its place in the preset: the analyser sees
  precisely the flags the compiler saw.

Three more jobs cover the platforms:

- **Linux** installs `libvulkan1` and `mesa-vulkan-drivers`, builds, and runs
  `ctest`. Mesa's software driver is what makes a real instance create and
  destroy possible on a machine with no GPU.
- **macOS** and **Windows** build only. The current workflow does not install a
  compatible Vulkan implementation on either runner: the macOS workflow does
  not install the LunarG SDK containing the KosmicKrisp preview driver, while
  the Windows runner does not expose a Vulkan ICD.

So the compile-time contract is verified everywhere, and the runtime contract
is verified where a driver exists. Every job that configures the project uses
`-DFIRE_ENGINE_TUTORIAL_WARNINGS_AS_ERRORS=ON` and caches vcpkg using a key
derived from `vcpkg.json` and `vcpkg-configuration.json` — the pinned baseline
doing double duty as a cache identity.

## Diagnose the likely failures

### CMake cannot find the vcpkg toolchain

If the preset expands to a path that does not exist, confirm `VCPKG_ROOT` in
the same shell:

```shell
printf '%s\n' "$VCPKG_ROOT"
test -f "$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"
```

If `VCPKG_ROOT` changed after the build directory was configured, remove the
disposable `build/` directory or use a fresh binary directory before
configuring again. CMake caches toolchain decisions on the first configure.

### The compiler does not support C++23

The configure or compiler output should identify the selected compiler:

```shell
cmake --preset vcpkg
cmake --build --preset default --verbose
```

Upgrade the compiler or launch the correct developer environment rather than
weakening the project's language requirement.

### Vulkan instance creation fails at runtime

First distinguish a loader problem from a driver-discovery problem. vcpkg does
not install the loader in this release: the executable dynamically opens the
platform's Vulkan loader, which must be installed alongside an implementation.

On macOS, verify the SDK environment and selected manifest:

```shell
printf '%s\n' "$VULKAN_SDK"
printf '%s\n' "$VK_DRIVER_FILES"
test -f "$VK_DRIVER_FILES"
```

On Linux, `vulkaninfo` from the distribution's Vulkan tools package is a useful
independent check:

```shell
vulkaninfo --summary
```

If that cannot enumerate an implementation, the engine will not be able to do
so either.

## What this foundation gives us

At the end of this milestone we have more than a program that prints two
lines:

- dependency declarations live beside the source;
- vcpkg installs only the headers required at build time;
- a pinned registry makes dependency resolution repeatable;
- one set of CMake presets drives local development and CI;
- formatting and static analysis are settled by config files, not opinions;
- compiler warnings are strict without leaking into third-party code;
- the executable builds on every supported platform, and runs as a smoke test
  wherever a Vulkan driver exists; and
- Vulkan ownership starts with deterministic RAII lifetimes.

That is enough infrastructure for the next layer: enumerate physical devices,
inspect their queue families and capabilities, and decide how fireEngine will
select a GPU.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan] — written against an earlier
  version of Vulkan, but still a definitive guide to the API's core concepts.
- [Professional CMake][reading-cmake] — widely regarded as the de facto guide
  to modern CMake, written by Craig Scott, one of CMake's maintainers. It covers
  practical, target-based project structure and cross-platform workflows.
- [vcpkg documentation][reading-vcpkg] — the official reference for manifests,
  registries, versioning, and CMake integration.
- [How to Vulkan][reading-how-to-vulkan] — a compact, code-first tutorial that
  builds a modern Vulkan 1.3 renderer while explaining how its major systems
  fit together.

The [Reading page][reading-page] keeps the site-wide list in one place.

[repository]: https://github.com/nnewson/fireEngine-tutorial
[source-vcpkg-manifest]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/vcpkg.json
[source-vcpkg-configuration]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/vcpkg-configuration.json
[source-cmake-presets]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/CMakePresets.json
[source-cmake]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/CMakeLists.txt
[source-main]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/src/main.cpp
[source-ci]: https://github.com/nnewson/fireEngine-tutorial/blob/0.1/.github/workflows/ci.yml
[vcpkg-manifest-mode]: https://learn.microsoft.com/vcpkg/concepts/manifest-mode
[vcpkg-cmake-integration]: https://learn.microsoft.com/vcpkg/users/buildsystems/cmake-integration
[vulkan-driver-discovery]: https://vulkan.lunarg.com/doc/view/latest/mac/LoaderDriverInterface.html
[vulkan-instance-guide]: https://docs.vulkan.org/tutorial/latest/03_Drawing_a_triangle/00_Setup/01_Instance.html
[reading-page]: {% link _tabs/reading.md %}
[reading-vulkan]: https://www.vulkanprogrammingguide.com
[reading-cmake]: https://crascit.com/professional-cmake/
[reading-vcpkg]: https://learn.microsoft.com/en-gb/vcpkg/
[reading-how-to-vulkan]: https://howtovulkan.com
