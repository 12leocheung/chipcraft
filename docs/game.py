"""Chipcraft -- browser build.

This is main.py's game (voxels, redstone, chips, nesting) running as Python inside the
browser through Pyodide. Pyodide cannot run ursina/Panda3D, so all drawing happens in
bridge.js on top of three.js; this module keeps the world state, the simulation, the
player physics and the inventory, and talks to the renderer through ``js.gameBridge``.
"""

import json
import math
import random
import time

import js
from pyodide.ffi import to_js

B = js.gameBridge

# ====================================================================
# --- WORLD GRID & REGISTRIES ---
# ====================================================================

PLATFORM = 60
REDSTONE_TICK_RATE = 0.1
WATER_INTERVAL = 0.5
WATER_LIMIT = 3000          # stop runaway flooding from eating the frame budget

blocks = {}                 # (x, y, z) -> block type
components = {}             # (x, y, z) -> RedstoneComponent
placed_chips = {}           # (x, y, z) -> Chip (every cell the chip covers)

DIRS = {
    'up': (0, 1, 0), 'down': (0, -1, 0),
    'north': (0, 0, -1), 'south': (0, 0, 1),
    'east': (1, 0, 0), 'west': (-1, 0, 0),
}
OUTSIDE_DIR = {
    'north': (0, 0, 1), 'south': (0, 0, -1),
    'east': (1, 0, 0), 'west': (-1, 0, 0),
}
OPPOSITE_FACE = {'up': 'down', 'down': 'up', 'north': 'south',
                 'south': 'north', 'east': 'west', 'west': 'east'}
COMPONENT_TYPES = ('lever', 'redstone_torch', 'redstone_dust')


def addpos(pos, d):
    return (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])


def _cell(v):
    """The grid cell a world coordinate falls in (cells are centred on integers)."""
    return int(math.floor(v + 0.5))


def grid_pos(p):
    return (int(round(p[0])), int(round(p[1])), int(round(p[2])))


def dir_from_vec(v):
    x, y, z = v
    if y > 0: return 'up'
    if y < 0: return 'down'
    if x > 0: return 'east'
    if x < 0: return 'west'
    if z > 0: return 'south'
    return 'north'


def is_solid(x, y, z):
    t = blocks.get((x, y, z))
    return t is not None and t != 'water_block'


def block_type_at(pos):
    return blocks.get(pos)


def is_opaque_support(pos):
    return block_type_at(pos) not in (None, 'water_block', 'glass')


def occupied(pos):
    return pos in blocks or pos in placed_chips


# ====================================================================
# --- GROUND PLATFORM ---
# ====================================================================

def build_ground():
    """Every ground cell is a real block, so mining one opens a hole you can fall in."""
    entries = []
    for x in range(PLATFORM):
        for z in range(PLATFORM):
            blocks[(x, 1, z)] = 'stone'
            blocks[(x, 2, z)] = 'grass'
            entries.append(['stone', x, 1, z])
            entries.append(['grass', x, 2, z])
    B.setBlocksJson(json.dumps(entries))


# ====================================================================
# --- NOTIFICATIONS ---
# ====================================================================

def notify(msg):
    B.notify(str(msg))


# ====================================================================
# --- REDSTONE COMPONENTS ---
# ====================================================================

class RedstoneComponent:
    kind = ''

    def __init__(self, pos, face):
        self.pos = (int(pos[0]), int(pos[1]), int(pos[2]))
        self.face = face
        self.attached_to = addpos(self.pos, DIRS[face])
        self.power_level = 0
        components[self.pos] = self
        B.addComponent(self.kind, self.pos[0], self.pos[1], self.pos[2], face)

    def remove(self):
        if components.get(self.pos) is self:
            del components[self.pos]
        B.removeComponent(self.pos[0], self.pos[1], self.pos[2])


class Lever(RedstoneComponent):
    kind = 'lever'

    def __init__(self, pos, face):
        self.powered = False
        super().__init__(pos, face)
        self._push()

    def _push(self):
        B.setLeverOn(self.pos[0], self.pos[1], self.pos[2], 1 if self.powered else 0)

    def toggle(self):
        self.powered = not self.powered
        self._push()


class RedstoneTorch(RedstoneComponent):
    kind = 'redstone_torch'

    def __init__(self, pos, face):
        self.lit = True
        self.burned_out = False
        self.pending_state = None
        self.pending_at = 0.0
        self.flicker_times = []
        super().__init__(pos, face)
        self._push()

    def _push(self):
        B.setTorchLit(self.pos[0], self.pos[1], self.pos[2], 1 if self.lit else 0)

    def tick(self, powered):
        now = time.time()
        self.flicker_times = [t for t in self.flicker_times if now - t < 3.0]
        desired = self.attached_to not in powered

        if self.burned_out:
            self.lit = False
            if len(self.flicker_times) < 8:
                self.burned_out = False
                self.lit = desired
                self._push()
            return

        if self.pending_state is not None:
            if desired == self.lit:
                self.pending_state = None
            elif now >= self.pending_at:
                self.lit = self.pending_state
                self.pending_state = None
                self.flicker_times.append(now)
                self._push()
                if len(self.flicker_times) > 8:
                    self.burned_out = True
                    self.lit = False
                    self._push()
        elif self.attached_to in powered and self.lit and self.pending_state is None:
            self.pending_state = False
            self.pending_at = now
        elif self.attached_to not in powered and not self.lit and self.pending_state is None:
            self.pending_state = True
            self.pending_at = now


class RedstoneDust(RedstoneComponent):
    kind = 'redstone_dust'

    def __init__(self, pos, face):
        self.connected_dirs = []
        self._last_push = None
        super().__init__(pos, face)
        self.refresh_connections()
        self.update_appearance()

    def _compute_connection_dirs(self):
        dirs = []
        up_cell_solid = addpos(self.pos, (0, 1, 0)) in blocks
        for name in ('north', 'south', 'east', 'west'):
            n = addpos(self.pos, DIRS[name])
            nc = components.get(n)
            bt = block_type_at(n)
            if nc is not None and nc.kind in ('redstone_dust', 'redstone_torch', 'lever'):
                dirs.append(name)
            elif bt is not None and bt != 'water_block':
                dirs.append(name)
            elif nc is None and bt is None:
                low = addpos(n, DIRS['down'])
                lc = components.get(low)
                if lc is not None and lc.kind == 'redstone_dust' and addpos(low, (0, 1, 0)) not in blocks:
                    dirs.append(name)
                elif not up_cell_solid:
                    hi = addpos(n, DIRS['up'])
                    hc = components.get(hi)
                    if hc is not None and hc.kind == 'redstone_dust':
                        dirs.append(name)
        return dirs

    def refresh_connections(self):
        self.connected_dirs = self._compute_connection_dirs()
        self.update_appearance()

    def update_appearance(self, mask=None):
        if mask is None:
            mask = 0
            for i, name in enumerate(('north', 'south', 'east', 'west')):
                if name in self.connected_dirs:
                    mask |= 1 << i
        state = (self.power_level, mask)
        if state == self._last_push:
            return
        self._last_push = state
        B.setDustLevel(self.pos[0], self.pos[1], self.pos[2], self.power_level, mask)


def break_redstone_component(comp):
    comp.remove()


def try_place_component(block_type, place_pos, face):
    if occupied(place_pos) or place_pos in components:
        return False
    support = addpos(place_pos, DIRS[face])
    support_bt = block_type_at(support)
    if support_bt in (None, 'water_block'):
        return False
    if block_type == 'redstone_dust':
        if face != 'down':
            return False
        RedstoneDust(place_pos, 'down')
    elif block_type == 'redstone_torch':
        if support_bt == 'glass' and face != 'down':
            return False
        RedstoneTorch(place_pos, face)
    elif block_type == 'lever':
        if support_bt == 'glass':
            return False
        Lever(place_pos, face)
    else:
        return False
    redstone_tick()
    return True


# ====================================================================
# --- CHIP SIMULATION ENGINE ---
# ====================================================================

def simulate_circuit_logic(chip_data, active_inputs, cache=None):
    """Evaluate a chip's internal wiring.

    ``cache`` memoises nested chip results (keyed by chip and the inputs that reach
    it) for a single evaluation, so chips nested inside chips inside chips are
    simulated once each instead of once per pass per nesting level.
    """
    if cache is None:
        cache = {}
    internal_comps = chip_data.get('contained_components', [])
    nested_chips = chip_data.get('contained_chips', [])
    solid_cells = {tuple(b['pos']) for b in chip_data.get('contained_blocks', [])}
    solid_cells.update(tuple(f['pos']) for f in chip_data.get('frame_blocks', []))
    port_cells = {tuple(p['orig_rel']) for p in chip_data.get('inputs', []) + chip_data.get('outputs', [])}

    torch_states = {idx: True for idx, comp in enumerate(internal_comps) if comp['type'] == 'redstone_torch'}
    cell_power = {}
    powered_blocks = set()

    for _pass in range(10):
        torch_state_before = frozenset(idx for idx, lit in torch_states.items() if lit)
        cell_power = {}
        powered_blocks = set()

        for p in chip_data.get('inputs', []):
            if p['id'] in active_inputs:
                cell_power[p['orig_rel']] = 15
                powered_blocks.add(p['orig_rel'])

        for idx, comp in enumerate(internal_comps):
            if comp['type'] == 'redstone_torch' and torch_states[idx]:
                t_pos = tuple(comp['pos'])
                cell_power[t_pos] = 15
                powered_blocks.add(addpos(t_pos, (0, 1, 0)))
            elif comp['type'] == 'lever' and comp.get('powered', False):
                l_pos = tuple(comp['pos'])
                cell_power[l_pos] = 15
                powered_blocks.add(tuple(comp['attached_to']))

        for sub in nested_chips:
            sub_pos = tuple(sub['pos'])
            sub_data = sub['chip_data']
            sub_active_inputs = set()
            for inp in sub_data.get('inputs', []):
                off, side = inp['placed_offset'], inp['side']
                sub_port_cell = (sub_pos[0] + off[0], sub_pos[1], sub_pos[2] + off[1])
                adj_cell = addpos(sub_port_cell, OUTSIDE_DIR[side])
                if cell_power.get(adj_cell, 0) > 0 or adj_cell in powered_blocks:
                    sub_active_inputs.add(inp['id'])

            cache_key = (id(sub_data), frozenset(sub_active_inputs))
            sub_outputs = cache.get(cache_key)
            if sub_outputs is None:
                sub_outputs = simulate_circuit_logic(sub_data, sub_active_inputs, cache)
                cache[cache_key] = sub_outputs
            for out in sub_data.get('outputs', []):
                if sub_outputs.get(out['id'], False):
                    off, side = out['placed_offset'], out['side']
                    sub_port_cell = (sub_pos[0] + off[0], sub_pos[1], sub_pos[2] + off[1])
                    adj_cell = addpos(sub_port_cell, OUTSIDE_DIR[side])
                    cell_power[adj_cell] = 15
                    powered_blocks.add(adj_cell)

        dust_comps = [comp for comp in internal_comps if comp['type'] == 'redstone_dust']
        for comp in dust_comps:
            d_pos = tuple(comp['pos'])
            if d_pos not in cell_power:
                cell_power[d_pos] = 0

        for _ in range(16):
            changed = False
            for comp in dust_comps:
                d_pos = tuple(comp['pos'])
                cur = cell_power.get(d_pos, 0)
                best = cur
                for d in DIRS.values():
                    p_val = cell_power.get(addpos(d_pos, d), 0)
                    if p_val - 1 > best:
                        best = p_val - 1
                if best != cur:
                    cell_power[d_pos] = best
                    changed = True
            if not changed:
                break

        for comp in dust_comps:
            d_pos = tuple(comp['pos'])
            if cell_power.get(d_pos, 0) > 0:
                powered_blocks.add(d_pos)
                powered_blocks.add(addpos(d_pos, (0, -1, 0)))

        # A powered cell lights up the port cells next to it (the way a chip in the
        # world reads the components sitting around its ports) and a powered dust
        # also lights the solid cells it touches (the way dust powers blocks outside).
        dust_cells = {tuple(comp['pos']) for comp in dust_comps}
        for cell, level in cell_power.items():
            if level <= 0:
                continue
            for d in DIRS.values():
                neighbour = addpos(cell, d)
                if neighbour in solid_cells and (neighbour in port_cells or cell in dust_cells):
                    powered_blocks.add(neighbour)

        for idx, comp in enumerate(internal_comps):
            if comp['type'] == 'redstone_torch':
                att = tuple(comp['attached_to'])
                torch_states[idx] = (att not in powered_blocks and cell_power.get(att, 0) == 0)

        if frozenset(idx for idx, lit in torch_states.items() if lit) == torch_state_before:
            break       # torch states settled, so another pass would give the same result

    return {p['id']: (cell_power.get(p['orig_rel'], 0) > 0 or p['orig_rel'] in powered_blocks)
            for p in chip_data.get('outputs', [])}


class Chip:
    def __init__(self, pos, chip_data):
        self.pos = grid_pos(pos)
        self.chip_data = chip_data
        self.width = chip_data['width']
        self.length = chip_data['length']
        self.output_states = {}
        self.inputs = chip_data.get('inputs', [])
        self.outputs = chip_data.get('outputs', [])
        self.key = '%d,%d,%d,%d,%d' % (self.pos[0], self.pos[1], self.pos[2], self.width, self.length)
        for dx in range(self.width):
            for dz in range(self.length):
                placed_chips[(self.pos[0] + dx, self.pos[1], self.pos[2] + dz)] = self
        ports = [{'side': p['side'], 'off': list(p['placed_offset']), 'out': False} for p in self.inputs]
        ports += [{'side': p['side'], 'off': list(p['placed_offset']), 'out': True} for p in self.outputs]
        B.addChip(self.key, self.pos[0], self.pos[1], self.pos[2], self.width, self.length,
                  json.dumps(ports))
        self.evaluate_circuit({})

    def evaluate_circuit(self, sim_cache=None):
        if sim_cache is None:
            sim_cache = {}
        active_inputs = set()
        for p in self.inputs:
            off, side = p['placed_offset'], p['side']
            world_p = (self.pos[0] + off[0], self.pos[1], self.pos[2] + off[1])
            adj = addpos(world_p, OUTSIDE_DIR[side])

            c = components.get(adj)
            if c and getattr(c, 'power_level', 0) > 0:
                active_inputs.add(p['id'])
            elif c and getattr(c, 'powered', False):
                active_inputs.add(p['id'])
            elif c and getattr(c, 'lit', False):
                active_inputs.add(p['id'])

        self.output_states = simulate_circuit_logic(self.chip_data, active_inputs, sim_cache)

        states = [p['id'] in active_inputs for p in self.inputs]
        states += [bool(self.output_states.get(p['id'], False)) for p in self.outputs]
        B.setChipPorts(self.key, json.dumps(states))

    def destroy(self):
        for dx in range(self.width):
            for dz in range(self.length):
                pos = (self.pos[0] + dx, self.pos[1], self.pos[2] + dz)
                if placed_chips.get(pos) is self:
                    del placed_chips[pos]
        B.removeChip(self.key)


# ====================================================================
# --- CHIP DETECT, PACKAGE & UNPACK ---
# ====================================================================

def select_frame_blocks(candidates, sp):
    """Pick the box the player is looking at.

    The candidate frame blocks are split into face-connected groups and the
    group closest to the clicked position is used, so a second box built
    nearby is never merged into the chip being saved.
    """
    groups, unvisited = [], set(candidates)
    while unvisited:
        seed = unvisited.pop()
        group, stack = {seed: candidates[seed]}, [seed]
        while stack:
            pos = stack.pop()
            for d in DIRS.values():
                neighbour = addpos(pos, d)
                if neighbour in unvisited:
                    unvisited.discard(neighbour)
                    group[neighbour] = candidates[neighbour]
                    stack.append(neighbour)
        groups.append(group)

    def distance(group):
        return min(max(abs(p[0] - sp[0]), abs(p[1] - sp[1]), abs(p[2] - sp[2])) for p in group)

    return min(groups, key=distance)


def detect_and_package_chip(start_pos):
    sp = grid_pos(start_pos)
    candidates = {}
    # only search cells that actually exist, instead of a 51x51x51 sweep
    for pos, btype in blocks.items():
        if btype in ('surrounder', 'chip_input', 'chip_output'):
            if (abs(pos[0] - sp[0]) <= 25 and abs(pos[1] - sp[1]) <= 25
                    and abs(pos[2] - sp[2]) <= 25):
                candidates[pos] = btype

    if not candidates:
        return None, "No surrounder blocks found!"
    frame_blocks = select_frame_blocks(candidates, sp)

    xs, ys, zs = [p[0] for p in frame_blocks], [p[1] for p in frame_blocks], [p[2] for p in frame_blocks]
    min_x, max_x, min_y, max_y, min_z, max_z = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

    if (max_x - min_x) < 2 or (max_z - min_z) < 2:
        return None, "Surrounder box is too small!"

    ports_by_side = {'north': [], 'south': [], 'east': [], 'west': []}
    for pos, btype in frame_blocks.items():
        if btype in ('chip_input', 'chip_output'):
            x, y, z = pos
            if z == max_z:
                ports_by_side['north'].append({'pos': pos, 'type': btype, 'rel_idx': x - min_x})
            elif z == min_z:
                ports_by_side['south'].append({'pos': pos, 'type': btype, 'rel_idx': x - min_x})
            elif x == max_x:
                ports_by_side['east'].append({'pos': pos, 'type': btype, 'rel_idx': z - min_z})
            elif x == min_x:
                ports_by_side['west'].append({'pos': pos, 'type': btype, 'rel_idx': z - min_z})

    for side in ports_by_side:
        ports_by_side[side].sort(key=lambda item: item['rel_idx'])

    n_north, n_south = len(ports_by_side['north']), len(ports_by_side['south'])
    n_east, n_west = len(ports_by_side['east']), len(ports_by_side['west'])

    chip_width = max((2 * n_north - 1) if n_north > 0 else 1, (2 * n_south - 1) if n_south > 0 else 1, 1)
    chip_length = max((2 * n_east - 1) if n_east > 0 else 1, (2 * n_west - 1) if n_west > 0 else 1, 1)

    inputs, outputs, port_id = [], [], 0
    for side in ('north', 'south', 'east', 'west'):
        p_list = ports_by_side[side]
        n_ports = len(p_list)
        if n_ports == 0:
            continue

        side_len = chip_width if side in ('north', 'south') else chip_length
        start_off = (side_len - (2 * n_ports - 1)) // 2

        for idx, port in enumerate(p_list):
            port_id += 1
            if side in ('north', 'south'):
                placed_off = (start_off + idx * 2, 0 if side == 'south' else chip_length - 1)
            else:
                placed_off = (0 if side == 'west' else chip_width - 1, start_off + idx * 2)

            p_data = {
                'id': port_id, 'side': side,
                'orig_rel': (port['pos'][0] - min_x, port['pos'][1] - min_y, port['pos'][2] - min_z),
                'placed_offset': placed_off
            }
            if port['type'] == 'chip_input':
                inputs.append(p_data)
            else:
                outputs.append(p_data)

    contained_blocks, contained_components, contained_chips, visited_chips = [], [], [], set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                pos = (x, y, z)
                rel_pos = (x - min_x, y - min_y, z - min_z)

                b = blocks.get(pos)
                if b and b not in ('surrounder', 'chip_input', 'chip_output'):
                    contained_blocks.append({'pos': rel_pos, 'type': b})

                c = components.get(pos)
                if c:
                    att_rel = (c.attached_to[0] - min_x, c.attached_to[1] - min_y, c.attached_to[2] - min_z)
                    contained_components.append({
                        'pos': rel_pos, 'type': c.kind, 'face': c.face, 'attached_to': att_rel,
                        'powered': getattr(c, 'powered', False),
                    })

                pc = placed_chips.get(pos)
                if pc and pc not in visited_chips:
                    visited_chips.add(pc)
                    pc_rel = (pc.pos[0] - min_x, pc.pos[1] - min_y, pc.pos[2] - min_z)
                    contained_chips.append({'pos': pc_rel, 'chip_data': pc.chip_data})

    chip_data = {
        'name': 'Chip', 'width': chip_width, 'length': chip_length,
        'box_bounds': (min_x, max_x, min_y, max_y, min_z, max_z),
        'inputs': inputs, 'outputs': outputs,
        'contained_blocks': contained_blocks, 'contained_components': contained_components,
        'contained_chips': contained_chips,
        'frame_blocks': [{'pos': (p[0] - min_x, p[1] - min_y, p[2] - min_z), 'type': t}
                         for p, t in frame_blocks.items()]
    }
    return chip_data, None


def consume_box(chip_data):
    bounds = chip_data['box_bounds']
    doomed_chips = set()
    for x in range(bounds[0], bounds[1] + 1):
        for y in range(bounds[2], bounds[3] + 1):
            for z in range(bounds[4], bounds[5] + 1):
                pos = (x, y, z)
                if pos in components:
                    break_redstone_component(components[pos])
                if pos in blocks:
                    remove_block(pos)
                if pos in placed_chips:
                    doomed_chips.add(placed_chips[pos])
    for chip in doomed_chips:
        chip.destroy()


def unpack_chip_for_editing(chip):
    pos = chip.pos
    data = chip.chip_data
    chip.destroy()

    for item in data.get('frame_blocks', []):
        rp = item['pos']
        place_block((pos[0] + rp[0], pos[1] + rp[1], pos[2] + rp[2]), item['type'])

    for item in data.get('contained_blocks', []):
        rp = item['pos']
        place_block((pos[0] + rp[0], pos[1] + rp[1], pos[2] + rp[2]), item['type'])

    for item in data.get('contained_components', []):
        rp = item['pos']
        target = (pos[0] + rp[0], pos[1] + rp[1], pos[2] + rp[2])
        try_place_component(item['type'], target, item['face'])
        if item['type'] == 'lever' and item.get('powered'):
            comp = components.get(target)
            if comp is not None:
                comp.toggle()

    for item in data.get('contained_chips', []):
        rp = item['pos']
        Chip((pos[0] + rp[0], pos[1] + rp[1], pos[2] + rp[2]), item['chip_data'])

    redstone_tick()
    notify("Unpacked '%s' for editing" % data['name'])


# ====================================================================
# --- BLOCK PLACE / REMOVE ---
# ====================================================================

def place_block(pos, block_type):
    pos = grid_pos(pos)
    if pos in blocks or pos in placed_chips:
        return False
    blocks[pos] = block_type
    B.setBlock(block_type, pos[0], pos[1], pos[2])
    return True


def remove_block(pos):
    entry = blocks.pop(pos, None)
    if entry is None:
        return
    B.removeBlock(pos[0], pos[1], pos[2])
    x, y, z = pos
    for neighbour in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                      (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
        comp = components.get(neighbour)
        if comp is not None and comp.attached_to == pos:
            break_redstone_component(comp)
    if entry == 'water_block':
        water_cells.discard(pos)
    redstone_tick()


# ====================================================================
# --- WATER PHYSICS ---
# ====================================================================

water_cells = set()
water_timer = 0.0


def update_water_physics():
    if len(water_cells) > WATER_LIMIT:
        return
    blocks_to_add = []
    for pos in list(water_cells):
        x, y, z = pos
        down = (x, y - 1, z)
        if not occupied(down):
            blocks_to_add.append(down)
        elif random.random() < 0.25:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                side = (x + dx, y, z + dz)
                if not occupied(side):
                    blocks_to_add.append(side)

    for pos in blocks_to_add:
        x, y, z = pos
        if not (0 <= x < PLATFORM and 0 <= z < PLATFORM and y >= 1):
            continue                    # spills off the platform edge and is lost
        if occupied(pos):
            continue
        comp = components.get(pos)
        if comp is not None:
            break_redstone_component(comp)
        place_block(pos, 'water_block')
        water_cells.add(pos)


# ====================================================================
# --- INVENTORY ---
# ====================================================================

INV_SLOTS = 27
items = {i: {'type': None, 'count': 0, 'chip_data': None} for i in range(INV_SLOTS)}
selected_slot = 0
held_slot = None
inv_open = False


def init_inventory():
    starting = ['surrounder', 'chip_input', 'chip_output', 'lever', 'redstone_torch',
                'redstone_dust', 'stone', 'oak_plank', 'glass', 'grass', 'dirt', 'brick',
                'sand', 'water_block', 'oak_log']
    for i, block_type in enumerate(starting):
        items[i] = {'type': block_type, 'count': 64, 'chip_data': None}


def item_name(slot):
    item = items[slot]
    if not item['type'] or item['count'] <= 0:
        return ''
    if item['type'] == 'chip' and item.get('chip_data'):
        return item['chip_data'].get('name', 'Chip')
    return item['type'].replace('_', ' ').title()


def find_chip_slot(name):
    for i in range(INV_SLOTS):
        item = items[i]
        if item['type'] == 'chip' and item.get('chip_data') and item['chip_data'].get('name') == name:
            return i
    return None


def unique_chip_name(base='Chip'):
    taken = {items[i]['chip_data'].get('name') for i in range(INV_SLOTS)
             if items[i]['type'] == 'chip' and items[i].get('chip_data')}
    if base not in taken:
        return base
    index = 2
    while '%s %d' % (base, index) in taken:
        index += 1
    return '%s %d' % (base, index)


def add_item(block_type, count=1, chip_data=None):
    if block_type != 'chip':
        for i in range(INV_SLOTS):
            if items[i]['type'] == block_type and items[i]['count'] < 64:
                space = 64 - items[i]['count']
                add_count = min(count, space)
                items[i]['count'] += add_count
                count -= add_count
                if count <= 0:
                    render_ui()
                    return True
    if count > 0:
        for i in range(INV_SLOTS):
            if items[i]['type'] is None:
                items[i] = {'type': block_type, 'count': count, 'chip_data': chip_data}
                render_ui()
                return True
    return False


def store_chip(chip_data):
    """Store a chip, replacing a chip that already carries the same name."""
    slot = find_chip_slot(chip_data.get('name'))
    if slot is not None:
        items[slot] = {'type': 'chip', 'count': 1, 'chip_data': chip_data}
        render_ui()
        return 'replaced'
    return 'added' if add_item('chip', 1, chip_data=chip_data) else 'full'


def get_selected_block():
    slot = items[selected_slot]
    return slot['type'] if slot['type'] and slot['count'] > 0 else None


def items_json():
    out = []
    for i in range(INV_SLOTS):
        item = items[i]
        if item['type'] and item['count'] > 0:
            out.append({'type': item['type'], 'count': item['count'], 'name': item_name(i)})
        else:
            out.append({'type': None, 'count': 0, 'name': ''})
    return json.dumps(out)


def render_ui():
    data = items_json()
    B.renderHotbar(data, selected_slot)
    B.renderInventory(data, selected_slot, -1 if held_slot is None else held_slot, 1 if inv_open else 0)
    B.setHeld(get_selected_block() or '')


# ====================================================================
# --- PLAYER ---
# ====================================================================

EYE_HEIGHT = 1.6
HALF_WIDTH = 0.3
FEET_SKIN = 0.002
PLAYER_SPEED = 6.0
GRAVITY = 24.0
JUMP_SPEED = 8.4

px, py, pz = PLATFORM / 2.0, 4.2, PLATFORM / 2.0
vy = 0.0
yaw = 0.0
pitch = 0.0
keys = set()
on_ground = False


def camera_dir():
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (-sy * cp, sp, -cy * cp)


def player_collides(x, y, z):
    # FEET_SKIN keeps the surface the player stands on from counting as a collision:
    # 4.1 - 1.6 is 2.4999999996 in floating point, which would round into the ground
    # block and block every horizontal move.
    feet, head = y - EYE_HEIGHT + FEET_SKIN, y + 0.15
    x0, x1 = _cell(x - HALF_WIDTH), _cell(x + HALF_WIDTH)
    y0, y1 = _cell(feet), _cell(head)
    z0, z1 = _cell(z - HALF_WIDTH), _cell(z + HALF_WIDTH)
    for bx in range(x0, x1 + 1):
        for by in range(y0, y1 + 1):
            for bz in range(z0, z1 + 1):
                if is_solid(bx, by, bz):
                    return True
    return False


def support_height(px_, pz_, eye_y):
    """Top of the highest solid cell under the player's footprint, at or below the feet."""
    best = None
    for bx in range(_cell(px_ - HALF_WIDTH), _cell(px_ + HALF_WIDTH) + 1):
        for bz in range(_cell(pz_ - HALF_WIDTH), _cell(pz_ + HALF_WIDTH) + 1):
            for by in range(_cell(eye_y - EYE_HEIGHT), _cell(eye_y - EYE_HEIGHT) - 5, -1):
                if is_solid(bx, by, bz):
                    top = by + 0.5
                    if best is None or top > best:
                        best = top
                    break
    return best


def respawn():
    global px, py, pz, vy
    px, py, pz = PLATFORM / 2.0, 4.2, PLATFORM / 2.0
    vy = 0.0


def update_player(dt):
    global px, py, pz, vy, on_ground

    speed = PLAYER_SPEED
    dx = dz = 0.0
    cy, sy = math.cos(yaw), math.sin(yaw)
    if 'w' in keys:
        dx -= sy
        dz -= cy
    if 's' in keys:
        dx += sy
        dz += cy
    if 'a' in keys:
        dx -= cy
        dz += sy
    if 'd' in keys:
        dx += cy
        dz -= sy
    length = math.hypot(dx, dz)
    if length > 0:
        dx = dx / length * speed * dt
        dz = dz / length * speed * dt

    # move one axis at a time so sliding along a wall works
    if not player_collides(px + dx, py, pz):
        px += dx
    if not player_collides(px, py, pz + dz):
        pz += dz
    px = min(max(px, 1.0), PLATFORM - 2.0)
    pz = min(max(pz, 1.0), PLATFORM - 2.0)

    vy -= GRAVITY * dt
    if 'space' in keys and on_ground:
        vy = JUMP_SPEED
        on_ground = False

    next_y = py + vy * dt
    if player_collides(px, next_y, pz):
        if vy > 0:
            next_y = py                 # bumped a ceiling
            on_ground = False
        else:
            # land exactly on top of the block below, so the camera never sinks in
            top = support_height(px, pz, py)
            if top is not None:
                next_y = top + EYE_HEIGHT
            on_ground = True
        vy = 0.0
    else:
        on_ground = False
    py = next_y

    if py < -5:
        respawn()
        notify('Teleported back to safety!')


# ====================================================================
# --- VOXEL RAYCAST (Amanatides & Woo) ---
# ====================================================================

def raycast(max_dist=6.0):
    ox, oy, oz = px, py, pz
    dx, dy, dz = camera_dir()
    cx, cy, cz = _cell(ox), _cell(oy), _cell(oz)

    step_x = 1 if dx > 0 else -1
    step_y = 1 if dy > 0 else -1
    step_z = 1 if dz > 0 else -1
    inf = float('inf')
    t_delta_x = abs(1.0 / dx) if dx else inf
    t_delta_y = abs(1.0 / dy) if dy else inf
    t_delta_z = abs(1.0 / dz) if dz else inf

    # distance to the next cell boundary in the direction of travel
    if dx > 0:
        t_max_x = (cx + 0.5 - ox) / dx
    elif dx < 0:
        t_max_x = (cx - 0.5 - ox) / dx
    else:
        t_max_x = inf
    if dy > 0:
        t_max_y = (cy + 0.5 - oy) / dy
    elif dy < 0:
        t_max_y = (cy - 0.5 - oy) / dy
    else:
        t_max_y = inf
    if dz > 0:
        t_max_z = (cz + 0.5 - oz) / dz
    elif dz < 0:
        t_max_z = (cz - 0.5 - oz) / dz
    else:
        t_max_z = inf

    t = 0.0
    normal = (0, 0, 0)
    while True:
        if (cx, cy, cz) in blocks or (cx, cy, cz) in placed_chips or (cx, cy, cz) in components:
            return (cx, cy, cz), normal
        if t_max_x < t_max_y and t_max_x < t_max_z:
            cx += step_x
            t = t_max_x
            t_max_x += t_delta_x
            normal = (-step_x, 0, 0)
        elif t_max_y <= t_max_z:
            cy += step_y
            t = t_max_y
            t_max_y += t_delta_y
            normal = (0, -step_y, 0)
        else:
            cz += step_z
            t = t_max_z
            t_max_z += t_delta_z
            normal = (0, 0, -step_z)
        if t > max_dist:
            return None, None


# ====================================================================
# --- INTERACTION ---
# ====================================================================

def break_target():
    cell, normal = raycast(6.0)
    if cell is None:
        return
    chip = placed_chips.get(cell)
    if chip is not None:
        chip.destroy()
        redstone_tick()
        return
    comp = components.get(cell)
    if comp is not None:
        break_redstone_component(comp)
        redstone_tick()
        return
    if cell in blocks:
        remove_block(cell)


def use_or_place():
    """Right click: toggle/attach first, and only place when nothing was used."""
    cell, normal = raycast(6.0)
    held = get_selected_block()

    if cell is not None and cell in components:
        comp = components[cell]
        if isinstance(comp, Lever):
            comp.toggle()
            redstone_tick()
            return

    if held in COMPONENT_TYPES:
        if cell is None or normal is None:
            return
        face = OPPOSITE_FACE[dir_from_vec(normal)]
        place_pos = addpos(cell, normal)
        try_place_component(held, place_pos, face)
        return

    if not held or cell is None or normal is None:
        return
    place_pos = addpos(cell, normal)

    if occupied(place_pos) or place_pos in components:
        return
    if held == 'chip':
        chip_data = items[selected_slot].get('chip_data')
        if chip_data:
            Chip(place_pos, chip_data)
            redstone_tick()
        return
    place_block(place_pos, held)
    if held == 'water_block':
        water_cells.add(place_pos)
    redstone_tick()


chip_dialog_data = None


def open_chip_dialog():
    global chip_dialog_data
    cell, normal = raycast(6.0)
    if cell is None:
        notify('Aim at a chip box first')
        return
    data, err = detect_and_package_chip(cell)
    if err or data is None:
        notify(err or 'Nothing to save')
        return
    chip_dialog_data = data
    B.openChipDialog(data['width'], data['length'])


def save_chip(name):
    global chip_dialog_data
    data = chip_dialog_data
    chip_dialog_data = None
    if data is None:
        return
    name = (name or '').strip() or unique_chip_name('Chip')
    data['name'] = name
    consume_box(data)
    result = store_chip(data)
    if result == 'replaced':
        notify("Replaced chip '%s'" % name)
    elif result == 'added':
        notify("Saved '%s' into Inventory!" % name)
    else:
        notify('Inventory full!')
    B.closeChipDialog()


def cancel_chip():
    global chip_dialog_data
    chip_dialog_data = None
    B.closeChipDialog()


# ====================================================================
# --- UI CALLBACKS (called from the page) ---
# ====================================================================

def select_slot(slot):
    global selected_slot
    slot = int(slot)
    if 0 <= slot < INV_SLOTS:
        selected_slot = slot
        render_ui()
        if not inv_open:
            B.showTag(item_name(slot), False)


def slot_click(slot):
    global held_slot
    slot = int(slot)
    if held_slot is None:
        if items[slot]['type'] is not None:
            held_slot = slot
    else:
        if held_slot != slot:
            items[held_slot], items[slot] = items[slot], items[held_slot]
        held_slot = None
    render_ui()


def slot_hover(slot):
    B.showTag(item_name(int(slot)), True)


def slot_unhover():
    B.showTag('', True)


def toggle_inventory():
    global inv_open, held_slot
    inv_open = not inv_open
    held_slot = None
    B.showTag('', True)
    render_ui()
    if inv_open:
        B.unlockPointer()


def scroll(direction):
    select_slot((selected_slot - int(direction)) % INV_SLOTS)


def key_press(key):
    if key == 'escape':
        if chip_dialog_data is not None:
            cancel_chip()
        elif inv_open:
            toggle_inventory()
        return
    if key == 'e':                    # toggles, whether or not the inventory is open
        if chip_dialog_data is None:
            toggle_inventory()
        return
    if inv_open:
        return
    if key == 'k':
        open_chip_dialog()
    elif key == 'l':
        cell, normal = raycast(6.0)
        chip = placed_chips.get(cell) if cell is not None else None
        if chip is not None:
            unpack_chip_for_editing(chip)
    elif key in '123456789':
        select_slot(int(key) - 1)


def key_state(key, down):
    if down:
        keys.add(key)
    else:
        keys.discard(key)


def look(dx, dy):
    global yaw, pitch
    yaw -= float(dx) * 0.0022
    pitch -= float(dy) * 0.0022
    pitch = max(-1.55, min(1.55, pitch))


def mouse_button(button):
    if inv_open or chip_dialog_data is not None:
        return
    if button == 0:
        break_target()
    elif button == 2:
        use_or_place()


# ====================================================================
# --- TICK / FRAME ---
# ====================================================================

redstone_timer = 0.0
outline_cell = None


def redstone_tick():
    # every cell of a chip maps to the same instance, so evaluate each chip only once,
    # and share one sim cache so identical chips with identical inputs cost one sim
    sim_cache = {}
    chips = list({id(chip): chip for chip in placed_chips.values()}.values())
    for chip in chips:
        chip.evaluate_circuit(sim_cache)

    dust_comps = [c for c in components.values() if c.kind == 'redstone_dust']
    levels = {c.pos: 0 for c in dust_comps}
    strong_powered = set()

    for comp in list(components.values()):
        if comp.kind == 'redstone_torch' and comp.lit:
            if comp.face != 'up':
                above = addpos(comp.pos, (0, 1, 0))
                if is_opaque_support(above):
                    strong_powered.add(above)
            for name in ('north', 'south', 'east', 'west', 'down'):
                n = addpos(comp.pos, DIRS[name])
                if n in levels:
                    levels[n] = 15
        elif comp.kind == 'lever' and comp.powered:
            if is_opaque_support(comp.attached_to):
                strong_powered.add(comp.attached_to)
            for name in ('north', 'south', 'east', 'west', 'down'):
                n = addpos(comp.pos, DIRS[name])
                if n in levels:
                    levels[n] = 15

    for chip in chips:
        for p in chip.outputs:
            if chip.output_states.get(p['id'], False):
                off = p['placed_offset']
                wp = (chip.pos[0] + off[0], chip.pos[1], chip.pos[2] + off[1])
                adj = addpos(wp, OUTSIDE_DIR[p['side']])
                if adj in levels:
                    levels[adj] = 15

    for sp in strong_powered:
        n = addpos(sp, (0, 1, 0))
        if n in levels:
            levels[n] = 15
        for name in ('east', 'west', 'north', 'south'):
            nb = addpos(sp, DIRS[name])
            dc = components.get(nb)
            if isinstance(dc, RedstoneDust) and OPPOSITE_FACE[name] in dc.connected_dirs:
                if levels[nb] < 15:
                    levels[nb] = 15

    for comp in dust_comps:
        comp.refresh_connections()

    for _ in range(16):
        changed = False
        for comp in dust_comps:
            cur = levels[comp.pos]
            best = cur
            for name in comp.connected_dirs:
                n = addpos(comp.pos, DIRS[name])
                if n in levels and levels[n] - 1 > best:
                    best = levels[n] - 1
            if best != cur:
                levels[comp.pos] = best
                changed = True
        if not changed:
            break

    powered = set(strong_powered)
    for comp in dust_comps:
        comp.power_level = levels[comp.pos]
        if comp.power_level >= 1:
            below = addpos(comp.pos, (0, -1, 0))
            if is_opaque_support(below):
                powered.add(below)
            for name in (comp.connected_dirs or ('north', 'south', 'east', 'west')):
                nb = addpos(comp.pos, DIRS[name])
                if is_opaque_support(nb):
                    powered.add(nb)

    for comp in dust_comps:
        comp.update_appearance()

    for comp in list(components.values()):
        if comp.kind == 'redstone_torch':
            comp.tick(powered)


def frame(dt):
    global water_timer, redstone_timer, outline_cell

    dt = min(max(float(dt), 0.0), 0.1)
    if not inv_open and chip_dialog_data is None:
        update_player(dt)
        water_timer += dt
        if water_timer >= WATER_INTERVAL:
            water_timer = 0.0
            update_water_physics()
        redstone_timer += dt
        if redstone_timer >= REDSTONE_TICK_RATE:
            redstone_timer = 0.0
            redstone_tick()

    B.setCamera(px, py, pz, yaw, pitch)

    cell, normal = raycast(6.0)
    if cell != outline_cell:
        outline_cell = cell
        if cell is None:
            B.setOutline(0, 0, 0, 0)
        else:
            B.setOutline(cell[0], cell[1], cell[2], 1)


# ====================================================================
# --- BOOT ---
# ====================================================================

init_inventory()
build_ground()
render_ui()

js.window.game = to_js({
    'frame': frame,
    'key_press': key_press,
    'key_state': key_state,
    'look': look,
    'mouse_button': mouse_button,
    'scroll': scroll,
    'select_slot': select_slot,
    'slot_click': slot_click,
    'slot_hover': slot_hover,
    'slot_unhover': slot_unhover,
    'toggle_inventory': toggle_inventory,
    'save_chip': save_chip,
    'cancel_chip': cancel_chip,
}, dict_converter=js.Object.fromEntries)

B.ready()
