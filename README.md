# Substrate

An isometric pixel-art logic game. Start with a Switch, a Wire, a NOT gate and a Light, turn small circuits into chips, then build bigger chips out of those chips until you have an adder and a counter, the heart of a computer.

It has a goal ladder to climb, and it is also a sandbox: the board and the Chip Frames are unlimited, and you can build anything at any time.

## Play

Open `docs/index.html` in a browser. It is a single file with no build step and no dependencies.

To host it on GitHub Pages, go to **Settings → Pages**, choose the `main` branch and the `/docs` folder, then save.

## Parts

| Part | What it does |
|---|---|
| **Switch** | A power source. Click it with ✋ Toggle to turn it on or off. |
| **Wire** | Carries power. Touching wires share one signal and glow yellow when powered. |
| **NOT gate** | Flips the signal. It turns itself to fit your wiring: power comes in from the side that touches a source and goes out the opposite side. Press **R** to switch between Auto (**A**) and a fixed direction. |
| **Light** | Lights up when power reaches it. |
| **Input Pin / Output Pin** | The connection points of a chip you are building. Pins are numbered top to bottom. |
| **Chip Frame** | A box you drag out. Whatever is inside becomes one chip. |

## Making a chip

1. Pick **Chip Frame** and drag a rectangle.
2. Build your circuit inside it using Wires, NOT gates and other chips.
3. Add at least one **Input Pin** and one **Output Pin**. Click an Input Pin with ✋ Toggle to test it.
4. Pick **Make Chip**, click inside the frame, and type a name.

The chip appears in your bottom bar and can be placed like any other part.

A finished chip is a small block 2 cells tall. Inputs sit along the top edge and outputs along the bottom edge, with one empty cell between pins so wires don't touch. The shorter side is centered, so a chip with 2 inputs and 1 output has an input at each top corner and the output in the middle of the bottom. Wire into the top and out of the bottom. Its width is `2 × (pins on the busier side) − 1`.

Your circuit keeps running exactly as you built it inside the chip.

## Goals

Each goal is checked when you make a chip with the right number of inputs and outputs. Matching the behavior certifies the chip and moves you up an era.

| # | Chip | Inputs → Outputs | Era |
|---|---|---|---|
| 1 | NOR Gate | 2 → 1 | Spark |
| 2 | AND Gate | 2 → 1 | Gate |
| 3 | XOR Gate | 2 → 1 | Gate |
| 4 | Half Adder | 2 → 2 | Logic |
| 5 | Full Adder | 3 → 2 | Logic |
| 6 | Memory Latch | 2 → 1 | Memory |
| 7 | 4-bit Adder | 8 → 5 | Engine |
| 8 | Tally Core | 1 → 2 | Engine |

Certify all eight and the engine wakes. Keep building after that.

## Controls

| Action | Control |
|---|---|
| Place a part | Click |
| Paint wire | Click and drag with the Wire tool |
| Toggle a Switch or Input Pin | ✋ Toggle, then click it |
| NOT gate direction | **R** cycles Auto, →, ↓, ←, ↑ |
| Pan the board | **WASD**, arrow keys, or right-drag (or Shift-drag) |
| Erase | Erase tool; click an empty cell inside a frame to remove the frame |
| Step-by-step examples | **❓ Guide** button |

The Guide has examples that place a working circuit for you, including a NOR gate you can turn into your first chip.

## Saving

Your board, frames and chip library save automatically in your browser's local storage. Clearing site data resets the game.

## How it works

- Each chip is its own small grid, simulated inside the board, so chips can contain other chips.
- Wires settle instantly. NOT gates and chips update one tick at a time, which is what makes memory and counters possible.
- The board only stores cells that hold a part, which is why it has no edges.
