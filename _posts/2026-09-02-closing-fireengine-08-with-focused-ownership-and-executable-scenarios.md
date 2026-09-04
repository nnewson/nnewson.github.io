---
title: "Closing fireEngine 0.8 with focused ownership and executable scenarios"
date: 2026-09-02 10:00:00 +0100
categories: [fireEngine, Development]
tags: [fireengine, "0.8", architecture, testing, vulkan, validation, synchronization, cmake, cpp]
description: >-
  Keep fireEngine's public renderer facade small, organise Vulkan owners by
  lifetime, and verify the complete imported-scene path through bounded device
  scenarios.
release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8"
previous_release_url: "https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7"
---

A rendering architecture's boundaries have to be both visible and executable.
They are visible in the facade, the ownership split, and the generated
documentation. They become executable when the real application can cross
them under validation. The same correct-looking image can otherwise hide a
loader leaking into the renderer, an early destruction, an untested material
path, or a dangling borrower.

Release 0.8 closes its imported-scene work on both sides of that claim. Vulkan
ownership types sit behind the public renderer facade. Plan-scoped compiled
resources and presentation-scoped depth have focused owners. Four bounded
scenarios then drive loading, animation, compilation, replacement, fallback
texturing, and presentation recreation through the real application and
Vulkan device.

The aim is not to replace focused unit tests with end-to-end tests. It is to
give each kind of test a question it can answer. Forty-seven device-free cases
check deterministic rules in isolation; a smaller scenario suite checks that
those rules still compose after the code crosses the Vulkan boundary.

This is the closing detailed post based on release 0.8. The
[architectural overview][planning-post] sets out the complete release, and the
[0.8 architecture page][architecture-0-8] records its final structure. The
[presentation post][presentation-post] establishes the second completion
domain exercised here, while the original [testing post][testing-post]
explains why most engine decisions should remain testable without a GPU.

> Code for this article: [fireEngine 0.8][release-0-8]
>
> Previous release: [fireEngine 0.7][release-0-7]
>
> Architecture: [fireEngine 0.8 architecture][architecture-0-8]
>
> The detailed 0.8 series is now complete. This post joins its public/internal
> ownership boundary to the executable scenarios that verify the whole path.
{: .prompt-info }

## Treat the facade and its documentation as a contract

Adding images, textures, depth, animation, loading, and presentation
replacement increases the amount of Vulkan implementation code. It should not
increase the amount of Vulkan that an application must understand.

The public renderer remains one small facade:

```text
application-visible                    renderer implementation

Renderer                               render/detail/
├── prepare(RenderAssets, Scene)        ├── Device + allocator
├── drawFrame(Scene)                    ├── FrameInFlight
├── recreatePresentation(Window)        ├── Swapchain + Pipeline
├── waitIdle()                          ├── CompiledResources
└── info()                              └── DepthBuffer + image owners

plain C++ descriptions          --->   Vulkan RAII ownership
RenderResult comes back         <---   submission and presentation
```

[`renderer.hpp`][source-renderer-header] forward-declares the application types
it consumes and contains no Vulkan type. Allocator, buffer, device, frame,
image, pipeline, swapchain, compilation, and selection declarations live below
[`include/fire_engine/render/detail/`][source-render-detail]. Their namespace is
`fire_engine::detail`, so their location and qualification say the same thing:
they are implementation vocabulary, not a second supported renderer API.

This boundary is deliberately narrower than “no public header includes
Vulkan.” The platform window still exposes the GLFW-Vulkan surface bridge, and
0.8's internal debug support still uses Vulkan types. The claim is that
application rendering goes through `Renderer`, and renderer-owned Vulkan types
do not leak out through that facade.

Source layout alone is easy to erode. The documentation build therefore makes
the distinction observable. The [public Doxyfile][source-public-doxyfile]
recurses through the supported inputs but excludes `src` and every `detail`
path. The [internal Doxyfile][source-internal-doxyfile] includes both. One
[documentation CI job][source-ci] builds the two views and then checks their
file indexes:

```text
public documentation                  internal documentation
├── supported headers                 ├── supported headers
├── README                            ├── detail headers
└── no detail/ or src                 └── implementation sources
          |                                      |
          +-------------- CI check --------------+
```

The result is more useful than an `@internal` label scattered through comments.
A reader of the public API cannot accidentally discover a renderer helper and
mistake its current signature for a compatibility promise. A reader studying
the tutorial implementation still has a complete generated reference.

## Split owners when they change for different reasons

Hiding everything behind a pImpl prevents Vulkan from leaking outward, but it
does not by itself produce coherent ownership inside. By the end of 0.8,
`renderer.cpp` has several distinct lifetimes:

```text
Renderer::Impl
├── Device + MemoryAllocator  -> renderer lifetime
├── FrameInFlight             -> submission lifetime
├── RenderPreparation         -> dependency-plan lifetime
├── CompiledResources         -> selected asset lifetime
└── PresentationState         -> surface-compatible lifetime
    ├── Swapchain
    ├── DepthBuffer
    ├── Pipeline
    └── presentation fences
```

Two extracted owners make the important split explicit.

[`CompiledResources`][source-compiled-header] owns the plan-scoped Vulkan
representation: compiled mesh buffers, images, samplers, the persistent white
fallback, and the dense render-object lookup used while recording. Its
implementation also owns the setup-time staging and upload operation in 0.8.
Those objects change when preparation selects a new dependency graph, not when
the window changes size.

[`DepthBuffer`][source-depth-header] owns one depth format, image allocation,
and depth-only view. It stays inside `PresentationState`, because its extent and
format must remain compatible with the swapchain and pipeline. It is a focused
direct owner rather than part of compiled scene content.

The colour and depth image paths also share named
[subresource ranges][source-subresource-ranges]. That small extraction removes
duplicated Vulkan structure literals while preserving the meaningful
difference between colour and depth aspects.

This is separation by reason to change. `CompiledResources` changes when scene
dependencies change. `DepthBuffer` changes when presentation compatibility
changes. The renderer coordinates both without becoming their storage format.

## Build a complete resource candidate before replacing anything

Compiled resources contain both owners and borrowers. A compiled texture owns
a sampler but points to a compiled image. A compiled render-object entry points
to its mesh and texture. Replacing those members independently could leave a
borrower referring to an owner already destroyed.

Release 0.8 makes replacement a small transaction inside
[`compiled_resources.cpp`][source-compiled-resources]:

```text
1. build candidate owners
   images + textures + meshes + optional new fallback
                  |
                  v
2. build candidate borrowers
   render-object lookup -> candidate mesh and texture owners
                  |
             all succeeded
                  v
3. commit in borrower-first order
   objects -> meshes -> fallback pair -> textures -> images
```

No member of the current graph changes while allocation, staging, upload,
sampler construction, or lookup construction can still fail. The candidate's
`unique_ptr` owners keep their heap addresses when moved into the live graph,
so the new borrowers remain valid across the commit.

The order during the final handoff is load-bearing. Replacing the render-object
lookup first removes every old mesh and texture borrower before their owners
are replaced. Regular textures are replaced before regular images for the same
reason. The fallback pair moves only on its first construction; subsequent
preparations reuse the already-owned white image and sampler.

Declaration order supplies the matching destruction rule. The lookup is
destroyed before meshes and textures, texture borrowers before images, and the
fallback sampler before its image. The protocol is therefore the same whether
the graph changes during preparation or dies with the renderer:

```text
build the new graph -> replace borrowers -> release old owners
```

Command recording does not need access to that ownership graph. A
`CompiledDraw` value contains only the vertex and index buffer handles, index
count, sampler, image view, and material colour required for one draw. That is
the narrow capability the renderer consumes after `CompiledResources` has
proved the requested ID is present.

Version 0.8 still borrows the sole `FrameInFlight` command pool and fence for
image uploads after earlier work has finished. Extracting compilation ownership
does not pretend that synchronization seam has disappeared; the 0.9 resource
compiler gives uploads their own context later.

## Make the boundary executable and its failures observable

At this point the boundary is inspectable: applications see one facade, public
documentation excludes its implementation vocabulary, resources are grouped
by lifetime, and replacement order is explicit. None of that proves the
arrangement survives submitted graphics work and outstanding presentation.

Exercising it only counts if a violation becomes a test failure. In Debug
builds the [validation callback][source-debug] gives each selected message a
severity-specific prefix:

```text
Vulkan validation warning: ...
Vulkan validation error: ...
```

The [CTest registration][source-cmake] fails a scenario whenever the error
prefix appears, even if the application itself exits normally:

```cmake
FAIL_REGULAR_EXPRESSION "Vulkan validation error:"
```

Warnings stay visible for diagnosis but remain non-fatal, because a validation
layer's performance suggestion is not a correctness failure. The scenarios can
therefore reject a validation-reported lifetime violation rather than merely
demonstrate that several frames happened to render.

They use the normal [`main.cpp`][source-main], not a second test-only renderer:
the same GLFW lifetime, window, loader, animation call, transform update,
preparation operation, recording, submission, presentation, and shutdown as an
interactive run. Only their inputs and bounded stopping conditions differ.

## Exercise the hardest composition with repeated preparation

`prepare-twice` creates the most demanding ownership transition in the suite.
The first frame uses the original imported resources. The application then
adds an untextured material and render object, attaches a translated instance
to the scene, updates world transforms, and calls `prepare()` again.

```text
prepare original graph
        |
draw and present frame 1
        |
mutate assets + add scene dependency
        |
retire device work + presentation work
        |
build and commit replacement graph
        |
draw and present frames 2, 3, and 4
```

This proves more than calling `prepare()` twice before drawing. The original
compiled buffers, images, samplers, and lookup have been consumed by submitted
commands, and presentation may still own work ordered after that submission.
The renderer must retire both completion domains before releasing the old
graph or reusing its frame upload context.

The remaining three frames revisit the replacement in the normal draw path.
They commonly revisit all three presentation-fence entries on the observed
swapchain, but the scenario does not turn that observation into a portable
claim: swapchain image count and acquisition order remain driver-selected.

This scenario found a real protocol gap. Whole-group retirement waited for a
submitted presentation fence and cleared its bookkeeping, but originally left
the signalled fence unchanged. A later presentation could then submit that
already-signalled fence again. Both per-image reuse and whole-group retirement
now call the same `preparePresentFence()` operation, which waits, resets, and
clears one submitted entry consistently.

The important testing lesson is not the particular bug. It is that preserving
`PresentationState` while replacing compiled content creates a lifetime
composition that neither a preparation unit test nor a recreation-only test
can exercise alone.

## Use smaller scenarios to cover the remaining composition risks

`prepare-twice` carries the central lifetime argument. Three smaller scenarios
cover the other ways independently correct pieces could fail to compose:

| Scenario | What it composes | What it proves that unit tests do not |
|---|---|---|
| `basic` | loading, animation, upload, depth-tested drawing, and presentation | the production executable can carry imported content through a real device path |
| `untextured` | an optional texture, the persistent white fallback, and the normal descriptor path | both material forms reach the same complete device contract |
| `resize` | repeated presentation replacement around unchanged compiled content | at a stable non-zero extent, compiled scene resources survive repeated presentation replacement; OS-driven resize events and extent changes remain untested |

The `basic` scenario presents three frames with a fixed animation step of `0.8`
seconds. AnimatedCube's two-second clip is sampled at `0.8`, `1.6`, and `0.4`
seconds, crossing both keyframe intervals and the loop boundary. It also runs
from an isolated working directory. CMake supplies absolute build-tree asset
and shader paths, so neither AnimatedCube nor `scene.spv` can be found by
accident through the directory containing the executable.

The `untextured` scenario reuses the imported mesh with a material that has no
base-colour texture. Compilation supplies the persistent one-pixel white image
and sampler, allowing recording and the shader to keep the single descriptor
contract established in the [texture-compilation post][texture-post].

The `resize` scenario requests recreation after each of three presented frames.
It uses the current non-zero framebuffer extent rather than synthesising a
window-system resize, so it proves repeated replacement, retirement, depth and
pipeline compatibility, and projection refresh. It does not prove callback
delivery, minimise and restore, a display move, or a changed physical extent.

The scenario loop counts presented frames rather than attempts. An out-of-date
acquisition can request recreation and retry without quietly shortening the
run. Shared metadata holds each scenario's frame limit and trigger while the
fixture construction stays explicit; 0.8 does not invent a general-purpose
scenario framework for four bounded cases.

CTest gives every device scenario a 30-second timeout and the shared
`fireEngineTutorialVulkan` resource lock, preventing concurrent tests from
contending for the same device. Two additional Debug registrations rerun
`prepare-twice` and `resize` with `VK_LAYER_VALIDATE_SYNC=1`, where validation
support is known to be compiled in.

## Prove that the test gate is sensitive, not merely present

A validation test that has only ever been green proves that its executable can
exit, not that its observation mechanism detects the intended defect. During
development, a positive-control run temporarily removed the
[`resetFences()` call][source-present-fence-reset] from
`preparePresentFence()`, then ran the standard and synchronization-validation
`prepare-twice` registrations. Both produced the validation-error prefix and
failed through CTest's regular-expression gate.

The same mutation can be exercised against a Debug build of 0.8 with:

```console
ctest --test-dir build -C Debug \
  -R '^fireEngineTutorialPrepareTwice(Smoke|SyncValidation)$' \
  --output-on-failure
```

The recreation registrations stayed green under that fault. That difference
located the missing reset in the path that preserves a `PresentationState`
across post-present resource preparation. Recreation destroys the old state,
so it does not reuse the same signalled fence.

The injected fault is not part of release 0.8. The reproducible recipe is the
one-line removal and those two named tests; the mutation was restored after the
run. The original full validation message and device environment were not
retained, however, so this remains an author-reported experiment rather than a
result independently recoverable from the tag. That distinction matters:
validation behaviour can depend on the implementation, and the matched message
is what would let another reader recognise the same failure.

Future positive controls should retain the exact patch, command, validation
message, and device and driver environment. The environment limits the claim
rather than merely documenting its provenance. The invalid code itself should
still be removed after the experiment; a small recipe is more useful than a
permanent broken mode.

## Let asymmetric evidence support one conclusion

The final Debug configuration registers 53 tests:

```text
47 device-free Catch2 cases
 4 standard Vulkan scenarios
 2 synchronization-validation variants
--
53 CTest registrations
```

That asymmetry is intentional. Maths, scene traversal, asset and animation
validation, loading policy, preparation caching, SPIR-V loading, and swapchain
selection have focused deterministic tests. The Vulkan scenarios are reserved
for questions that require the real integration path: compiled descriptors,
submitted ownership, presentation retirement, and replacement across a
device.

The [CI workflow][source-ci] reflects the same division. Ubuntu runs the full
Debug suite in Xvfb through Lavapipe. Hosted macOS and Windows jobs verify the
AppleClang and MSVC builds but do not claim device execution on drivers those
runners do not provide. Formatting, clang-tidy, terminology, and the public/
internal documentation boundary remain separate gates.

One software Vulkan implementation is valuable continuous evidence, not proof
of every presentation environment. Interactive resize, minimise/restore, and
display-move checks remain manual and explicit instead of disappearing behind
a broad “CI passed” claim.

That closes the 0.8 roadmap. The next release can change scheduling rather than
repairing the content path: dedicated upload ownership, immutable recording
input, two frames in flight, and conditional parallel command recording all
arrive behind the boundaries verified here. The completed
[0.9 architecture][architecture-0-9] shows that next state without requiring
this walkthrough as a prerequisite.

The normal result is still one rotating textured cube, but that image is no
longer the whole argument. The facade, focused owners, replacement transaction,
and generated documentation make the architecture's boundaries visible. The
bounded scenarios cross those same boundaries after real submission and
presentation, while the validation gate makes a reported violation observable.
A boundary that can be inspected and exercised is stronger evidence than
either a tidy source tree or a correct-looking frame on its own.

## Recommended reading

- [C++ Software Design][reading-cpp-design] — practical guidance for making
  dependencies and reasons to change visible without turning every boundary
  into an inheritance hierarchy.
- [Catch2 tutorial][reading-catch2] — the focused test framework used for the
  47 device-free cases beneath the scenario layer.
- [CTest `FAIL_REGULAR_EXPRESSION`][reading-fail-regex] — how matching test
  output can fail a run independently of the executable's exit code.
- [CTest `RESOURCE_LOCK`][reading-resource-lock] — the global-resource
  mechanism used to prevent device scenarios from running concurrently.
- [Vulkan Validation Overview][reading-validation] — why valid usage is an
  explicit development concern and how the Khronos validation layer reports
  violations.

The [Reading page][reading-page] keeps the site-wide list in one place.

[release-0-7]: {{ page.previous_release_url }}
[release-0-8]: {{ page.release_url }}
[planning-post]: {% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}
[architecture-0-8]: {% link _architecture/0.8.md %}
[architecture-0-9]: {% link _architecture/0.9.md %}
[presentation-post]: {% post_url 2026-08-31-making-fireengines-presentation-state-replaceable %}
[testing-post]: {% post_url 2026-08-09-testing-fireengine-without-a-gpu %}
[texture-post]: {% post_url 2026-08-28-compiling-and-sampling-fireengines-first-texture %}
[source-renderer-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/renderer.hpp>
[source-render-detail]: <https://github.com/nnewson/fireEngine-tutorial/tree/0.8/include/fire_engine/render/detail>
[source-public-doxyfile]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/docs/Doxyfile>
[source-internal-doxyfile]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/docs/Doxyfile.internal>
[source-ci]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/.github/workflows/ci.yml>
[source-compiled-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/compiled_resources.hpp>
[source-compiled-resources]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/compiled_resources.cpp>
[source-depth-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/depth_buffer.hpp>
[source-subresource-ranges]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/image_subresource_ranges.hpp>
[source-present-fence-reset]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/render/renderer.cpp#L715-L729>
[source-main]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/main.cpp>
[source-debug]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/src/core/debug.cpp>
[source-cmake]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/CMakeLists.txt>
[reading-cpp-design]: <https://www.oreilly.com/library/view/c-software-design/9781098113155/>
[reading-catch2]: <https://github.com/catchorg/Catch2/blob/devel/docs/tutorial.md>
[reading-fail-regex]: <https://cmake.org/cmake/help/latest/prop_test/FAIL_REGULAR_EXPRESSION.html>
[reading-resource-lock]: <https://cmake.org/cmake/help/latest/prop_test/RESOURCE_LOCK.html>
[reading-validation]: <https://docs.vulkan.org/guide/latest/validation_overview.html>
[reading-page]: {% link _tabs/reading.md %}
