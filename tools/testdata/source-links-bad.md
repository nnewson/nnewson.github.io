Source-link failures that reached publication before the checker existed.
Running the checker over this file should report two findings: S2 on the
wrong-file section and S1 on the unlinked one. The correct and the deliberately
illustrative sections must stay silent.

## Correctly linked

The snippet is quoted from the file the section links to.

```cpp
struct CompiledDraw
{
    vk::Buffer vertexBuffer;
    vk::Buffer indexBuffer;
    std::uint32_t indexCount;
    vk::Sampler sampler;
    vk::ImageView imageView;
    Color4 baseColor;
};
```

See [`compiled_resources.hpp`][source-compiled-header].

## Wrong file

The link names the type the section is about, while the snippet comes from the
implementation. This is the failure mode a presence check cannot see, because
a link is present.

```cpp
const vk::ImageMemoryBarrier2 toTransfer{
    .srcStageMask = vk::PipelineStageFlagBits2::eNone,
    .srcAccessMask = vk::AccessFlagBits2::eNone,
    .dstStageMask = vk::PipelineStageFlagBits2::eCopy,
    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
};
```

See [`compiled_resources.hpp`][source-compiled-header].

## No link at all

A source excerpt with nothing to click through to.

```cpp
void validateSceneContent(const SceneContent& content)
{
    validateAssets(content.assets);
    validateAnimationBindings(content.scene, content.animations);
}
```

<!-- source-link: ignore -->
## Deliberately illustrative

A simplified shape that never existed verbatim, so no file can contain it.

```cpp
class Renderer
{
    void prepare(...);
    void drawFrame(...);
};
```

## Not source, so no link is expected

Diagrams, commands, and captured output are excluded from the check.

```text
application ---> Renderer ---> Vulkan
```

```shell
ctest --preset default
```

[source-compiled-header]: <https://github.com/nnewson/fireEngine-tutorial/blob/0.8/include/fire_engine/render/detail/compiled_resources.hpp>
