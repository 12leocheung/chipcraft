# Chipcraft — browser build

The same game as `../main.py`, plus pistons: a voxel sandbox with levers, torches,
redstone dust, pistons and sticky pistons, chip boxes you package into reusable
chips, and chips nested inside chips.

The game code is Python. It runs in the browser through
[Pyodide](https://pyodide.org) (CPython compiled to WebAssembly) and draws through
[three.js](https://threejs.org), so the site is just static files.

> Ursina/Panda3D has no browser build, so this is a port rather than the desktop app
> running in a tab. `../main.py` is untouched and still runs locally as before.

## Files

| File | What it does |
| --- | --- |
| `index.html` | Page shell, HUD, inventory, chip dialog, Pyodide bootstrap |
| `game.py` | The game: world, redstone simulation, chips, inventory, player physics |
| `bridge.js` | three.js renderer, textures, input forwarding, DOM HUD |
| `style.css` | HUD, inventory and dialog styling |
| `assets/` | Block and item textures (copied from `../assets`) |

## Run it locally

Any static file server works — `file://` will not, because the page fetches `game.py`
and the ES modules:

```bash
cd docs
python -m http.server 8123
# then open http://127.0.0.1:8123/
```

The first visit downloads the Pyodide runtime (about 10 MB) from the jsDelivr CDN;
after that the browser caches it. three.js is also loaded from jsDelivr.

## Host it on GitHub Pages

Everything needed is in this folder, so Pages can serve it directly:

1. Commit the `docs/` folder and push to GitHub.
2. Repository → **Settings → Pages**.
3. **Source: Deploy from a branch**, **Branch: `main`**, **Folder: `/docs`**, Save.
4. The site appears at `https://<user>.github.io/<repo>/` after a minute or two.

No build step, no workflow file, no server code. To host it under a custom domain or
from a different folder, keep `index.html`, `game.py`, `bridge.js`, `style.css` and
`assets/` together — all paths are relative.

## Controls

| Input | Action |
| --- | --- |
| `WASD` / `Space` | Move / jump |
| Mouse | Look (click the page to capture the pointer) |
| Left click | Break a block, component or chip |
| Right click | Use a lever, attach a component, or place the held item |
| `1`-`9`, wheel | Select a hotbar slot (the item name shows above the hotbar) |
| `E` | Inventory (click a slot to pick up, click another to swap) |
| `K` | Package the chip box you are looking at into a chip |
| `L` | Unpack a placed chip back into editable blocks |

## Pistons

Right-click the ground, a wall or a ceiling while holding a piston. It faces **you**
when it goes down, the way Minecraft's do, so it shoves blocks away from you — power
it from behind with a lever, torch, dust line or chip output.

- It pushes up to **12 blocks** in a line, one cell along its facing. A 13th block, or
  any component, chip or water in the way, and the push fails and nothing moves.
- Remove the power and it retracts. A **sticky** piston drags the one block against its
  head back with it; a plain piston leaves the blocks where they were.
- A signal in **front** of the head never activates it (only behind, the sides, or the
  block it sits against). There is no quasi-connectivity, unlike Java Edition.
- A piston is a solid block: you can stand on it or on an extended head, and it blocks
  placement. Breaking a piston takes its head with it.
- Blocks pushed onto a torch, dust or lever break that component, as in Minecraft.

## Notes on the port

- Ground cells are real blocks, so mining one leaves a hole you can fall into
  (the desktop build only marks the cell as removed).
- Water spreads inside the platform bounds and is capped at 3000 cells, so a spilled
  bucket cannot take the frame rate down.
- Saving a chip with a name that already exists replaces that chip instead of adding
  a duplicate; leaving the name empty gives `Chip`, `Chip 2`, and so on.
- Chips evaluate once per redstone tick and nested results are memoised, so a chip
  three levels deep costs about five simulations per tick.
