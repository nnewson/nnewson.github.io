Diagrams with alignment mistakes that reached publication before the checker
existed. Running the checker over this file should report three findings:
R1 on the first, R2 on the second, R3 (and R1) on the third.

Misaligned joins — the two `+` sit one column apart:

```text
Texture 0 -- linear + repeat --------+
                                        >-- ImageData 0
Texture 1 -- nearest + clamp-to-edge -+
```

Ragged description column — descriptions start at 31, 44 and 54:

```text
   fireEngineTutorialEngine   static library, all engine code
            │
            ├──> fireEngineTutorial        thin application, src/main.cpp
            │         │
            │         └──> smoke test:  --frames 1   one real presented frame
            │
            └──> fireEngineTutorialTests   Catch2, no window or device
```

Ragged box — the right edge drifts:

```text
  ┌──────────────────┐
  │  Renderer        │
  │  prepare()      │
  │  drawFrame()      │
  └──────────────────┘
```
