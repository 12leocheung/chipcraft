// Rendering + input bridge. Python (game.py, running under Pyodide) owns the world
// state and the simulation; this file draws it with three.js and forwards input back.
import * as THREE from 'three';

const TEX = {
  grass: 'assets/grass_top.png',
  stone: 'assets/stone.png',
  dirt: 'assets/dirt.png',
  oak_plank: 'assets/wood.png',
  brick: 'assets/brick.png',
  water_block: 'assets/water.png',
  glass: 'assets/glass.png',
  sand: 'assets/sand.png',
  oak_log: 'assets/oak_log_top.png',
  surrounder: 'assets/surrounder.png',
  chip_input: 'assets/io_in.png',
  chip_output: 'assets/io_out.png',
  chip: 'assets/chip.png',
};

const ITEM_ICON = {
  grass: 'assets/grass_top.png',
  stone: 'assets/stone.png',
  dirt: 'assets/dirt.png',
  oak_plank: 'assets/wood.png',
  brick: 'assets/brick.png',
  water_block: 'assets/water.png',
  glass: 'assets/glass.png',
  sand: 'assets/sand.png',
  oak_log: 'assets/oak_log_top.png',
  surrounder: 'assets/surrounder.png',
  chip_input: 'assets/io_in.png',
  chip_output: 'assets/io_out.png',
  chip: 'assets/chip.png',
  lever: 'assets/lever_item.png',
  redstone_torch: 'assets/torch_item.png',
  redstone_dust: 'assets/redstone_item.png',
};

const DIR = {
  up: [0, 1, 0], down: [0, -1, 0],
  north: [0, 0, -1], south: [0, 0, 1],
  east: [1, 0, 0], west: [-1, 0, 0],
};

export function createBridge() {
  // ---------------------------------------------------------------- scene
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x8fc9e8);
  scene.fog = new THREE.Fog(0x8fc9e8, 45, 90);

  const camera = new THREE.PerspectiveCamera(72, window.innerWidth / window.innerHeight, 0.05, 400);
  camera.rotation.order = 'YXZ';

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.getElementById('view').appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(0.6, 1, 0.35);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-0.6, 0.4, -0.5);
  scene.add(fill);

  // ---------------------------------------------------------------- textures
  const loader = new THREE.TextureLoader();
  const textureCache = new Map();
  function texture(type) {
    if (textureCache.has(type)) return textureCache.get(type);
    const url = TEX[type];
    let tex;
    if (url) {
      tex = loader.load(url);
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4;
    } else {
      tex = proceduralTexture(type);
    }
    textureCache.set(type, tex);
    return tex;
  }

  const FALLBACK_COLOR = {
    redstone_torch: '#b53a1a', redstone_dust: '#8c1a1a', lever: '#8a7358',
  };
  function proceduralTexture(type) {
    const size = 32;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = FALLBACK_COLOR[type] || '#9a9a9a';
    ctx.fillRect(0, 0, size, size);
    for (let i = 0; i < 140; i++) {
      ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.18})`;
      ctx.fillRect(Math.random() * size, Math.random() * size, 2, 2);
    }
    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, size - 2, size - 2);
    const tex = new THREE.CanvasTexture(canvas);
    tex.magFilter = THREE.NearestFilter;
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  // ---------------------------------------------------------------- blocks
  const blockIndex = new Map();        // "x,y,z" -> type
  const positionsByType = new Map();   // type -> Map("x,y,z" -> [x, y, z])
  const meshes = new Map();            // type -> { mesh, capacity }
  const dirtyTypes = new Set();
  const keyOf = (x, y, z) => `${x},${y},${z}`;

  function setOf(type) {
    let set = positionsByType.get(type);
    if (!set) {
      set = new Map();
      positionsByType.set(type, set);
    }
    return set;
  }

  function ensureMesh(type, count) {
    let rec = meshes.get(type);
    if (rec && rec.capacity >= count) return rec;
    const capacity = Math.max(64, 1 << Math.ceil(Math.log2(Math.max(count, 2))));
    if (rec) {
      scene.remove(rec.mesh);
      rec.mesh.dispose();
    }
    const material = new THREE.MeshLambertMaterial({ map: texture(type) });
    if (type === 'water_block' || type === 'glass') {
      material.transparent = true;
      material.opacity = type === 'glass' ? 0.55 : 0.8;
      material.depthWrite = false;
    }
    const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material, capacity);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    mesh.count = 0;
    rec = { mesh, capacity };
    meshes.set(type, rec);
    scene.add(mesh);
    return rec;
  }

  const matrix = new THREE.Matrix4();
  function rebuildType(type) {
    const positions = setOf(type);
    const rec = ensureMesh(type, positions.size);
    let i = 0;
    for (const p of positions.values()) {
      matrix.makeTranslation(p[0], p[1], p[2]);
      rec.mesh.setMatrixAt(i++, matrix);
    }
    rec.mesh.count = i;
    rec.mesh.instanceMatrix.needsUpdate = true;
    if (rec.mesh.computeBoundingSphere) rec.mesh.computeBoundingSphere();
  }

  function flush() {
    if (!dirtyTypes.size) return;
    for (const type of dirtyTypes) rebuildType(type);
    dirtyTypes.clear();
  }

  function setBlock(type, x, y, z) {
    const k = keyOf(x, y, z);
    const previous = blockIndex.get(k);
    if (previous === type) return;
    if (previous) {
      setOf(previous).delete(k);
      dirtyTypes.add(previous);
    }
    blockIndex.set(k, type);
    setOf(type).set(k, [x, y, z]);
    dirtyTypes.add(type);
  }

  function removeBlock(x, y, z) {
    const k = keyOf(x, y, z);
    const previous = blockIndex.get(k);
    if (!previous) return;
    blockIndex.delete(k);
    setOf(previous).delete(k);
    dirtyTypes.add(previous);
  }

  // ---------------------------------------------------------------- outline
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(1.004, 1.004, 1.004)),
    new THREE.LineBasicMaterial({ color: 0x0b0b0b, transparent: true, opacity: 0.85 }),
  );
  outline.visible = false;
  scene.add(outline);

  // ---------------------------------------------------------------- components
  const components = new Map();

  const stickMat = new THREE.MeshLambertMaterial({ map: texture('lever') });
  const plateMat = new THREE.MeshLambertMaterial({ map: (() => {
    const t = loader.load('assets/lever_base.png');
    t.magFilter = THREE.NearestFilter;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })() });
  const torchOff = new THREE.Color(0x78281e);
  const torchOn = new THREE.Color(0xff3d14);
  const dustDark = new THREE.Color(0x4d0505);

  function box(w, h, d, material) {
    return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  }

  function torchLayout(face) {
    if (face === 'up') return { shaft: [0, 0.1875, 0], tip: [0, -0.1875, 0] };
    if (face === 'down') return { shaft: [0, -0.1875, 0], tip: [0, 0.1875, 0] };
    const d = DIR[face];
    return { shaft: [d[0] * 0.34, -0.0475, d[2] * 0.34], tip: [d[0] * 0.34, 0.325, d[2] * 0.34] };
  }

  function leverLayout(face) {
    if (face === 'down') {
      return { plate: [0, -0.47, 0], plateScale: [0.6, 0.06, 0.6], hinge: [0, -0.44, 0], axis: 'x', off: -35, on: 35 };
    }
    if (face === 'up') {
      return { plate: [0, 0.47, 0], plateScale: [0.6, 0.06, 0.6], hinge: [0, 0.44, 0], axis: 'x', off: 180, on: 145 };
    }
    const d = DIR[face];
    if (face === 'north' || face === 'south') {
      return {
        plate: [0, -0.05, d[2] * 0.47], plateScale: [0.6, 0.5, 0.06],
        hinge: [0, -0.05, d[2] * 0.41], axis: 'z', off: -25, on: -155,
      };
    }
    return {
      plate: [d[0] * 0.47, -0.05, 0], plateScale: [0.06, 0.5, 0.6],
      hinge: [d[0] * 0.41, -0.05, 0], axis: 'x', off: 25, on: 155,
    };
  }

  function addComponent(kind, x, y, z, face) {
    const group = new THREE.Group();
    group.position.set(x, y, z);
    const key = keyOf(x, y, z);
    const record = { kind, face, group };

    if (kind === 'redstone_torch') {
      const layout = torchLayout(face);
      const shaft = box(0.125, 0.625, 0.125, stickMat);
      shaft.position.set(...layout.shaft);
      const tip = box(0.16, 0.125, 0.16, new THREE.MeshBasicMaterial({ color: torchOn }));
      tip.position.set(...layout.tip);
      group.add(shaft, tip);
      record.tip = tip;
    } else if (kind === 'lever') {
      const layout = leverLayout(face);
      const plate = box(...layout.plateScale, plateMat);
      plate.position.set(...layout.plate);
      const handleGeometry = new THREE.BoxGeometry(0.075, 0.45, 0.075).translate(0, 0.225, 0);
      const handle = new THREE.Mesh(handleGeometry, stickMat);
      handle.position.set(...layout.hinge);
      group.add(plate, handle);
      record.handle = handle;
      record.layout = layout;
    } else if (kind === 'redstone_dust') {
      const material = new THREE.MeshBasicMaterial({ color: dustDark });
      const center = box(0.4, 0.05, 0.4, material);
      center.position.set(0, -0.475, 0);
      group.add(center);
      record.dustMaterial = material;
      record.arms = {};
      for (const name of ['north', 'south', 'east', 'west']) {
        const d = DIR[name];
        const horizontal = name === 'east' || name === 'west';
        const arm = box(horizontal ? 0.3 : 0.15, 0.05, horizontal ? 0.15 : 0.3, material);
        arm.position.set(d[0] * 0.35, -0.475, d[2] * 0.35);
        group.add(arm);
        record.arms[name] = arm;
      }
    }

    scene.add(group);
    components.set(key, record);
  }

  function removeComponent(x, y, z) {
    const key = keyOf(x, y, z);
    const record = components.get(key);
    if (!record) return;
    scene.remove(record.group);
    components.delete(key);
  }

  function setLeverOn(x, y, z, on) {
    const record = components.get(keyOf(x, y, z));
    if (!record || !record.handle) return;
    const angle = on ? record.layout.on : record.layout.off;
    const radians = (angle * Math.PI) / 180;
    if (record.layout.axis === 'x') {
      record.handle.rotation.x = radians;
      record.handle.rotation.z = 0;
    } else {
      record.handle.rotation.z = -radians;
      record.handle.rotation.x = 0;
    }
  }

  function setTorchLit(x, y, z, lit) {
    const record = components.get(keyOf(x, y, z));
    if (!record || !record.tip) return;
    record.tip.material.color.copy(lit ? torchOn : torchOff);
  }

  function setDustLevel(x, y, z, level, mask) {
    const record = components.get(keyOf(x, y, z));
    if (!record || !record.dustMaterial) return;
    const t = Math.min(1, level / 15);
    record.dustMaterial.color.setRGB(0.35 + 0.65 * t, 0.13 * (0.35 + 0.65 * t), 0.12 * (0.35 + 0.65 * t));
    const names = ['north', 'south', 'east', 'west'];
    names.forEach((name, i) => {
      record.arms[name].visible = mask === 0 ? true : (mask & (1 << i)) !== 0;
    });
  }

  // ---------------------------------------------------------------- chips
  const chips = new Map();
  const chipTexture = (() => {
    const t = loader.load('assets/chip.png');
    t.magFilter = THREE.NearestFilter;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const chipMaterial = new THREE.MeshLambertMaterial({ map: chipTexture });
  const pinOffColor = 0x005064;
  const pinOnColor = 0x00e0ff;
  const pinOutOffColor = 0x642800;
  const pinOutOnColor = 0xff9600;

  function addChip(key, x, y, z, w, l, portsJson) {
    const ports = JSON.parse(portsJson);
    const group = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(w, 1, l), chipMaterial);
    body.position.set(x + (w - 1) / 2, y, z + (l - 1) / 2);
    group.add(body);

    const pins = [];
    for (const port of ports) {
      const wx = x + port.off[0];
      const wz = z + port.off[1];
      let position;
      let scale;
      if (port.side === 'north') {
        position = [wx, y, wz + 0.51]; scale = [0.35, 0.35, 0.04];
      } else if (port.side === 'south') {
        position = [wx, y, wz - 0.51]; scale = [0.35, 0.35, 0.04];
      } else if (port.side === 'east') {
        position = [wx + 0.51, y, wz]; scale = [0.04, 0.35, 0.35];
      } else if (port.side === 'west') {
        position = [wx - 0.51, y, wz]; scale = [0.04, 0.35, 0.35];
      } else {
        position = [wx, y, wz]; scale = [0.35, 0.04, 0.35];
      }
      const pin = new THREE.Mesh(
        new THREE.BoxGeometry(scale[0], scale[1], scale[2]),
        new THREE.MeshBasicMaterial({ color: port.out ? pinOutOffColor : pinOffColor }),
      );
      pin.position.set(...position);
      pin.userData.out = port.out;
      group.add(pin);
      pins.push(pin);
    }

    scene.add(group);
    chips.set(key, { group, pins });
  }

  function setChipPorts(key, statesJson) {
    const record = chips.get(key);
    if (!record) return;
    const states = JSON.parse(statesJson);
    record.pins.forEach((pin, i) => {
      const on = !!states[i];
      pin.material.color.setHex(pin.userData.out
        ? (on ? pinOutOnColor : pinOutOffColor)
        : (on ? pinOnColor : pinOffColor));
    });
  }

  function removeChip(key) {
    const record = chips.get(key);
    if (!record) return;
    scene.remove(record.group);
    chips.delete(key);
  }

  // ---------------------------------------------------------------- HUD
  const hotbarEl = document.getElementById('hotbar');
  const invEl = document.getElementById('inventory');
  const invGridEl = document.getElementById('inv-grid');
  const invHotbarEl = document.getElementById('inv-hotbar');
  const tagEl = document.getElementById('tag');
  const toastEl = document.getElementById('toast');
  const heldEl = document.getElementById('held');
  const lockHint = document.getElementById('lock-hint');
  const chipModal = document.getElementById('chip-modal');
  const chipTitle = document.getElementById('chip-title');
  const chipName = document.getElementById('chip-name');

  let tagTimer = 0;

  function makeSlots(container, count, startIndex) {
    const slots = [];
    container.innerHTML = '';
    for (let i = 0; i < count; i++) {
      const slot = document.createElement('div');
      slot.className = 'slot';
      slot.dataset.slot = String(startIndex + i);
      const img = document.createElement('img');
      img.draggable = false;
      img.alt = '';
      const countEl = document.createElement('span');
      countEl.className = 'slot-count';
      slot.append(img, countEl);
      container.appendChild(slot);
      slots.push({ root: slot, img, countEl });
    }
    return slots;
  }

  const hotbarSlots = makeSlots(hotbarEl, 9, 0);
  const invGridSlots = makeSlots(invGridEl, 18, 9);
  const invHotbarSlots = makeSlots(invHotbarEl, 9, 0);

  function paint(slot, entry, selected, held) {
    slot.root.classList.toggle('selected', selected);
    slot.root.classList.toggle('held', held);
    if (entry && entry.type && entry.count > 0) {
      const src = ITEM_ICON[entry.type] || 'assets/chip.png';
      if (slot.img.getAttribute('src') !== src) slot.img.src = src;
      slot.img.style.visibility = 'visible';
      slot.countEl.textContent = entry.count > 1 ? String(entry.count) : '';
      slot.root.title = entry.name || entry.type;
    } else {
      slot.img.style.visibility = 'hidden';
      slot.countEl.textContent = '';
      slot.root.title = '';
    }
  }

  function renderHotbar(json, selected) {
    const data = JSON.parse(json);
    hotbarSlots.forEach((slot, i) => paint(slot, data[i], i === selected, false));
  }

  function renderInventory(json, selected, held, open) {
    const data = JSON.parse(json);
    invGridSlots.forEach((slot, i) => paint(slot, data[i + 9], (i + 9) === selected, (i + 9) === held));
    invHotbarSlots.forEach((slot, i) => paint(slot, data[i], i === selected, i === held));
    invEl.classList.toggle('open', !!open);
    if (open) {
      heldEl.style.visibility = 'hidden';
    }
    updateLockHint();
  }

  function setHeld(type) {
    if (!type || invEl.classList.contains('open')) {
      heldEl.style.visibility = 'hidden';
      return;
    }
    const src = ITEM_ICON[type] || 'assets/chip.png';
    if (heldEl.getAttribute('src') !== src) heldEl.src = src;
    heldEl.style.visibility = 'visible';
  }

  function showTag(text, hold) {
    clearTimeout(tagTimer);
    if (!text) {
      tagEl.classList.remove('show');
      return;
    }
    tagEl.textContent = text;
    tagEl.classList.add('show');
    if (!hold) tagTimer = setTimeout(() => tagEl.classList.remove('show'), 1800);
  }

  function notify(text) {
    toastEl.textContent = text;
    toastEl.classList.add('show');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toastEl.classList.remove('show'), 2500);
  }

  function openChipDialog(width, length) {
    chipTitle.textContent = `Save Chip (Size: ${width}x${length})`;
    chipName.value = '';
    chipModal.classList.add('open');
    document.exitPointerLock();
    setTimeout(() => chipName.focus(), 30);
    updateLockHint();
  }

  function closeChipDialog() {
    chipModal.classList.remove('open');
    updateLockHint();
  }

  function unlockPointer() {
    document.exitPointerLock();
    updateLockHint();
  }

  function uiBlocking() {
    return invEl.classList.contains('open') || chipModal.classList.contains('open');
  }

  function updateLockHint() {
    const locked = document.pointerLockElement === renderer.domElement;
    lockHint.style.display = !locked && !uiBlocking() ? 'block' : 'none';
    document.getElementById('crosshair').style.display = locked ? 'block' : 'none';
  }

  // ---------------------------------------------------------------- camera
  function setCamera(x, y, z, yaw, pitch) {
    camera.position.set(x, y, z);
    camera.rotation.set(pitch, yaw, 0);
  }

  function setOutline(x, y, z, visible) {
    outline.visible = !!visible;
    if (visible) outline.position.set(x, y, z);
  }

  // ---------------------------------------------------------------- input
  function bind() {
    const canvas = renderer.domElement;

    canvas.addEventListener('click', () => {
      if (!uiBlocking() && document.pointerLockElement !== canvas) canvas.requestPointerLock();
    });

    document.addEventListener('pointerlockchange', updateLockHint);

    document.addEventListener('mousemove', (event) => {
      if (document.pointerLockElement !== canvas) return;
      if (window.game && window.game.look) window.game.look(event.movementX, event.movementY);
    });

    document.addEventListener('mousedown', (event) => {
      if (uiBlocking()) return;
      if (document.pointerLockElement !== canvas) return;
      if (window.game && window.game.mouse_button) window.game.mouse_button(event.button);
    });

    canvas.addEventListener('contextmenu', (event) => event.preventDefault());

    window.addEventListener('wheel', (event) => {
      if (uiBlocking()) return;
      if (window.game && window.game.scroll) window.game.scroll(event.deltaY > 0 ? 1 : -1);
    }, { passive: true });

    const movement = { w: 'w', a: 'a', s: 's', d: 'd', Shift: 'shift', ' ': 'space' };
    window.addEventListener('keydown', (event) => {
      if (event.target && event.target.tagName === 'INPUT') return;
      const key = event.key;
      if (movement[key]) {
        if (window.game && window.game.key_state) window.game.key_state(movement[key], true);
        event.preventDefault();
        return;
      }
      if (event.repeat) return;
      if (key === 'Escape' || key === 'e' || key === 'E' || key === 'k' || key === 'K'
          || key === 'l' || key === 'L' || /^[1-9]$/.test(key)) {
        if (window.game && window.game.key_press) {
          window.game.key_press(key === 'Escape' ? 'escape' : key.toLowerCase());
        }
      }
    });

    window.addEventListener('keyup', (event) => {
      const key = movement[event.key];
      if (key && window.game && window.game.key_state) window.game.key_state(key, false);
    });

    window.addEventListener('blur', () => {
      if (!window.game || !window.game.key_state) return;
      for (const key of ['w', 'a', 's', 'd', 'shift', 'space']) window.game.key_state(key, false);
    });

    // HUD buttons
    hotbarEl.addEventListener('click', (event) => {
      const slot = event.target.closest('.slot');
      if (slot && window.game) window.game.select_slot(Number(slot.dataset.slot));
    });
    for (const container of [invGridEl, invHotbarEl]) {
      container.addEventListener('click', (event) => {
        const slot = event.target.closest('.slot');
        if (slot && window.game) window.game.slot_click(Number(slot.dataset.slot));
      });
      container.addEventListener('mouseover', (event) => {
        const slot = event.target.closest('.slot');
        if (slot && window.game) window.game.slot_hover(Number(slot.dataset.slot));
      });
      container.addEventListener('mouseleave', () => {
        if (window.game) window.game.slot_unhover();
      });
    }
    hotbarEl.addEventListener('mouseover', (event) => {
      const slot = event.target.closest('.slot');
      if (slot && window.game) window.game.slot_hover(Number(slot.dataset.slot));
    });
    hotbarEl.addEventListener('mouseleave', () => {
      if (window.game) window.game.slot_unhover();
    });

    document.getElementById('chip-save').addEventListener('click', () => {
      if (window.game) window.game.save_chip(chipName.value);
    });
    document.getElementById('chip-cancel').addEventListener('click', () => {
      if (window.game) window.game.cancel_chip();
    });
    chipName.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && window.game) window.game.save_chip(chipName.value);
      if (event.key === 'Escape' && window.game) window.game.cancel_chip();
    });

    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });
  }

  // ---------------------------------------------------------------- loop
  let last = performance.now();
  function loop(now) {
    const dt = (now - last) / 1000;
    last = now;
    if (window.game && window.game.frame) {
      try {
        window.game.frame(dt);
      } catch (error) {
        console.error(error);
      }
    }
    flush();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }

  bind();
  updateLockHint();
  requestAnimationFrame(loop);

  return {
    setBlocksJson: (json) => {
      for (const [type, x, y, z] of JSON.parse(json)) setBlock(type, x, y, z);
      // bulk load: build every mesh now instead of on the first frame
      flush();
    },
    setBlock,
    removeBlock,
    addComponent,
    removeComponent,
    setLeverOn,
    setTorchLit,
    setDustLevel,
    addChip,
    setChipPorts,
    removeChip,
    setCamera,
    setOutline,
    renderHotbar,
    renderInventory,
    setHeld,
    showTag,
    notify,
    openChipDialog,
    closeChipDialog,
    unlockPointer,
    ready: () => {
      const loading = document.getElementById('loading');
      if (loading) loading.classList.add('done');
      updateLockHint();
    },
  };
}
