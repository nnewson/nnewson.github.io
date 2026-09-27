---
icon: fas fa-book
order: 5
---

A small collection of books and websites that provide useful background for
the tools and techniques used while building fireEngine.

## Books

### [C++ Software Design](https://www.oreilly.com/library/view/c-software-design/9781098113155/)

Klaus Iglberger's guide to managing dependencies and software change in modern
C++, using design principles and patterns to build flexible, maintainable
systems without losing sight of practical trade-offs.

### [Foundations of Game Engine Development, Volume 1: Mathematics](https://foundationsofgameenginedev.com/#fged1)

Eric Lengyel's focused treatment of vectors, matrices, transforms, geometry,
and the mathematical conventions used to build game engines.

### [Game Engine Architecture](https://www.gameenginebook.com/)

Jason Gregory's broad guide to building game engines, including resource
management, runtime architecture, rendering, animation, gameplay systems, and
the engineering trade-offs that connect them.

### [Professional CMake](https://crascit.com/professional-cmake/)

Widely regarded as the de facto guide to modern CMake, written by Craig Scott,
one of CMake's maintainers. It covers practical, target-based project structure,
dependency management, testing, packaging, and cross-platform workflows.

### [Real-Time Rendering](https://www.realtimerendering.com/)

The classic end-to-end reference for real-time rendering systems, connecting
the graphics pipeline and hardware with transforms, shading, effects,
optimisation, and acceleration techniques.

### [Refactoring](https://martinfowler.com/books/refactoring.html)

Martin Fowler's guide to improving the design of existing code through small,
behaviour-preserving transformations, supported by tests that keep each change
safe and observable.

### [Vulkan Programming Guide](https://www.vulkanprogrammingguide.com)

Written against an earlier version of Vulkan, but still a definitive,
example-rich guide to the API's core model, including queues, commands, memory,
synchronization, and presentation.

## Websites

### C++ standard library

Reference pages for the standard-library types fireEngine leans on, mostly for
ownership, lifetime, and error signalling.

#### [`std::span`](https://en.cppreference.com/w/cpp/container/span)

The cppreference entry for the non-owning contiguous view used by scene draw
lists and immutable recording inputs. Copying a span copies its view, not the
storage or the storage's lifetime.

#### [`std::chrono::steady_clock`](https://en.cppreference.com/w/cpp/chrono/steady_clock)

The cppreference entry for the monotonic clock used to measure elapsed frame
time without being affected by changes to the system wall clock.

#### [`std::counting_semaphore`](https://en.cppreference.com/w/cpp/thread/counting_semaphore)

The cppreference entry for the C++20 synchronization primitive used to park
fireEngine's persistent recording helper until the coordinator publishes work.

#### [`std::atomic::wait`](https://en.cppreference.com/w/cpp/atomic/atomic/wait)

The cppreference entry for blocking until an atomic value changes, including
the need to recheck the value after a wake rather than treating notification
alone as the state transition.

#### [`std::exception_ptr`](https://en.cppreference.com/w/cpp/error/exception_ptr)

The cppreference entry for capturing an exception on one thread and rethrowing
it later after another thread has completed its borrowed work.

#### [`std::expected`](https://en.cppreference.com/w/cpp/utility/expected.html)

The cppreference language-library entry for the C++23 vocabulary type that
represents either an expected value or a recoverable error without requiring an
exception.

#### [`std::ranges::upper_bound`](https://en.cppreference.com/w/cpp/algorithm/upper_bound)

The cppreference algorithms entry covering the ordered search used to find the
first animation keyframe strictly after a playback time.

#### [subscript operator](https://en.cppreference.com/w/cpp/language/operators.html#Array_subscript_operator)

The cppreference language reference for overloaded subscripting, including the
multi-argument `operator[]` syntax added in C++23 and used by fireEngine's
matrix type.

#### [`std::variant`](https://en.cppreference.com/w/cpp/utility/variant.html)

The cppreference language-library entry for the type-safe discriminated union
used to give a scene node one explicit component role.

### Vulkan Guide

Khronos's practical articles, used where the specification is precise but hard
to quote.

#### [Depth](https://docs.vulkan.org/guide/latest/depth.html)

The Khronos guide to depth formats, image aspects, layouts, fixed-function
testing, comparisons, and attachment writes.

#### [Image Copies](https://docs.vulkan.org/guide/latest/image_copies.html)

The Khronos guide to copying between buffers and images, including subresource
selection, tightly packed data, row length, image height, and copy extents.

#### [Swapchain Semaphore Reuse](https://docs.vulkan.org/guide/latest/swapchain_semaphore_reuse.html)

The Khronos guide to indexing presentation wait semaphores by acquired
swapchain image rather than frame slot, preventing unsafe binary-semaphore
reuse.

#### [Synchronization Examples](https://docs.vulkan.org/guide/latest/synchronization_examples.html)

Worked Synchronization 2 examples for image layout transitions, transfer
operations, and making uploaded data visible to later shader reads.

#### [Vulkan Validation Overview](https://docs.vulkan.org/guide/latest/validation_overview.html)

The Khronos guide to Vulkan valid usage, VUIDs, undefined behaviour, and the
development-time role of the validation layer.

### Vulkan specification

The normative text, cited where exact wording matters.

#### [Fixed-Function Vertex Post-Processing](https://docs.vulkan.org/spec/latest/chapters/vertexpostproc.html)

The normative path from clip coordinates through perspective division,
clipping, and viewport transformation into rasterization.

#### [Command Buffers](https://docs.vulkan.org/spec/latest/chapters/cmdbuffers.html)

The normative definition of primary and secondary command buffers, recording,
execution, inheritance, usage flags, and command-pool synchronization.

#### [Push Descriptors](https://docs.vulkan.org/spec/latest/chapters/descriptorsets.html)

The normative definition of push-descriptor layouts and commands, including
the lifetime of descriptor contents recorded directly into a command buffer.

#### [Window System Integration](https://docs.vulkan.org/spec/latest/chapters/VK_KHR_surface/wsi.html)

The normative definition of surfaces, swapchains, image acquisition,
presentation, and the lifetime rules governing window-system resources.

### Vulkan reference pages

Individual structures and extensions whose fields or guarantees a post depends
on.

#### [`VkFrontFace`](https://docs.vulkan.org/refpages/latest/refpages/source/VkFrontFace.html)

The Vulkan reference definition of clockwise and counter-clockwise front faces
after projection into framebuffer coordinates.

#### [`VkCommandBufferInheritanceRenderingInfo`](https://docs.vulkan.org/refpages/latest/refpages/source/VkCommandBufferInheritanceRenderingInfo.html)

The Vulkan reference for the attachment formats, sample count, and view mask a
secondary command buffer inherits when it executes inside dynamic rendering.

#### [`VK_KHR_swapchain_maintenance1`](https://docs.vulkan.org/refpages/latest/refpages/source/VK_KHR_swapchain_maintenance1.html)

The Vulkan extension reference for presentation fences, explicit image release,
and other facilities that make swapchain lifetime and replacement easier to
control.

#### [`VkSwapchainPresentFenceInfoKHR`](https://docs.vulkan.org/refpages/latest/refpages/source/VkSwapchainPresentFenceInfoKHR.html)

The Vulkan reference for associating fences with presentation operations so an
application can determine when related presentation resources may be safely
recycled.

### glTF 2.0 specification

The source-format definitions the loader translates into engine descriptions.

#### [Animations](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations)

The Khronos definition of animation samplers, channels, target nodes and paths,
input timestamps, output values, and supported interpolation modes.

#### [Buffers, Buffer Views, and Accessors](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#buffers-and-buffer-views)

The Khronos definitions of binary storage, byte ranges, interleaved stride,
typed accessors, and sparse data used when translating glTF geometry and
animation samples.

#### [Meshes](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#meshes)

The Khronos definitions of mesh primitives, topology, counter-clockwise
winding, and the way mirrored node transforms reverse triangle facing.

#### [Scenes and Nodes](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#scenes)

The Khronos definition of scenes, ordered root nodes, child hierarchies, and
local transforms in glTF 2.0, providing a concrete interchange model for
scene-graph ownership and traversal.

#### [Textures](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#textures)

The Khronos definitions of images, samplers, textures, and texture coordinates
used to describe sampled surface colour.

#### [Transformations](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#transformations)

The Khronos definition of node translation, rotation, and scale properties,
their composition into a local matrix, and the way those transforms accumulate
through a hierarchy. It fixes the order an importer must preserve and the
decomposition a matrix-valued node has to yield.

### Shading with Slang

The shading language fireEngine compiles to SPIR-V, and the operations its
shaders use.

#### [Slang `Sample` reference](https://docs.shader-slang.org/en/stable/external/core-module-reference/types/0texture-01/sample-0.html)

The Slang core-module reference for filtered texture sampling with an implicit
level of detail, as used by fireEngine's fragment shader.

#### [Your first Slang shader](https://shader-slang.org/docs/first-slang-shader)

The official first step into Slang, covering HLSL-like shader source, entry
points, command-line compilation, SPIR-V output, and cross-target code
generation.

### Build and test tooling

CMake, CTest, vcpkg, and Catch2 behaviour the build and its test gates rely
on.

#### [Catch2 tutorial](https://github.com/catchorg/Catch2/blob/devel/docs/tutorial.md)

The official introduction to Catch2, covering test cases, assertions, sections,
behaviour-driven aliases, and data- and type-driven tests.

#### [CTest `FAIL_REGULAR_EXPRESSION`](https://cmake.org/cmake/help/latest/prop_test/FAIL_REGULAR_EXPRESSION.html)

The CMake test property that turns matching standard output or standard error
into a failed test independently of the executable's exit code.

#### [CTest `RESOURCE_LOCK`](https://cmake.org/cmake/help/latest/prop_test/RESOURCE_LOCK.html)

The CMake test property for serialising tests that share one global resource,
such as the Vulkan device used by fireEngine's application scenarios.

#### [vcpkg documentation](https://learn.microsoft.com/en-gb/vcpkg/)

The official reference for the cross-platform C and C++ package manager used by
the tutorial, covering manifests, registries, versioning, and CMake integration.

### Libraries

Third-party libraries used behind fireEngine's own interfaces.

#### [GLFW documentation](https://www.glfw.org/docs/latest/)

The official guide to GLFW's cross-platform window, input, event, and Vulkan
surface APIs, including the lifetime and platform rules behind them.

#### [fastgltf](https://github.com/spnda/fastgltf)

The C++ glTF parsing library used behind fireEngine's format-specific loading
boundary, including helpers for traversing accessors without assuming packed
buffer layouts.

#### [Vulkan Memory Allocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator)

AMD's open-source allocation library for Vulkan, with documentation and examples
covering memory-type selection, suballocation, resource creation, and allocator
configuration.

### Articles

Standalone pieces that shaped a specific decision.

#### [Fix Your Timestep!](https://gafferongames.com/post/fix_your_timestep/)

Glenn Fiedler's explanation of fixed, variable, and semi-fixed simulation
steps, and why elapsed-time policy matters as a real-time update loop grows.

#### [How to Vulkan](https://howtovulkan.com)

A compact, code-first tutorial that builds a modern Vulkan 1.3 renderer while
explaining how its major systems fit together.
