---
title: Preparing fireEngine for its first frame
date: 2026-08-01 14:05:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, vulkan, vma, swapchain, glfw, cpp, cmake, vcpkg]
description: >-
  Prepare fireEngine for rendering by introducing Vulkan Memory Allocator,
  creating a window swapchain, and viewing its presentable images.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.3"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.2"
---

Release 0.2 connected fireEngine to a Vulkan 1.4 device with graphics and
presentation queues. Release 0.3 uses that foundation to create the resources
that will eventually hold and display a rendered frame.

The result still does not draw. It creates a Vulkan Memory Allocator for future
engine-owned resources, configures a swapchain for the current window and
surface, obtains the presentable images owned by that swapchain, and creates an
image view for each one. Once the startup smoke test proves that complete chain,
the window closes.

This post follows the changes from [release 0.2][release-0-2] to
[release 0.3][release-0-3]. Code links are pinned to 0.3 so the walkthrough
continues to match the published source as fireEngine evolves.

> Source: [fireEngine 0.3]({{ page.release_url }})
>
> Start with the [0.2 device post][device-post] if you want the window, surface,
> physical-device selection, and logical-device setup. This post concentrates
> on what changed.
{: .prompt-info }

## Introducing VMA, swapchains, and image views

Release 0.3 introduces three pieces that give the selected device somewhere to
put a frame:

- the **Vulkan Memory Allocator**, usually shortened to **VMA**, is a library
  that sits above Vulkan's explicit device-memory API. Vulkan exposes memory
  heaps, memory types, allocations, and binding as separate operations. That
  control is valuable, but building a fast general-purpose allocator around it
  is not part of fireEngine's purpose. VMA will choose suitable memory types,
  suballocate from larger blocks, and create future buffers and images without
  hiding the Vulkan objects themselves;
- a **swapchain** is the collection of images shared between the application
  and the presentation engine. The application acquires an available image,
  renders into it, queues it for presentation, and then repeats with another
  image. To configure the swapchain, fireEngine must query what the selected
  device can do with this particular surface, then choose a format, extent,
  image count, presentation mode, alpha mode, and queue-family sharing mode
  from the supported options; and
- an **image view** describes how Vulkan should interpret an image. The image
  is the storage; the view selects its format, dimensionality, aspect, mip
  levels, and array layers. Later dynamic-rendering commands will refer to
  these views as colour attachments rather than using the swapchain images
  directly.

Release 0.3 creates the allocator but deliberately makes no allocation through
it yet. The first engine-owned buffer will arrive after command objects, when
the tutorial has somewhere to record the operations that use it.

One boundary is important: VMA does not allocate the swapchain images. The
presentation engine owns those images and exposes their handles through the
swapchain. fireEngine owns the VMA allocator for later resources, the swapchain
object, and the image views it creates over the swapchain-owned images.

## Extend the ownership chain

Release 0.2 stopped at two queues retrieved from the logical device:

```text
GLFW
    -> native window
        -> Vulkan instance and surface
            -> physical and logical device
                -> graphics queue
                -> presentation queue
```

Release 0.3 grows two branches from that device:

```text
GLFW
    -> native window
        -> Vulkan instance and surface
            -> physical and logical device
                -> graphics and presentation queues
                -> VMA allocator
                -> swapchain
                    -> presentable images (owned by the swapchain)
                        -> image views (owned by fireEngine)
```

The allocator needs the instance, physical device, and logical device. The
swapchain needs the logical device and surface, the selected queue-family
indices, and the window's current framebuffer size. Both therefore have to be
destroyed before `Device`, while the image views must disappear before their
parent swapchain.

The source tree expresses the new rendering responsibilities directly:

```text
include/fire_engine/render/
├── allocator.hpp
├── device.hpp
└── swapchain.hpp
src/render/
├── allocator.cpp
├── device.cpp
└── swapchain.cpp
```

`MemoryAllocator` owns VMA's opaque allocator handle. `Swapchain` owns the
Vulkan-Hpp RAII swapchain and image views. `Device` remains the owner of the
Vulkan handles both depend on.

## Add VMA through vcpkg

The manifest moves to version 0.3.0 and adds one dependency:

```json
{
  "name": "fire-engine-tutorial",
  "version-string": "0.3.0",
  "dependencies": [
    "glfw3",
    "vulkan-memory-allocator",
    "vulkan-headers",
    {
      "name": "vulkan-loader",
      "features": [
        { "name": "xcb", "platform": "linux" },
        { "name": "xlib", "platform": "linux" }
      ]
    }
  ]
}
```

The complete manifest is [`vcpkg.json`][source-vcpkg]. vcpkg supplies VMA's
header and CMake package, just as it already supplies GLFW, the Vulkan headers,
and the loader. There is no separate SDK environment to configure.

CMake discovers and links the imported target:

```cmake
find_package(VulkanMemoryAllocator CONFIG REQUIRED)

# ...

target_link_libraries(fireEngineTutorial PRIVATE
    GPUOpen::VulkanMemoryAllocator
    glfw
    Vulkan::Headers
    Vulkan::Loader
)
```

The two new implementation files join the executable, and the project version
becomes 0.3.0. VMA is a large third-party header, so the MSVC configuration also
lowers warnings for imported external headers with `/external:W0`. fireEngine's
own code remains under `/W4 /WX`; the dependency is not required to satisfy the
project's warning policy. See the full [`CMakeLists.txt`][source-cmake].

## Give dependent objects read-only access to the device

In 0.2, `Device` could keep most of its Vulkan objects private because only its
own implementation used them. The allocator and swapchain now need those
objects to create resources with the same device chain.

Release 0.3 adds narrow `const` accessors:

```cpp
[[nodiscard]] const vk::raii::Instance& instance() const noexcept;
[[nodiscard]] const vk::raii::SurfaceKHR& surface() const noexcept;
[[nodiscard]] const vk::raii::PhysicalDevice& physicalDevice() const noexcept;
[[nodiscard]] const vk::raii::Device& logicalDevice() const noexcept;
```

Returning references avoids copying RAII owners and makes the lifetime
relationship visible: neither `MemoryAllocator` nor `Swapchain` acquires
ownership of these handles. The existing queue-family accessors provide the
remaining information required to choose the swapchain's sharing mode.

See [`device.hpp`][source-device-header] and
[`device.cpp`][source-device].

## Create one RAII owner for VMA

VMA exposes a C API and an opaque `VmaAllocator` handle. The public header
forward-declares its underlying type rather than including VMA's large header:

```cpp
struct VmaAllocator_T;

// ...

class MemoryAllocator final
{
public:
    explicit MemoryAllocator(const Device& device);
    ~MemoryAllocator();

    MemoryAllocator(const MemoryAllocator&) = delete;
    MemoryAllocator& operator=(const MemoryAllocator&) = delete;
    MemoryAllocator(MemoryAllocator&&) = delete;
    MemoryAllocator& operator=(MemoryAllocator&&) = delete;

    [[nodiscard]] VmaAllocator_T* handle() const noexcept;

private:
    VmaAllocator_T* allocator_ = nullptr;
};
```

The class is deliberately small. It establishes one owner, releases that owner
in its destructor, and exposes the handle later resource classes will need.
Copy and move operations stay disabled so its place in the startup lifetime is
unambiguous. The public declaration is in
[`allocator.hpp`][source-allocator-header].

### Connect VMA to the linked Vulkan loader

VMA's implementation lives in exactly one translation unit:

```cpp
#define VMA_STATIC_VULKAN_FUNCTIONS 1
#define VMA_DYNAMIC_VULKAN_FUNCTIONS 0
#define VMA_IMPLEMENTATION
#include <vk_mem_alloc.h>
```

`VMA_STATIC_VULKAN_FUNCTIONS` tells VMA to call the Vulkan functions exported
by the loader already linked through vcpkg. Disabling
`VMA_DYNAMIC_VULKAN_FUNCTIONS` prevents VMA from constructing a second dynamic
loading path. This matches the decision made in 0.2 for Vulkan-Hpp and GLFW:
all three use the same explicit loader dependency. VMA's
[configuration reference][vma-configuration] documents these macros alongside
its other build-time switches.

### Describe the Vulkan device to VMA

Creating the allocator requires the complete device chain and the API version:

```cpp
VmaAllocatorCreateInfo createInfo{};
createInfo.physicalDevice =
    static_cast<VkPhysicalDevice>(*device.physicalDevice());
createInfo.device = static_cast<VkDevice>(*device.logicalDevice());
createInfo.instance = static_cast<VkInstance>(*device.instance());
createInfo.vulkanApiVersion = VK_API_VERSION_1_4;

const VkResult result = vmaCreateAllocator(&createInfo, &allocator_);
```

This is the only structure in the project that does not use a C++20
designated initializer. `VmaAllocatorCreateInfo` is a versioned C structure
with many optional fields. A partial designated initializer makes Clang warn
about every field intentionally omitted. Value-initializing the whole structure
first leaves optional values—including `flags`—at zero, then the assignments
make the four settings used by this milestone explicit.

If creation fails, the constructor converts VMA's `VkResult` into a readable
Vulkan result name and throws. If it succeeds, destruction is the inverse:

```cpp
MemoryAllocator::~MemoryAllocator()
{
    vmaDestroyAllocator(allocator_);
}
```

The complete implementation is in [`allocator.cpp`][source-allocator]. No
buffer or image allocation appears here yet; this release proves that VMA can
connect to the selected device without prematurely introducing resource upload
and command-recording concerns.

## Query the surface again at swapchain creation

Device selection in 0.2 rejected devices without surface formats or
presentation modes. Swapchain creation still queries the surface again because
these capabilities belong to the current device-and-surface pair and provide
all the configuration values needed now:

```cpp
struct SurfaceSupport
{
    vk::SurfaceCapabilitiesKHR capabilities;
    std::vector<vk::SurfaceFormatKHR> formats;
    std::vector<vk::PresentModeKHR> presentModes;
};

// ...

SurfaceSupport querySurfaceSupport(const Device& device)
{
    return {
        .capabilities = device.physicalDevice()
                            .getSurfaceCapabilitiesKHR(*device.surface()),
        .formats = device.physicalDevice()
                       .getSurfaceFormatsKHR(*device.surface()),
        .presentModes = device.physicalDevice()
                            .getSurfacePresentModesKHR(*device.surface()),
    };
}
```

The capability structure supplies image-count limits, supported extents,
transforms, usage flags, and alpha modes. The two vectors supply the supported
format/colour-space pairs and presentation scheduling modes.

Vulkan requires every presentation surface to support colour-attachment usage.
The implementation nevertheless verifies that bit. A conformant driver always
passes, but the project currently targets preview Vulkan 1.4 drivers too, and
the defensive check mirrors the feature checks retained during device
selection.

## Choose the swapchain configuration

The [Vulkan window-system integration specification][vulkan-wsi] defines what
the surface reports and which values swapchain creation may choose. fireEngine
turns those possibilities into a small, deterministic policy.

### Prefer an sRGB surface format

Each surface format combines a channel layout with a colour space. fireEngine
prefers BGRA with an sRGB transfer function and an sRGB nonlinear colour space:

```cpp
constexpr vk::SurfaceFormatKHR kPreferredSurfaceFormat{
    .format = vk::Format::eB8G8R8A8Srgb,
    .colorSpace = vk::ColorSpaceKHR::eSrgbNonlinear,
};

// ...

const auto preferred = std::ranges::find(formats, kPreferredSurfaceFormat);
return preferred != formats.end() ? *preferred : formats.front();
```

The two halves of that pair do different jobs. With an sRGB image format,
Vulkan converts the renderer's linear colour output to sRGB encoding as it
writes the attachment. The nonlinear sRGB colour space then tells the
presentation engine how to interpret the values already stored there. If the
exact pair is unavailable, the first supported pair is a valid fallback.
Device selection already guarantees that `formats` is non-empty, and the
helper documents that precondition next to the `front()` call.

### Prefer mailbox, fall back to FIFO

The presentation mode determines how completed images enter the display's
presentation queue. Release 0.3 chooses mailbox when the surface exposes it:

```cpp
return std::ranges::find(presentModes, vk::PresentModeKHR::eMailbox) !=
               presentModes.end()
           ? vk::PresentModeKHR::eMailbox
           : vk::PresentModeKHR::eFifo;
```

**Mailbox** retains the newest queued image, replacing an older waiting image
when the presentation engine has not consumed it yet. It is a useful low-latency
choice when the renderer can run ahead of the display, but support is optional.

**FIFO** queues images in order and presents them as the display advances. The
Vulkan specification guarantees it for every surface, which makes it the safe
fallback. On the Apple M2 Pro used for this checkpoint, KosmicKrisp exposes
FIFO rather than mailbox, so the smoke-test output makes the selected fallback
visible instead of silently assuming the preferred path ran.

### Use framebuffer pixels for the extent

Some platforms provide a fixed `currentExtent`; when they do, the swapchain
must use it. Otherwise fireEngine asks GLFW for the current framebuffer size
and clamps it to the surface's supported range:

```cpp
if (capabilities.currentExtent.width !=
    std::numeric_limits<std::uint32_t>::max())
{
    return capabilities.currentExtent;
}

const vk::Extent2D framebufferExtent = window.framebufferExtent();
if (framebufferExtent.width == 0 || framebufferExtent.height == 0)
{
    throw std::runtime_error("The window framebuffer has zero area");
}
return {
    .width = std::clamp(framebufferExtent.width,
                        capabilities.minImageExtent.width,
                        capabilities.maxImageExtent.width),
    .height = std::clamp(framebufferExtent.height,
                         capabilities.minImageExtent.height,
                         capabilities.maxImageExtent.height),
};
```

The new `Window::framebufferExtent()` uses `glfwGetFramebufferSize`, not the
logical window size. That distinction matters on high-DPI displays. An
800-by-600 window can have a 1600-by-1200 framebuffer; using logical coordinates
would halve each dimension, creating an image with one-quarter the pixel count
that still appears to work after the window system scales it.

A minimized window may report zero in either dimension, which is why the
clamped path checks before it clamps: `std::clamp` against a minimum extent
would otherwise turn an empty framebuffer into a plausible-looking size. On
platforms where the surface leaves extent selection to the application,
swapchain creation therefore rejects that transient state for now. A later
event loop and resize path can wait for a non-zero framebuffer before
recreating the swapchain.

See [`window.hpp`][source-window-header] and
[`window.cpp`][source-window].

### Request one image beyond the minimum

The surface advertises a minimum and possibly a maximum swapchain image count.
fireEngine asks for one more than the minimum to leave room for presentation
while rendering progresses:

```cpp
const std::uint32_t desiredCount = capabilities.minImageCount + 1;
return capabilities.maxImageCount > 0
           ? std::min(desiredCount, capabilities.maxImageCount)
           : desiredCount;
```

A maximum of zero means there is no finite upper limit, not that the surface
supports zero images. When a maximum exists, the request is capped to it.

### Respect the supported transform and alpha mode

The swapchain adopts `currentTransform`, which requests no rotation or flip
beyond the transform the surface already reports. For composition with other
windows, fireEngine walks an ordered list and takes the first mode the surface
supports:

```cpp
constexpr std::array kPreferredModes = {
    vk::CompositeAlphaFlagBitsKHR::eOpaque,
    vk::CompositeAlphaFlagBitsKHR::ePreMultiplied,
    vk::CompositeAlphaFlagBitsKHR::ePostMultiplied,
    vk::CompositeAlphaFlagBitsKHR::eInherit,
};
for (const vk::CompositeAlphaFlagBitsKHR mode : kPreferredModes)
{
    if (static_cast<bool>(capabilities.supportedCompositeAlpha & mode))
    {
        return mode;
    }
}
throw std::runtime_error(
    "The presentation surface has no supported composite-alpha mode"
);
```

This is more portable than hard-coding opaque. Vulkan platforms are allowed to
offer only another composite-alpha mode, so the selection remains valid on
window systems whose capabilities differ from the development machine. Vulkan
nevertheless guarantees that `supportedCompositeAlpha` contains at least one
bit, and the list covers every defined mode. The throw therefore diagnoses
non-conformant driver output rather than an ordinary surface configuration.

All of these helpers and their documented assumptions live in
[`swapchain.cpp`][source-swapchain].

## Account for graphics and presentation queue families

Release 0.2 deliberately supported both a single queue family that handles
graphics and presentation and two separate families. Swapchain creation now
turns that distinction into an image-sharing choice. It begins with the
comparison itself:

```cpp
const std::array queueFamilies = {
    device.graphicsQueueFamily(),
    device.presentQueueFamily()
};
const bool usesSeparateQueueFamilies = queueFamilies[0] != queueFamilies[1];
```

When both operations use the same family, exclusive sharing is the natural
choice. When the families differ, concurrent sharing allows either family to
access the images without explicit queue-family ownership transfers. That
keeps this first presentation path simple; a later renderer can revisit the
trade-off if profiling justifies more elaborate ownership transitions.

That single boolean then drives three fields of the create info in the next
section: the sharing mode itself, and the queue-family count and pointer that
accompany it. The exclusive path clears both of those rather than leaving an
irrelevant family list attached, so the structure states exactly which fields
Vulkan will read in either mode.

## Create the swapchain and retrieve its images

With every choice made, the create info brings the policy together:

```cpp
const vk::SwapchainCreateInfoKHR createInfo{
    .surface = *device.surface(),
    .minImageCount = chooseImageCount(support.capabilities),
    .imageFormat = surfaceFormat.format,
    .imageColorSpace = surfaceFormat.colorSpace,
    .imageExtent = imageExtent,
    .imageArrayLayers = 1,
    .imageUsage = vk::ImageUsageFlagBits::eColorAttachment,
    .imageSharingMode = usesSeparateQueueFamilies
        ? vk::SharingMode::eConcurrent
        : vk::SharingMode::eExclusive,
    .queueFamilyIndexCount = usesSeparateQueueFamilies
        ? static_cast<std::uint32_t>(queueFamilies.size())
        : 0U,
    .pQueueFamilyIndices = usesSeparateQueueFamilies
        ? queueFamilies.data()
        : nullptr,
    .preTransform = support.capabilities.currentTransform,
    .compositeAlpha = chooseCompositeAlpha(support.capabilities),
    .presentMode = presentMode,
    .clipped = vk::True,
};
```

Each image has one layer and colour-attachment usage because the first frame
will render colour directly into it. `clipped` allows pixels hidden behind
other windows to be discarded rather than preserving results the user cannot
see.

Vulkan-Hpp gives the swapchain exception-safe ownership, then returns its image
handles:

```cpp
swapchain_ = vk::raii::SwapchainKHR{device.logicalDevice(), createInfo};
images_ = swapchain_.getImages();
```

The difference in wrapper types records the ownership boundary.
`vk::raii::SwapchainKHR` is owned by `Swapchain`; the `vk::Image` values are
non-owning handles because destroying the swapchain releases the images.

There is no `oldSwapchain` yet. This checkpoint creates once and exits. When
the renderer gains an event loop and resize handling, recreation will need to
pass the old handle and carefully replace the resources that depend on its
images.

## Give every image a two-dimensional colour view

The eventual colour-attachment commands need views, so release 0.3 creates one
for every image in swapchain order:

```cpp
for (const vk::Image image : images)
{
    const vk::ImageViewCreateInfo createInfo{
        .image = image,
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange =
            {
                .aspectMask = vk::ImageAspectFlagBits::eColor,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1,
            },
    };
    imageViews.emplace_back(device, createInfo);
}
```

Each view describes a two-dimensional colour image using the swapchain's chosen
format. Swapchain images have one mip level and one array layer here, so the
subresource range covers exactly that single colour surface.

The view does not allocate, copy, or own the image's pixels. It is an
application-owned Vulkan object that gives later commands a typed window onto
swapchain-owned storage.

## Encode the swapchain destruction order in its layout

The public owner keeps the swapchain, its non-owning image handles, and its
owned views together:

```cpp
vk::raii::SwapchainKHR swapchain_{nullptr};
std::vector<vk::Image> images_;
std::vector<vk::raii::ImageView> imageViews_;
vk::Format imageFormat_ = vk::Format::eUndefined;
vk::PresentModeKHR presentMode_ = vk::PresentModeKHR::eFifo;
vk::Extent2D extent_{};
```

C++ destroys members in reverse declaration order. The plain format, mode, and
extent values disappear first, followed by the image-view vector. Only after
every owned view has released its Vulkan handle does the RAII swapchain get
destroyed. The non-owning image handles require no destruction of their own.

The accessors expose the state needed by the smoke test and later rendering
code without exposing mutable ownership:

```cpp
[[nodiscard]] std::size_t imageCount() const noexcept;
[[nodiscard]] vk::Format imageFormat() const noexcept;
[[nodiscard]] vk::PresentModeKHR presentMode() const noexcept;
[[nodiscard]] vk::Extent2D extent() const noexcept;
[[nodiscard]] const std::vector<vk::Image>& images() const noexcept;
[[nodiscard]] const std::vector<vk::raii::ImageView>&
imageViews() const noexcept;
```

See the complete [`swapchain.hpp`][source-swapchain-header].

## Leave `main()` with the new startup story

The entry point now reads as the complete release checkpoint:

```cpp
const std::string applicationName = "fireEngine Tutorial";

fire_engine::Glfw glfw;
const fire_engine::Window window{800, 600, applicationName};
const fire_engine::Device device{glfw, window, applicationName};
const fire_engine::MemoryAllocator allocator{device};
const fire_engine::Swapchain swapchain{device, window};
```

Local declaration order is lifetime policy. Destruction runs backwards:

1. `swapchain` releases its image views and swapchain;
2. `allocator` releases VMA;
3. `device` releases queues, logical device, surface, and instance;
4. `window` destroys the GLFW window; and
5. `glfw` terminates its process-wide state.

The smoke test checks that VMA returned a handle, the swapchain returned at
least one image, and the image and view counts agree. It then prints every
choice that is useful to compare between platforms:

```cpp
std::println("VMA allocator created.");
std::println(
    "Swapchain created: {} images at {}x{} ({}, {}).",
    swapchain.imageCount(),
    swapchain.extent().width,
    swapchain.extent().height,
    vk::to_string(swapchain.imageFormat()),
    vk::to_string(swapchain.presentMode())
);
```

Reporting the presentation mode matters because mailbox support is optional;
without it, the most platform-dependent swapchain choice would remain hidden.
See the complete [`main.cpp`][source-main].

## Configure, build, and run release 0.3

The C++23 compiler, CMake, Ninja, and `VCPKG_ROOT` prerequisites remain the
same as in the [0.2 post][device-post]. Clone the checkpoint directly with:

```shell
git clone --branch 0.3 --depth 1 \
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

A successful run has this shape:

```text
Selected Vulkan 1.4 device: Apple M2 Pro
Graphics queue family: 0
Present queue family: 0
Logical device and queues created.
VMA allocator created.
Swapchain created: 3 images at 1600x1200 (B8G8R8A8Srgb, Fifo).
```

That is captured output rather than a template. From this release onwards these
posts show real runs, because the values themselves have started to be worth
comparing — and comparison only means something if the machine is named.
Release 0.3 was captured on an Apple M2 Pro running macOS 26, using the
KosmicKrisp driver from the LunarG SDK. Each later post will state its own test
machine, which will not always be this one.

The exact device, queue indices, image count, pixel dimensions, format, and
presentation mode all depend on the driver, display, and window system. The
1600-by-1200 extent above comes from an 800-by-600 window on a Retina display;
it demonstrates why the code asks for framebuffer pixels.

The window still closes immediately because this release has no event loop or
render loop. That is expected. The same path remains available as a CTest smoke
test:

```shell
ctest --preset default
```

CTest now proves that startup reaches a Vulkan 1.4 device, creates the VMA
allocator, creates a swapchain, retrieves its images, and creates a matching
view for each one.

## Prove the wider chain in CI

`ci.yml` does not change in this release, which is the interesting part. The
jobs established in 0.2 already cover the new work:

- vcpkg restores VMA alongside GLFW, the headers, and the loader. Because CI
  installs dependencies straight from the manifest, adding the package needed
  no workflow change;
- `clang-format` already walks `src/` and `include/`, while `clang-tidy`
  analyzes every `.cpp` with first-party headers included by its header filter.
  The two new implementation files and their headers are therefore checked
  from the moment they arrive; and
- the Linux job still selects Mesa's Lavapipe ICD and runs CTest inside Xvfb.

That last job now proves considerably more than device selection. A headless
runner with a software Vulkan implementation creates a VMA allocator, queries
its virtual X11 surface, creates a swapchain, and creates an image view for
every presentable image the swapchain reports. See the full
[`ci.yml`][source-ci].

## Diagnose the new failure boundaries

Release 0.3 adds failures that occur after device selection but before any
rendering command exists.

### VMA allocator creation failed

The error includes VMA's Vulkan result. The allocator receives handles that
were already used successfully to create the logical device, so this points to
an invalid allocator configuration or a driver/runtime failure rather than a
missing physical device.

### The presentation surface does not support color attachments

Vulkan requires every surface to advertise colour-attachment usage, so a
conformant driver never reaches this message. It exists for the same reason as
the Vulkan 1.3 feature checks kept in 0.2: preview drivers are not always
conformant, and naming the missing capability beats an unexplained failure
inside swapchain creation.

### The window framebuffer has zero area

The window is currently minimized or otherwise has no drawable pixels. This
release exits because it has no event loop in which to wait. Swapchain
recreation will eventually turn this from a startup error into a temporary
state.

### The presentation surface has no supported composite-alpha mode

The fallback chain covers opaque, pre-multiplied, post-multiplied, and
inherited alpha. Vulkan requires `supportedCompositeAlpha` to contain at least
one bit, so a conformant surface never reaches this message. It instead points
to non-conformant driver or window-system output rather than fireEngine's
configuration.

### Swapchain or image-view creation throws `vk::SystemError`

Surface capabilities can change between device selection and swapchain
creation. Display configuration, window-system state, and driver support are
all relevant. The selected format, presentation mode, extent, image count,
usage, transform, alpha mode, and queue families must remain compatible with
the surface at the moment Vulkan creates the swapchain.

Validation in a Debug build is particularly useful here: it can identify the
specific create-info field that violated the current surface contract.

## What release 0.3 gives us

Release 0.2 established a device capable of rendering and presentation.
Release 0.3 gives that device memory infrastructure and somewhere presentable
to render:

- VMA is installed through vcpkg and connected to the project's linked Vulkan
  loader;
- one RAII `MemoryAllocator` owns the allocator that future resources will use;
- device accessors expose dependencies without transferring ownership;
- the window reports physical framebuffer pixels for high-DPI-correct images;
- current surface capabilities, formats, and presentation modes are queried;
- BGRA sRGB is preferred with a supported-format fallback;
- mailbox presentation is preferred with guaranteed FIFO fallback;
- the requested image count respects both surface minimum and maximum;
- surface transform and composite-alpha support are honoured;
- combined and split graphics/presentation queue families select appropriate
  image sharing;
- the presentation engine's images remain clearly distinguished from
  engine-owned allocations;
- each swapchain image receives a matching two-dimensional colour view;
- C++ declaration order makes views die before the swapchain and both new
  owners die before `Device`; and
- the smoke test reports the selected swapchain policy instead of merely
  asserting that creation succeeded.

There is still no command pool, command buffer, synchronization object, render
loop, or presented frame. There is also no vertex buffer yet: although VMA is
ready, resource allocation waits until command objects provide the next piece
of the rendering path.

That makes 0.3 a useful boundary. The platform can supply presentable storage,
the engine can describe those images as colour attachments, and future
resources have an allocator. The next release can concentrate on recording
work rather than extending startup in several directions at once.

## Recommended reading

- [Vulkan Programming Guide][reading-vulkan] — a detailed treatment of
  Vulkan's memory, image, swapchain, queue, command, and synchronization model.
  Its examples predate current Vulkan, but its explanation of the API's
  explicit ownership remains valuable.
- [How to Vulkan][reading-how-to-vulkan] — a compact, code-first modern Vulkan
  guide whose swapchain and resource sections provide a useful comparison with
  this tutorial's RAII design.
- [Vulkan Memory Allocator][reading-vma] — the library's source, documentation,
  configuration reference, and examples. This is the primary reference for
  the allocator introduced here rather than a book about Vulkan memory in
  general.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-2]: {{ page.previous_release_url }}
[release-0-3]: {{ page.release_url }}
[device-post]: {% post_url 2026-07-31-connecting-fireengine-to-its-first-vulkan-device %}
[source-vcpkg]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/vcpkg.json
[source-cmake]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/CMakeLists.txt
[source-window-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/include/fire_engine/platform/window.hpp
[source-window]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/src/platform/window.cpp
[source-device-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/include/fire_engine/render/device.hpp
[source-device]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/src/render/device.cpp
[source-allocator-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/include/fire_engine/render/allocator.hpp
[source-allocator]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/src/render/allocator.cpp
[source-swapchain-header]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/include/fire_engine/render/swapchain.hpp
[source-swapchain]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/src/render/swapchain.cpp
[source-main]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/src/main.cpp
[source-ci]: https://github.com/nnewson/fireEngine-tutorial/blob/0.3/.github/workflows/ci.yml
[vulkan-wsi]: https://docs.vulkan.org/spec/latest/chapters/VK_KHR_surface/wsi.html
[vma-configuration]: https://gpuopen-librariesandsdks.github.io/VulkanMemoryAllocator/html/configuration.html
[reading-page]: {% link _tabs/reading.md %}
[reading-vulkan]: https://www.vulkanprogrammingguide.com
[reading-how-to-vulkan]: https://howtovulkan.com
[reading-vma]: https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator
