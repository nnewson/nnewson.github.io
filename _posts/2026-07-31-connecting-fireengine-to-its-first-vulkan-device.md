---
title: Connecting fireEngine to its first Vulkan device
date: 2026-07-31 21:50:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, glfw, cpp, cmake, vcpkg]
description: >-
  Evolve fireEngine from creating a Vulkan instance to opening a window,
  selecting a Vulkan 1.4 physical device, and creating its logical queues.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.2"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.1"
---

Release 0.1 proved that fireEngine could load Vulkan, create an instance, and
destroy it safely. Release 0.2 extends that short vertical slice until the
application is connected to a device that can eventually render and present an
image.

The result still does not draw anything. It opens a window, creates its Vulkan
surface, inspects every available physical device, chooses one that satisfies
the renderer's requirements, creates a logical device, and retrieves its
graphics and presentation queues. Once that startup smoke test succeeds, the
window closes.

This post follows the changes from [release 0.1][release-0-1] to
[release 0.2][release-0-2]. Code links are pinned to 0.2 so the walkthrough
continues to match the published source as fireEngine evolves.

> Source: [fireEngine 0.2]({{ page.release_url }})
>
> Start with the [0.1 foundation post][foundation-post] if you want the full
> toolchain and first-instance setup. This post concentrates on what changed.
{: .prompt-info }

## Extend the startup chain

Release 0.1 stopped after the first two Vulkan objects:

```text
Vulkan-Hpp context
    -> Vulkan instance
```

Release 0.2 turns that into a usable device chain:

```text
GLFW
    -> native window
        -> Vulkan-Hpp context
            -> Vulkan instance
                -> debug messenger (when available)
                -> window surface
                    -> selected physical device
                        -> logical device
                            -> graphics queue
                            -> presentation queue
```

Each arrow represents either a lifetime dependency or information required by
the next step. GLFW must remain initialized while the window exists. The
instance must remain alive while its debug messenger and surface exist. Device
selection needs that surface because presentation support is specific to both a
queue family and a surface. Finally, queues come from the logical device.

The source tree grows to reflect those responsibilities:

```text
include/fire_engine/
├── core/
│   ├── debug.hpp
│   └── log.hpp
├── platform/
│   ├── glfw.hpp
│   └── window.hpp
└── render/
    └── device.hpp
src/
├── core/
│   └── debug.cpp
├── platform/
│   ├── glfw.cpp
│   └── window.cpp
├── render/
│   └── device.cpp
└── main.cpp
```

This is the first architectural split in the tutorial. `core` owns facilities
that can be shared by the rest of the engine, `platform` hides GLFW and native
window-system work, and `render` owns Vulkan device setup. `main.cpp` is left
with orchestration rather than implementation details.

## Bring the window system and loader into the build

Release 0.1 needed only `vulkan-headers`. Its Vulkan-Hpp context discovered the
platform loader dynamically at run time. Release 0.2 adds GLFW and makes the
loader an explicit linked dependency:

```json
{
  "name": "fire-engine-tutorial",
  "version-string": "0.2.0",
  "dependencies": [
    "glfw3",
    "vulkan-headers",
    {
      "name": "vulkan-loader",
      "features": [
        {
          "name": "xcb",
          "platform": "linux"
        },
        {
          "name": "xlib",
          "platform": "linux"
        }
      ]
    }
  ]
}
```

The complete manifest is [`vcpkg.json`][source-vcpkg]. The Linux-only features
give the loader the XCB and Xlib window-system integrations needed by the
supported GLFW backends without applying them to macOS or Windows builds.

The matching CMake changes find and link all three packages:

```cmake
find_package(glfw3 CONFIG REQUIRED)
find_package(VulkanHeaders 1.4 CONFIG REQUIRED)
find_package(VulkanLoader 1.4 CONFIG REQUIRED)

target_link_libraries(fireEngineTutorial PRIVATE
    glfw
    Vulkan::Headers
    Vulkan::Loader
)
```

`Vulkan::Headers` still supplies Vulkan-Hpp. `Vulkan::Loader` now supplies the
loader entry point used by both Vulkan-Hpp and GLFW. It does not supply a
physical-device implementation: a compatible Vulkan driver must still be
installed on the machine.

The target disables Vulkan-Hpp's loader-discovery helper to make that choice
unambiguous:

```cmake
target_compile_definitions(fireEngineTutorial PRIVATE
    VULKAN_HPP_ENABLE_DYNAMIC_LOADER_TOOL=0
    VULKAN_HPP_NO_CONSTRUCTORS
)
```

`VULKAN_HPP_NO_CONSTRUCTORS` carries forward the designated-initializer style
from 0.1. `VULKAN_HPP_ENABLE_DYNAMIC_LOADER_TOOL=0` is new: the program uses the
linked loader's `vkGetInstanceProcAddr` rather than asking Vulkan-Hpp to locate
another loader with `dlopen` or the equivalent platform mechanism.

That change matters on macOS, where the vcpkg loader may not live in a system
library search path. GLFW and Vulkan-Hpp are explicitly connected to the same
loader, while that loader continues to discover the installed KosmicKrisp
driver through the standard Vulkan driver search path.

## Grow one source file into a target

The executable now contains all of the new implementation files and exposes the
public headers only to itself:

```cmake
add_executable(fireEngineTutorial
    src/core/debug.cpp
    src/main.cpp
    src/platform/glfw.cpp
    src/platform/window.cpp
    src/render/device.cpp
)

target_include_directories(fireEngineTutorial PRIVATE include)
```

The project version is also passed into C++ instead of being duplicated in
`main.cpp`:

```cmake
target_compile_definitions(fireEngineTutorial PRIVATE
    FIRE_ENGINE_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
    FIRE_ENGINE_VERSION_MINOR=${PROJECT_VERSION_MINOR}
    FIRE_ENGINE_VERSION_PATCH=${PROJECT_VERSION_PATCH}
)
```

`device.cpp` turns those three components into the exact encoding expected by
Vulkan:

```cpp
constexpr std::uint32_t kVersion = VK_MAKE_API_VERSION(
    0,
    FIRE_ENGINE_VERSION_MAJOR,
    FIRE_ENGINE_VERSION_MINOR,
    FIRE_ENGINE_VERSION_PATCH
);
```

The application metadata reported to the driver therefore stays synchronized
with `project(VERSION 0.2.0)` in [`CMakeLists.txt`][source-cmake].

## Add an error path that is safe during failure

GLFW and Vulkan both report errors through C callbacks. Exceptions must not
escape through those C boundaries, and a formatter failure should not hide the
startup error that the logger was trying to explain. Release 0.2 introduces a
small `noexcept` logger for those paths:

```cpp
template <typename... Args>
void log(
    detail::LogMessage<std::type_identity_t<Args>...> message,
    Args&&... args
) noexcept
{
    try
    {
        std::println(stderr, message.format(), std::forward<Args>(args)...);
    }
    catch (...)
    {
        const std::source_location& location = message.location();
        std::fprintf(
            stderr,
            "A log message could not be formatted at %s:%lu in %s.\n",
            location.file_name(),
            static_cast<unsigned long>(location.line()),
            location.function_name()
        );
    }
}
```

The normal path keeps `std::println` and its checked formatting. The fallback
uses C stdio because it does not throw a C++ exception. The original error is
preserved even if formatting or allocation fails.

### Deliberately allow the format string conversion

The companion `LogMessage` constructor contains a small but important design
choice:

```cpp
template <typename String>
explicit(false) consteval LogMessage(
    const String& format,
    std::source_location location = std::source_location::current()
)
    : format_{format},
      location_{location}
{
}
```

`explicit(false)` is C++'s conditional `explicit` syntax. Because its condition
is `false`, this constructor is deliberately **not** explicit. The logger wants
a string literal to convert implicitly into `LogMessage`, so callers can write:

```cpp
log("GLFW error {}: {}", errorCode, description);
```

instead of constructing an implementation type at every call site. Writing
`explicit(false)` rather than omitting the specifier records that the implicit
conversion is intentional — we explicitly choose not to make this constructor
explicit.

The relaxed call syntax does not relax format checking. `consteval` requires
the conversion at compile time, and the stored `std::format_string<Args...>`
checks the placeholders against the argument types. `std::type_identity_t`
prevents the format parameter from independently deducing `Args`; the values
after it establish the types, then the message is checked against them. The
defaulted `std::source_location` captures the log call for the emergency
fallback.

The complete implementation is in [`log.hpp`][source-log].

## Own GLFW's process-wide lifetime

`Glfw` is a non-copyable, non-movable RAII owner for GLFW's process-wide state.
Its constructor installs error reporting before initialization and connects
GLFW to the linked Vulkan loader:

```cpp
Glfw::Glfw()
{
    glfwSetErrorCallback(errorCallback);

    glfwInitVulkanLoader(vkGetInstanceProcAddr);
    if (glfwInit() != GLFW_TRUE)
    {
        throw std::runtime_error("GLFW initialization failed");
    }

    if (glfwVulkanSupported() != GLFW_TRUE)
    {
        glfwTerminate();
        throw std::runtime_error(
            "GLFW could not find a Vulkan loader and ICD"
        );
    }
}
```

`glfwInitVulkanLoader()` must be called before `glfwInit()`, which is why the
order above matters; [GLFW's Vulkan guide][glfw-vulkan-guide] covers it along
with the rest of the Vulkan entry points used here.

`glfwVulkanSupported()` moves a useful failure earlier. Before creating a
window, the program verifies that GLFW can reach the chosen loader and that the
loader can see at least one installable client driver, or ICD.

The destructor completes the ownership pair:

```cpp
Glfw::~Glfw()
{
    glfwTerminate();
}
```

The type cannot enforce that every window is destroyed first, so that ordering
remains part of its public contract and is made concrete by declaration order
in `main()`.

GLFW also knows which instance extensions its current platform backend needs:

```cpp
std::vector<const char*> Glfw::requiredVulkanExtensions() const
{
    std::uint32_t extensionCount = 0;
    const char** glfwExtensions =
        glfwGetRequiredInstanceExtensions(&extensionCount);

    if (glfwExtensions == nullptr || extensionCount == 0)
    {
        throw std::runtime_error(
            "GLFW returned no required Vulkan instance extensions"
        );
    }
    return {glfwExtensions, glfwExtensions + extensionCount};
}
```

That keeps platform decisions out of the renderer. macOS can request its Metal
surface extension while a Linux GLFW backend can request an X11 extension, and
`Device` consumes the result without branching on the operating system. See
[`glfw.hpp`][source-glfw-header] and [`glfw.cpp`][source-glfw].

## Create a window for Vulkan, not OpenGL

The `Window` wrapper validates its dimensions, then tells GLFW that no client
graphics API context is wanted:

```cpp
Window::Window(int width, int height, const std::string& title)
{
    if (width <= 0 || height <= 0)
    {
        throw std::invalid_argument("Window dimensions must be positive");
    }

    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
    window_ = glfwCreateWindow(
        width,
        height,
        title.c_str(),
        nullptr,
        nullptr
    );

    if (window_ == nullptr)
    {
        throw std::runtime_error("GLFW window creation failed");
    }
}
```

Vulkan performs presentation itself, so asking GLFW to create an OpenGL or
OpenGL ES context would create an unrelated graphics path.

The destructor completes the pair, exactly as `Glfw` does for the library-wide
state:

```cpp
Window::~Window()
{
    glfwDestroyWindow(window_);
}
```

The wrapper's other responsibility is to turn the native window into a Vulkan
surface:

```cpp
vk::raii::SurfaceKHR
Window::createVulkanSurface(const vk::raii::Instance& instance) const
{
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    const VkResult result = glfwCreateWindowSurface(
        static_cast<VkInstance>(*instance),
        window_,
        nullptr,
        &surface
    );

    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(
            "GLFW Vulkan surface creation failed: " +
            vk::to_string(static_cast<vk::Result>(result))
        );
    }
    return {instance, surface};
}
```

GLFW chooses the platform-specific `VkSurfaceKHR` creation call. The raw handle
is immediately wrapped in `vk::raii::SurfaceKHR`, restoring the same automatic
cleanup convention established in 0.1. The full wrapper is in
[`window.cpp`][source-window], and the Vulkan tutorial's
[window surface][vulkan-window-surface] chapter shows what that one GLFW call
replaces on each platform.

## Make validation useful but optional

Validation is tied to the Debug configuration at build time:

```cmake
target_compile_definitions(fireEngineTutorial PRIVATE
    $<$<CONFIG:Debug>:FIRE_ENGINE_ENABLE_VALIDATION>
)
```

The generator expression works with both single-configuration tools such as
Ninja and multi-configuration tools such as Visual Studio. Non-Debug builds do
not pay for the validation setup.

A Debug build still does not assume that the validation layer or debug utility
extension is installed. It queries them independently:

```cpp
const auto layers = context.enumerateInstanceLayerProperties();
support.hasValidationLayer = std::ranges::any_of(
    layers,
    [](const vk::LayerProperties& layer)
    {
        return std::string_view{layer.layerName.data()} ==
               kValidationLayerName;
    }
);

const auto extensions = context.enumerateInstanceExtensionProperties();
support.hasDebugUtils = std::ranges::any_of(
    extensions,
    [](const vk::ExtensionProperties& extension)
    {
        return std::string_view{extension.extensionName.data()} ==
               VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    }
);
```

Both queries sit behind `#ifdef FIRE_ENGINE_ENABLE_VALIDATION`. A non-Debug
build returns an empty support structure immediately and never enumerates
layers or extensions, while `Device` keeps one unconditional call site instead
of spreading build-configuration conditionals through the renderer.

This avoids turning an optional development aid into a runtime requirement.
When debug utilities are available, the messenger requests warnings and errors
across general, validation, and performance messages. Its callback passes the
message to the `noexcept` logger and returns `VK_FALSE`, meaning the callback
observes the error without asking Vulkan to abort the API call.

The same messenger create info is chained into `vkCreateInstance` and then used
to create the owned messenger. Chaining it captures messages produced during
instance creation, before the messenger object itself can exist. The full
support code is in [`debug.cpp`][source-debug].

## Create the instance around a real loader and window

In 0.1, the default `vk::raii::Context` discovered a loader and the instance
requested no extensions. The new `Device` connects its context to the loader
linked by CMake:

```cpp
vk::raii::Context context_{vkGetInstanceProcAddr};
```

Instance creation first checks the loader itself:

```cpp
if (context_.enumerateInstanceVersion() < vk::ApiVersion14)
{
    throw std::runtime_error(
        "The Vulkan loader does not support Vulkan 1.4"
    );
}
```

This is separate from checking a GPU. The loader exposes instance-level Vulkan
operations; each physical device later reports its own supported API version.

The method then combines the extensions required for the active window system
with optional debug support:

```cpp
const debug::InstanceSupport debugSupport =
    debug::queryInstanceSupport(context_);

std::vector<const char*> extensions =
    glfw.requiredVulkanExtensions();
if (debugSupport.hasDebugUtils)
{
    extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
}

const std::vector<const char*> layers =
    debugSupport.hasValidationLayer
        ? std::vector<const char*>{debug::kValidationLayerName}
        : std::vector<const char*>{};
```

Finally, the instance metadata uses the version supplied by CMake and requests
Vulkan 1.4:

```cpp
const vk::ApplicationInfo applicationInfo{
    .pApplicationName = applicationName.c_str(),
    .applicationVersion = kVersion,
    .pEngineName = "No Engine",
    .engineVersion = 0,
    .apiVersion = vk::ApiVersion14,
};
```

The application name moves from 0.1's hard-coded `"Fire Engine Vulkan
Tutorial"` to the `applicationName` passed down from `main()`, so one string
names the window and the Vulkan application. The engine remains `"No Engine"`
with an `engineVersion` of zero: release 0.2 has a clearer source structure,
but nothing is layered beneath the application yet, so repeating the
application's own version there would only invent a second identity.

## Select a physical device by capability

Finding a physical device is not enough. It must be able to serve this window
and the rendering path planned for the next milestones. `inspectDevice()`
therefore applies a sequence of explicit checks. The Vulkan tutorial's
[physical devices and queue families][vulkan-physical-devices] chapter covers
the same ground with a smaller set of requirements.

### Require Vulkan 1.4 on the device

```cpp
if (properties.apiVersion < vk::ApiVersion14)
{
    return std::unexpected(std::format(
        "{}: reports Vulkan {}.{}, requires 1.4",
        deviceName,
        vk::apiVersionMajor(properties.apiVersion),
        vk::apiVersionMinor(properties.apiVersion)
    ));
}
```

Requesting 1.4 from the instance does not prove that every enumerated physical
device supports 1.4. Keeping the checks separate also produces the right
diagnostic: an old loader fails before instance creation, while an old device
is rejected by name during selection.

### Check the rendering features before enabling them

```cpp
const auto features = physicalDevice.getFeatures2<
    vk::PhysicalDeviceFeatures2,
    vk::PhysicalDeviceVulkan13Features
>();
const auto& features13 =
    features.get<vk::PhysicalDeviceVulkan13Features>();

if (features13.dynamicRendering != vk::True)
{
    return std::unexpected(std::format(
        "{}: dynamic rendering is unavailable",
        deviceName
    ));
}
if (features13.synchronization2 != vk::True)
{
    return std::unexpected(std::format(
        "{}: synchronization2 is unavailable",
        deviceName
    ));
}
```

Dynamic rendering removes the need to create render-pass objects for the first
rendering path. Synchronization 2 provides the newer synchronization commands
and structures. Both belong to Vulkan 1.3 and should be present on a conformant
1.4 device; checking them still gives useful diagnostics for preview or unusual
drivers and demonstrates that supported features must be queried before they
are enabled.

### Find graphics and presentation queues

Queue families advertise different work. The selector prefers one family that
can do both graphics and presentation:

```cpp
QueueFamilies result;
const auto queueFamilies = physicalDevice.getQueueFamilyProperties();

for (std::uint32_t index = 0; index < queueFamilies.size(); ++index)
{
    const bool supportsGraphics = static_cast<bool>(
        queueFamilies[index].queueFlags &
        vk::QueueFlagBits::eGraphics
    );
    const bool supportsPresentation =
        physicalDevice.getSurfaceSupportKHR(index, *surface) == vk::True;

    if (supportsGraphics && supportsPresentation)
    {
        return {.graphics = index, .present = index};
    }
    if (supportsGraphics && !result.graphics)
    {
        result.graphics = index;
    }
    if (supportsPresentation && !result.present)
    {
        result.present = index;
    }
}
return result;
```

One shared family allows future swapchain images to use exclusive sharing
without queue-family ownership transfers. Devices with separate graphics and
presentation families remain valid: the function retains the first candidate
for each role and returns them if no combined family exists. Both members are
`std::optional<std::uint32_t>`, so a missing role is representable and
`inspectDevice()` can name exactly which one the device failed to provide.

Presentation capability is queried against `surface`, not treated as a general
device property. A queue that can present to one window-system surface is not
automatically suitable for every surface. The specification's
[window system integration][vulkan-wsi] chapter explains why that pairing, and
not the device alone, is the unit of support.

### Validate the future swapchain path

The release does not create a swapchain yet, but it refuses to select a device
that cannot support the next step:

```cpp
if (!supportsSwapchain(physicalDevice))
{
    return std::unexpected(std::format(
        "{}: {} is unavailable",
        deviceName,
        VK_KHR_SWAPCHAIN_EXTENSION_NAME
    ));
}
if (physicalDevice.getSurfaceFormatsKHR(*surface).empty())
{
    return std::unexpected(std::format(
        "{}: this surface has no supported formats",
        deviceName
    ));
}
if (physicalDevice.getSurfacePresentModesKHR(*surface).empty())
{
    return std::unexpected(std::format(
        "{}: this surface has no supported presentation modes",
        deviceName
    ));
}
```

`VK_KHR_swapchain` supplies swapchain operations. A non-empty surface-format
list means there is at least one image format and colour-space pairing that the
surface accepts. A non-empty presentation-mode list means there is at least one
way to queue images for display.

These checks prevent release 0.2 from declaring success with a device that the
next release would immediately have to reject.

### Keep every rejection reason

`inspectDevice()` returns
[`std::expected<DeviceSelection, std::string>`][std-expected]. Success carries
the physical device and queue-family indices; failure carries the reason that
particular device was unsuitable. A plain `std::optional` would have thrown
that reason away. `std::expected` keeps routine rejection in the return value,
allowing the search to continue to the next device without using exceptions for
control flow.

`choosePhysicalDevice()` keeps those errors while evaluating every device:

```cpp
std::expected<DeviceSelection, std::string> candidate =
    inspectDevice(physicalDevice, surface);
if (!candidate)
{
    rejectionReasons.push_back(std::move(candidate.error()));
    continue;
}
```

If nothing passes, one exception lists every rejection:

```text
No suitable Vulkan physical device was found:
  - Example GPU: reports Vulkan 1.3, requires 1.4
  - Example Software Device: no queue family can present to this surface
```

Those names are illustrative; the actual output comes from the devices and
drivers installed on the machine.

Selection is deterministic. A suitable discrete GPU receives a score of two;
every other suitable device receives one. The first highest-scoring device
wins, so discrete hardware is preferred while integrated GPUs and software
implementations remain supported.

## Create the logical device and queues

A physical device describes hardware capabilities. A logical device is the
application's enabled interface to those capabilities. The tutorial's
[logical device and queues][vulkan-logical-device] chapter is the reference for
this step.

The first task is to create one request for each unique queue family:

```cpp
std::vector<vk::DeviceQueueCreateInfo> queueCreateInfos;
queueCreateInfos.push_back({
    .queueFamilyIndex = selection.graphicsQueueFamily,
    .queueCount = 1,
    .pQueuePriorities = &kQueuePriority,
});

if (selection.presentQueueFamily != selection.graphicsQueueFamily)
{
    queueCreateInfos.push_back({
        .queueFamilyIndex = selection.presentQueueFamily,
        .queueCount = 1,
        .pQueuePriorities = &kQueuePriority,
    });
}
```

Vulkan requires the queue-family entries in device creation to be unique. When
one family performs both jobs, it is requested once and the same queue can be
retrieved for each role. When the roles use separate families, one queue is
requested from each.

`kQueuePriority` is a file-scope `constexpr float` rather than a local. Vulkan
stores `pQueuePriorities` as a pointer and only reads it during
`vkCreateDevice`, so the value it points at must still be alive at that moment.
A local priority inside a helper that returns its create infos would leave a
dangling pointer behind. Static storage removes the question entirely. The
value itself is a relative hint within the family, not an operating-system
thread priority.

The logical device enables exactly the extension and features checked during
inspection:

```cpp
constexpr std::array kRequiredDeviceExtensions = {
    VK_KHR_SWAPCHAIN_EXTENSION_NAME
};

constexpr vk::PhysicalDeviceVulkan13Features enabledFeatures13{
    .synchronization2 = vk::True,
    .dynamicRendering = vk::True,
};

const vk::DeviceCreateInfo deviceCreateInfo{
    .pNext = &enabledFeatures13,
    .queueCreateInfoCount =
        static_cast<std::uint32_t>(queueCreateInfos.size()),
    .pQueueCreateInfos = queueCreateInfos.data(),
    .enabledExtensionCount =
        static_cast<std::uint32_t>(kRequiredDeviceExtensions.size()),
    .ppEnabledExtensionNames = kRequiredDeviceExtensions.data(),
};
```

Querying feature support does not enable it. The `pNext` chain makes dynamic
rendering and synchronization 2 active for the new logical device. Likewise,
discovering `VK_KHR_swapchain` does not enable it; its name must appear in the
device extension list.

After creation, queue index zero is retrieved from each selected family:

```cpp
logicalDevice_ = createLogicalDeviceFor(selection);
graphicsQueue_ = logicalDevice_.getQueue(graphicsQueueFamily_, 0);
presentQueue_ = logicalDevice_.getQueue(presentQueueFamily_, 0);
```

The complete selection and creation path is in [`device.cpp`][source-device].

## Encode destruction order in the `Device` layout

The release keeps the RAII rule from 0.1, but now there are enough dependent
objects for declaration order to matter:

```cpp
vk::raii::Context context_{vkGetInstanceProcAddr};
vk::raii::Instance instance_{nullptr};
vk::raii::DebugUtilsMessengerEXT debugMessenger_{nullptr};
vk::raii::SurfaceKHR surface_{nullptr};
vk::raii::PhysicalDevice physicalDevice_{nullptr};
vk::raii::Device logicalDevice_{nullptr};
vk::raii::Queue graphicsQueue_{nullptr};
vk::raii::Queue presentQueue_{nullptr};
```

The two `std::uint32_t` queue-family indices follow these members in the real
header; they hold no resource, so they play no part in the ordering argument.

C++ destroys members in reverse declaration order. Queue wrappers disappear
before the logical device, the logical device before the surface and instance,
and the instance before its context. Optional objects begin as null RAII
handles, so the same destructor path works whether validation was available or
startup threw partway through construction.

`Device` is non-copyable and non-movable. It is the unique owner of this graph,
and keeping it at a stable address makes the lifetime relationship easy to
reason about. See [`device.hpp`][source-device-header].

## Leave `main()` with the story of startup

The 0.1 `main.cpp` contained the Vulkan context, application metadata, instance
create info, and explicit scope used to demonstrate destruction. In 0.2 those
details move behind focused types:

```cpp
int main()
try
{
    const std::string applicationName = "fireEngine Tutorial";

    fire_engine::Glfw glfw;
    const fire_engine::Window window{800, 600, applicationName};
    const fire_engine::Device device{glfw, window, applicationName};

    if (!*device.graphicsQueue() || !*device.presentQueue())
    {
        throw std::runtime_error("Vulkan returned a null device queue");
    }

    std::println("Selected Vulkan 1.4 device: {}", device.name());
    std::println(
        "Graphics queue family: {}",
        device.graphicsQueueFamily()
    );
    std::println(
        "Present queue family: {}",
        device.presentQueueFamily()
    );
    std::println("Logical device and queues created.");
    return 0;
}
catch (const std::exception& error)
{
    fire_engine::log("Vulkan startup failed: {}", error.what());
    return 1;
}
```

Local declaration order is another lifetime declaration. `device` is destroyed
first, taking its surface with it; `window` is destroyed next; and only then
does `glfw` terminate the process-wide GLFW state.

The queue-handle checks make the smoke test exercise the new accessors instead
of merely printing a claim that queues exist. The function try block continues
to turn any startup exception into a readable error and non-zero exit status,
now through the shared failure-safe logger.

See the complete [`main.cpp`][source-main].

## Configure, build, and run release 0.2

The prerequisite toolchain and `VCPKG_ROOT` setup remain the same as in the
[0.1 post][foundation-post]. Clone the new checkpoint directly with:

```shell
git clone --branch 0.2 --depth 1 \
  https://github.com/nnewson/fireEngine-tutorial.git
cd fireEngine-tutorial
```

Then configure and build through the existing presets:

```shell
cmake --preset vcpkg
cmake --build --preset default
```

Run the executable directly:

```shell
./build/fireEngineTutorial
```

On Windows:

```powershell
.\build\fireEngineTutorial.exe
```

The device name and queue indices depend on the installed hardware and driver.
A successful run has this shape:

```text
Selected Vulkan 1.4 device: <device name>
Graphics queue family: <index>
Present queue family: <index>
Logical device and queues created.
```

The GLFW window closes immediately because this milestone has no event loop or
render loop. That is expected, not a crash.

The same startup path is still registered as a CTest smoke test:

```shell
ctest --preset default
```

The test itself carries over from 0.1. What is new is the 30-second timeout
attached to it:

```cmake
add_test(NAME fireEngineTutorial COMMAND fireEngineTutorial)
set_tests_properties(fireEngineTutorial PROPERTIES TIMEOUT 30)
```

Now that the program talks to a window system, it has a way to block instead of
failing. The timeout prevents a window-system or driver problem from leaving CI
waiting indefinitely.

## Prove the larger contract in CI

Release 0.2 expands CI along with the source. The changed jobs are:

- `clang-format` now checks both `src/` and `include/`;
- `clang-tidy` moves to clang-tidy 22, uses GCC 14 to configure a C++23
  standard-library environment, builds first, and analyses every `.cpp` file
  rather than only `main.cpp`;
- Linux installs GLFW's X11 development dependencies, selects Mesa's Lavapipe
  ICD, and runs both `vulkaninfo` and CTest inside Xvfb; and
- every job that uses vcpkg pins its checkout to one commit instead of tracking
  the tip of the repository.

The build-only scope of the macOS and Windows jobs is unchanged from 0.1. Both
still verify only that the AppleClang and MSVC C++23 builds succeed: the hosted
macOS runner does not provide the required KosmicKrisp environment, and the
hosted Windows runner exposes no Vulkan ICD at all.

That vcpkg pin is worth calling out because it completes the reproducibility
argument started in 0.1. `vcpkg-configuration.json` already pinned the registry
baseline, which fixes the package versions. Pinning the CI checkout also fixes
the vcpkg client that reads them. A local build gets the same client-level
guarantee when its vcpkg checkout uses that recorded commit.

The Linux job now proves considerably more than instance creation: a headless
CI runner can open a virtual X11 window, create a surface, select a Vulkan 1.4
software device, and create its logical queues. See the full
[`ci.yml`][source-ci].

## Publish the API documentation

Release 0.2 also adds a documentation job. The Doxygen comments used throughout
the new headers and source files are not decoration: they are checked.
`WARN_IF_UNDOCUMENTED`, `WARN_IF_DOC_ERROR`, and `WARN_IF_INCOMPLETE_DOC` are
enabled, and `WARN_AS_ERROR = FAIL_ON_WARNINGS` turns an undocumented parameter
or a broken reference into a failed build. Adding a member without documenting
it breaks CI in the same way that misformatting it does.

Every run uploads the generated HTML as the `doxygen-html` artifact. Deploying
it to GitHub Pages is gated behind a repository variable, `PUBLISH_DOXYGEN`, so
a fork gets the checks without inheriting a publishing step it did not ask for.
The published result for this repository is the
[fireEngine tutorial API reference][api-reference], and the configuration lives
in [`docs/Doxyfile`][source-doxygen].

## Diagnose the new failure boundaries

The expanded startup chain makes its failures more specific.

### GLFW cannot find a loader and ICD

This means GLFW cannot reach the linked Vulkan loader or the loader cannot
discover a driver. Installing `vulkan-loader` through vcpkg solves only the
first half; the machine still needs a Vulkan implementation.

On macOS, install the supported LunarG SDK containing KosmicKrisp. That preview
driver requires Apple Silicon and macOS 26; an Intel Mac or an older macOS
release cannot satisfy this milestone's requirements no matter how the project
is built. Its installer should register the driver manifest in Vulkan's normal
search path, so sourcing the SDK environment is no longer a normal requirement
for this release. `VK_DRIVER_FILES` remains available as an override when
selecting among multiple installed drivers.

On Linux, `vulkaninfo --summary` remains a useful independent test. If it cannot
enumerate an implementation, fireEngine cannot select one.

### No Vulkan physical devices were found

This is a different failure from the one below, and the distinction is the
point. GLFW found a loader and a minimally functional ICD, the instance was
created, and the surface exists, but `enumeratePhysicalDevices()` returned
nothing at all. No device was rejected for being unsuitable — there was nothing
to inspect.

Check the selected driver configuration with `vulkaninfo --summary`, and verify
that an override such as `VK_DRIVER_FILES` points at the intended manifest. The
runtime is present, but it is not exposing a physical device to this process.

### No suitable Vulkan physical device was found

Read the indented rejection list. Each entry identifies a device and the first
requirement it failed: Vulkan 1.4, dynamic rendering, synchronization 2,
graphics queues, presentation queues, `VK_KHR_swapchain`, surface formats, or
presentation modes.

This is more actionable than a generic device-creation failure because it
distinguishes an unsupported GPU from a missing window-system capability.

### Validation produces no messages

Validation is enabled only in Debug builds, and even then only when the
`VK_LAYER_KHRONOS_validation` layer is installed. A successful build without
that optional layer is expected to continue without validation.

## What release 0.2 gives us

The distance from 0.1 to 0.2 is the distance from "Vulkan is present" to "this
application has a usable rendering endpoint":

- GLFW and the platform window now have explicit RAII owners;
- GLFW and Vulkan-Hpp share one loader linked through vcpkg;
- the native window becomes a Vulkan presentation surface;
- Debug builds use validation when the runtime provides it;
- error callbacks share a checked, `noexcept` logging path;
- the loader and every candidate physical device are checked separately;
- queue-family selection supports combined and split graphics/presentation
  families;
- device rejection explains exactly which required capability is missing;
- selection prefers discrete hardware without excluding integrated or software
  devices;
- dynamic rendering, synchronization 2, and swapchain support are both checked
  and enabled;
- member and local declaration order encode dependency-safe destruction;
- documentation warnings fail CI, so the new headers stay described; and
- CI pins its vcpkg checkout as well as the registry baseline.

There is still no swapchain, image view, command buffer, or presented frame.
That boundary is useful: release 0.2 proves that the platform and device chain
is sound before image ownership and synchronization make the renderer more
complicated. The next milestone can start from known graphics and presentation
queues and build the first swapchain on top of them.

[release-0-1]: {{ page.previous_release_url }}
[release-0-2]: {{ page.release_url }}
[foundation-post]: {% post_url 2026-07-30-creating-fireengine-vulkan-foundation %}
[source-vcpkg]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/vcpkg.json
[source-cmake]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/CMakeLists.txt
[source-log]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/include/fire_engine/core/log.hpp
[source-glfw-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/include/fire_engine/platform/glfw.hpp
[source-glfw]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/src/platform/glfw.cpp
[source-window]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/src/platform/window.cpp
[source-debug]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/src/core/debug.cpp
[source-device-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/include/fire_engine/render/device.hpp
[source-device]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/src/render/device.cpp
[source-main]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/src/main.cpp
[source-ci]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/.github/workflows/ci.yml
[source-doxygen]: https://github.com/nnewson/fireEngine-tutorial/blob/0.2/docs/Doxyfile
[api-reference]: https://nnewson.github.io/fireEngine-tutorial/
[glfw-vulkan-guide]: https://www.glfw.org/docs/latest/vulkan_guide.html
[vulkan-window-surface]: https://docs.vulkan.org/tutorial/latest/03_Drawing_a_triangle/01_Presentation/00_Window_surface.html
[vulkan-physical-devices]: https://docs.vulkan.org/tutorial/latest/03_Drawing_a_triangle/00_Setup/03_Physical_devices_and_queue_families.html
[vulkan-logical-device]: https://docs.vulkan.org/tutorial/latest/03_Drawing_a_triangle/00_Setup/04_Logical_device_and_queues.html
[vulkan-wsi]: https://docs.vulkan.org/spec/latest/chapters/VK_KHR_surface/wsi.html
[std-expected]: https://en.cppreference.com/w/cpp/utility/expected
