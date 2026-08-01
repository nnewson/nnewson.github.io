---
icon: fas fa-info-circle
order: 5
---

After university, my first job was as a software engineer at
[Rare](https://www.rare.co.uk). I joined its R&D team and worked on what became
known as `REngine`: a shared 3D engine intended for several future GameCube
projects—though not *Perfect Dark Zero*, whose team developed its own
technology.

During that time, I began designing the 3D engine I would build without the
GameCube's technical constraints. The ideas included tessellated surfaces,
spline-based animation, soft-body skinning, and “correct” collision detection.

I've been exploring parts of that design ever since, through OpenGL experiments
and general-purpose CPU soft-body solvers. More recently, I began working with
Vulkan, got the foundations of an engine running, and started combining my
various projects into a single repository:
[fireEngine](https://github.com/nnewson/fireEngine).

While bringing those experiments together—with AI-assisted testing and some
fairly fierce reviews—I realised that I wasn't happy with the overall
architecture. I wanted to rebuild several areas around a clearer and more
structured design. For example, I would like the rendering subsystem to use a
render graph similar to the directed acyclic graph (DAG) used by Maya.

Rebuilding the engine from the ground up, while documenting the decisions
behind it, seemed useful both for me and for anyone interested in learning
about the techniques involved.

With that in mind, I created
[fireEngine-tutorial](https://github.com/nnewson/fireEngine-tutorial): a
step-by-step guide to building a 3D engine from scratch and restructuring
fireEngine around a more coherent architecture.

Each repository release will have a corresponding blog post explaining what
changed, how the code works, and why particular design decisions were made.
The repository will hold the step-by-step history of the engine, while this
site provides the companion narrative: the rendering techniques, experiments,
dead ends, trade-offs, and lessons that do not fit neatly into a changelog.

## Follow the project

- Read the [latest posts](/).
- Browse the
  [fireEngine tutorial source](https://github.com/nnewson/fireEngine-tutorial).
- Subscribe to the [Atom feed](/feed.xml).
