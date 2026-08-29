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

### [C++ `std::expected`](https://en.cppreference.com/w/cpp/utility/expected.html)

The cppreference language-library entry for the C++23 vocabulary type that
represents either an expected value or a recoverable error without requiring an
exception.

### [C++ subscript operator](https://en.cppreference.com/w/cpp/language/operators.html#Array_subscript_operator)

The cppreference language reference for overloaded subscripting, including the
multi-argument `operator[]` syntax added in C++23 and used by fireEngine's
matrix type.

### [C++ `std::variant`](https://en.cppreference.com/w/cpp/utility/variant.html)

The cppreference language-library entry for the type-safe discriminated union
used to give a scene node one explicit component role.

### [Catch2 tutorial](https://github.com/catchorg/Catch2/blob/devel/docs/tutorial.md)

The official introduction to Catch2, covering test cases, assertions, sections,
behaviour-driven aliases, and data- and type-driven tests.

### [GLFW documentation](https://www.glfw.org/docs/latest/)

The official guide to GLFW's cross-platform window, input, event, and Vulkan
surface APIs, including the lifetime and platform rules behind them.

### [glTF 2.0 specification: Animations](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations)

The Khronos definition of animation samplers, channels, target nodes and paths,
input timestamps, output values, and supported interpolation modes.

### [glTF 2.0 specification: Buffers, Buffer Views, and Accessors](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#buffers-and-buffer-views)

The Khronos definitions of binary storage, byte ranges, interleaved stride,
typed accessors, and sparse data used when translating glTF geometry and
animation samples.

### [glTF 2.0 specification: Meshes](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#meshes)

The Khronos definitions of mesh primitives, topology, counter-clockwise
winding, and the way mirrored node transforms reverse triangle facing.

### [glTF 2.0 specification: Scenes and Nodes](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#scenes)

The Khronos definition of scenes, ordered root nodes, child hierarchies, and
local transforms in glTF 2.0, providing a concrete interchange model for
scene-graph ownership and traversal.

### [glTF 2.0 specification: Textures](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#textures)

The Khronos definitions of images, samplers, textures, and texture coordinates
used to describe sampled surface colour.

### [fastgltf](https://github.com/spnda/fastgltf)

The C++ glTF parsing library used behind fireEngine's format-specific loading
boundary, including helpers for traversing accessors without assuming packed
buffer layouts.

### [How to Vulkan](https://howtovulkan.com)

A compact, code-first tutorial that builds a modern Vulkan 1.3 renderer while
explaining how its major systems fit together.

### [vcpkg documentation](https://learn.microsoft.com/en-gb/vcpkg/)

The official reference for the cross-platform C and C++ package manager used by
the tutorial, covering manifests, registries, versioning, and CMake integration.

### [`VkFrontFace` reference](https://docs.vulkan.org/refpages/latest/refpages/source/VkFrontFace.html)

The Vulkan reference definition of clockwise and counter-clockwise front faces
after projection into framebuffer coordinates.

### [Vulkan Guide: Depth](https://docs.vulkan.org/guide/latest/depth.html)

The Khronos guide to depth formats, image aspects, layouts, fixed-function
testing, comparisons, and attachment writes.

### [Vulkan specification: Fixed-Function Vertex Post-Processing](https://docs.vulkan.org/spec/latest/chapters/vertexpostproc.html)

The normative path from clip coordinates through perspective division,
clipping, and viewport transformation into rasterization.

### [Vulkan Memory Allocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator)

AMD's open-source allocation library for Vulkan, with documentation and examples
covering memory-type selection, suballocation, resource creation, and allocator
configuration.

### [Your first Slang shader](https://shader-slang.org/docs/first-slang-shader)

The official first step into Slang, covering HLSL-like shader source, entry
points, command-line compilation, SPIR-V output, and cross-target code
generation.
