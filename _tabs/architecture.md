---
icon: fas fa-sitemap
order: 4
---

Each fireEngine release from 0.7 onwards has two complementary records:

- a standalone architecture document describing the system as released; and
- a development story showing the decisions, evidence, experiments, and
  trade-offs that produced it.

The architecture documents do not require earlier versions to be read first.
The posts retain their useful sequence within each release, while the source
tag remains the authority on implementation details. Earlier releases are
omitted because their architecture is too simple to warrant a separate
reference.

## fireEngine 0.9 — multithreaded command recording

Version 0.9 separates mutable preparation from immutable recording input, then
conditionally records one frame with a coordinator and one helper. Its
development story is organised around the questions and measurements that
decided which experiments survived.

> **Architecture as released:** [fireEngine 0.9 architecture]({% link _architecture/0.9.md %})
>
> **Source and downloads:** [GitHub release 0.9](https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.9)
>
> **Every post for this release:** [posts tagged 0.9](/tags/0-9/)
{: .prompt-info }

### 0.9 design and evidence

- [Mapping fireEngine's path to multithreaded rendering]({% post_url 2026-09-04-mapping-fireengines-path-to-multithreaded-rendering %}) — release map
- [Proving fireEngine's secondary command path before measuring it]({% post_url 2026-09-12-proving-fireengines-secondary-command-path-before-measuring-it %})
- [Measuring fireEngine's CPU work before adding another thread]({% post_url 2026-09-13-measuring-fireengines-cpu-work-before-adding-another-thread %})
- [Making fireEngine's recording boundary safe before adding another thread]({% post_url 2026-09-15-making-fireengines-recording-boundary-safe-before-adding-another-thread %})
- [Rebaselining fireEngine before adding another recording thread]({% post_url 2026-09-17-rebaselining-fireengine-before-adding-another-recording-thread %})
- [Coordinating fireEngine's second recording participant]({% post_url 2026-09-18-coordinating-fireengines-second-recording-participant %})
- [Deciding when fireEngine's second recording participant earns its overhead]({% post_url 2026-09-20-deciding-when-fireengines-second-recording-participant-earns-its-overhead %})

## fireEngine 0.8 — animated glTF rendering

Version 0.8 carries imported scene content from a glTF file to a textured,
depth-tested, animated frame while keeping Vulkan behind the renderer boundary.
It also makes presentation-dependent state safely replaceable.

> **Architecture as released:** [fireEngine 0.8 architecture]({% link _architecture/0.8.md %})
>
> **Source and downloads:** [GitHub release 0.8](https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.8)
>
> **Every post for this release:** [posts tagged 0.8](/tags/0-8/)
{: .prompt-info }

### 0.8 design and evidence

- [Growing fireEngine into an animated glTF renderer]({% post_url 2026-08-20-growing-fireengine-into-an-animated-gltf-renderer %}) — release plan
- [Giving fireEngine's imported transforms enough vocabulary]({% post_url 2026-08-22-giving-fireengine-imported-transforms-enough-vocabulary %})
- [Extending fireEngine's descriptions without introducing Vulkan]({% post_url 2026-08-23-extending-fireengines-descriptions-without-introducing-vulkan %})
- [Introducing format-neutral scene content to fireEngine]({% post_url 2026-08-27-introducing-format-neutral-scene-content-to-fireengine %})
- [Compiling and sampling fireEngine's first texture]({% post_url 2026-08-28-compiling-and-sampling-fireengines-first-texture %})
- [Adding a camera, depth, and culling to fireEngine]({% post_url 2026-08-29-adding-camera-depth-and-culling-to-fireengine %})
- [Animating fireEngine's transforms without rebuilding resources]({% post_url 2026-08-30-animating-fireengines-transforms-without-rebuilding-resources %})
- [Making fireEngine's presentation state replaceable]({% post_url 2026-08-31-making-fireengines-presentation-state-replaceable %})
- [Closing fireEngine 0.8 with focused ownership and executable scenarios]({% post_url 2026-09-02-closing-fireengine-08-with-focused-ownership-and-executable-scenarios %})

## fireEngine 0.7 — explicit engine structure

Version 0.7 turns the original Vulkan program into a layered engine with
device-free descriptions, explicit scene preparation, and a renderer that owns
the Vulkan boundary.

> **Architecture as released:** [fireEngine 0.7 architecture]({% link _architecture/0.7.md %})
>
> **Source and downloads:** [GitHub release 0.7](https://github.com/nnewson/fireEngine-tutorial/releases/tag/0.7)
>
> **Every post for this release:** [posts tagged 0.7](/tags/0-7/)
{: .prompt-info }

### 0.7 design and evidence

- [Refactoring fireEngine for what comes next]({% post_url 2026-08-08-refactoring-fireengine-for-what-comes-next %}) — release plan
- [Testing fireEngine without a GPU]({% post_url 2026-08-09-testing-fireengine-without-a-gpu %})
- [Giving fireEngine a small maths vocabulary]({% post_url 2026-08-10-giving-fireengine-a-small-maths-vocabulary %})
- [Describing fireEngine's render assets without Vulkan]({% post_url 2026-08-12-describing-fireengines-render-assets-without-vulkan %})
- [Building fireEngine's first scene graph]({% post_url 2026-08-14-building-fireengines-first-scene-graph %})
- [Preparing fireEngine's scene data explicitly]({% post_url 2026-08-16-preparing-fireengines-scene-data-explicitly %})
- [Turning fireEngine's renderer into the Vulkan facade]({% post_url 2026-08-18-turning-fireengines-renderer-into-the-vulkan-facade %})
