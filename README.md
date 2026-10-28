# Chipcraft

A voxel sandbox with redstone: levers, torches, dust, pistons and sticky pistons, and
**chips** — build a logic box out of blocks, package it into a reusable chip, then place
chips inside other chips.

The game is written in Python. It runs in the browser through
[Pyodide](https://pyodide.org) (CPython compiled to WebAssembly) and draws with
[three.js](https://threejs.org), so the whole thing is static files — no server.

**Play it:** https://12leocheung.github.io/chipcraft/

## Controls

| Input | Action |
| --- | --- |
| `WASD` / `Space` | Move / jump |
| Mouse | Look (click the page to capture the pointer) |
| Left click | Break a block, component or chip |
| Right click | Use a lever, attach a component, or place the held item |
| `1`-`9`, wheel | Select a hotbar slot |
| `E` | Inventory |
| `K` | Package the chip box you are looking at into a chip |
| `L` | Unpack a placed chip back into editable blocks |

## Layout

- `docs/` — the website (this is what GitHub Pages serves)
- `docs/README.md` — controls, piston behaviour and hosting notes
- `docs/game.py` — world, redstone simulation, chips, inventory, physics
- `docs/bridge.js` — three.js renderer and input, driven from Python
- `main.py` — the original desktop version of the game (Ursina / Panda3D)

## Run locally

```bash
cd docs
python -m http.server 8123
# open http://127.0.0.1:8123/
```
