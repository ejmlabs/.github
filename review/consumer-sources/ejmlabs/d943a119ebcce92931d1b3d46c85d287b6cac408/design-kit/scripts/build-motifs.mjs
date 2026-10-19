#!/usr/bin/env node
// Generates the grid, dots, contour, ripple and stripe motif families into motifs/.
// Deterministic: seeded math only, no dependencies, same bytes every run.
// Usage: node scripts/build-motifs.mjs [--check]   (--check verifies files on disk match the generator, and palette only)
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'motifs');
const check = process.argv.includes('--check');

// Brand palette (tokens/brand.css). Nothing else may appear in a generated file.
const C = { paper: '#F6F5EF', mist: '#E8EDE3', forest: '#29443B', ink: '#202721', sage: '#8A9A7B' };
// Surface: ground color, line color, and the line opacity that keeps the art quiet.
const SURFACES = {
  paper: { bg: C.paper, line: C.forest, m: 0.26 },
  mist: { bg: C.mist, line: C.forest, m: 0.28 },
  forest: { bg: C.forest, line: C.sage, m: 0.36 },
  ink: { bg: C.ink, line: C.sage, m: 0.32 },
};
const W = 1600, H = 900;

// ---- seeded math -----------------------------------------------------------
const rng = seed => () => { // mulberry32
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const hash = (x, y, s) => {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(s, 1103515245);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};
const fade = t => t * t * t * (t * (6 * t - 15) + 10);
const vnoise = (x, y, s) => { // smooth value noise, 0..1
  const ix = Math.floor(x), iy = Math.floor(y), fx = fade(x - ix), fy = fade(y - iy);
  const a = hash(ix, iy, s), b = hash(ix + 1, iy, s), c = hash(ix, iy + 1, s), d = hash(ix + 1, iy + 1, s);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
};
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const n1 = v => String(+v.toFixed(1));
const n3 = v => String(+v.toFixed(3));
const pathOf = pts => 'M' + pts.map(p => `${n1(p[0])} ${n1(p[1])}`).join('L');

// ---- svg shells --------------------------------------------------------------
const art = (label, w, h, body, bg) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${label}"><title>${label}</title>${bg ? `<rect width="${w}" height="${h}" fill="${bg}"/>` : ''}${body}</svg>\n`;
const tile = (size, body) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">${body}</svg>\n`;
const mask = (id, inner) =>
  `<defs>${inner}<mask id="${id}" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="url(#${id}-g)"/></mask></defs>`;

// ---- families: (line color, opacity multiplier) -> inner markup --------------
const families = {};

// grid: fine technical grid, a few emphasised lines, one soft elliptical crop
families.grid = {
  mood: 'precise, technical',
  label: 'grid',
  art(line, m) {
    const r = rng(11), minor = [], major = [], accent = [];
    const pick = (n, lo, hi) => { const s = new Set(); while (s.size < n) s.add(lo + 40 * Math.floor(r() * ((hi - lo) / 40 + 1))); return [...s].sort((a, b) => a - b); };
    const ax = pick(3, 600, 1400).filter(x => x % 200), ay = pick(2, 120, 760).filter(y => y % 200);
    for (let x = 40; x < W; x += 40) (ax.includes(x) ? accent : x % 200 ? minor : major).push(`M${x} 0V${H}`);
    for (let y = 40; y < H; y += 40) (ay.includes(y) ? accent : y % 200 ? minor : major).push(`M0 ${y}H${W}`);
    const g = (d, w, o) => `<path d="${d.join('')}" stroke-width="${w}" stroke-opacity="${n3(o * m)}"/>`;
    // Radial gradient squashed vertically: one soft elliptical crop.
    const crop = `<defs><radialGradient id="grid-fade-g" gradientUnits="userSpaceOnUse" cx="1020" cy="430" r="640" gradientTransform="translate(1020 430) scale(1 0.78) translate(-1020 -430)"><stop offset="0" stop-color="#fff"/><stop offset="0.55" stop-color="#fff" stop-opacity="0.8"/><stop offset="1" stop-color="#000"/></radialGradient><mask id="grid-fade" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="url(#grid-fade-g)"/></mask></defs>`;
    return `${crop}<g mask="url(#grid-fade)" fill="none" stroke="${line}">${g(minor, 0.8, 0.8)}${g(major, 1.1, 1)}${g(accent, 1.8, 1)}</g>`;
  },
  tile(line, m) {
    const p = (xs, v) => xs.map(v).join('');
    const minor = [], major = [];
    for (let k = 0; k <= 240; k += 40) (k % 120 ? minor : major).push(k);
    const d = (arr, w, o) => `<path d="${p(arr, k => `M${k} 0V240M0 ${k}H240`)}" stroke-width="${w}" stroke-opacity="${n3(o * m)}"/>`;
    return `<g fill="none" stroke="${line}">${d(minor, 0.8, 0.55)}${d(major, 1.1, 0.95)}</g>`;
  },
};

// dots: staggered halftone field, large on the right, fading to nothing on the left
families.dots = {
  mood: 'soft, printed',
  label: 'dots',
  art(line, m) {
    const step = 22, out = [];
    for (let j = 0, y = 12; y < H + step; j++, y += step * 0.866) {
      for (let x = (j % 2) * step / 2; x < W + step; x += step) {
        const t = (x / W) * 0.82 + (y / H) * 0.28 + (vnoise(x / 260, y / 260, 5) - 0.5) * 0.16;
        const r = 4.6 * Math.pow(smooth(0.26, 1.02, t), 1.15);
        if (r >= 0.5) out.push(`<circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r)}"/>`);
      }
    }
    return `<g fill="${line}" fill-opacity="${n3(0.8 * m)}">${out.join('')}</g>`;
  },
  tile(line, m) {
    const out = [];
    for (let j = 0; j < 10; j++) {
      const y = 12 + 24 * j;
      for (let i = 0; i <= 10; i++) {
        const x = 24 * i + (j % 2 ? 0 : 12);
        if (x <= 240) out.push(`<circle cx="${x}" cy="${y}" r="1.7"/>`);
      }
    }
    return `<g fill="${line}" fill-opacity="${n3(0.9 * m)}">${out.join('')}</g>`;
  },
};

// contour: topographic lines from smooth noise, calm and sparse on the left
families.contour = {
  mood: 'natural, exploratory',
  label: 'contour',
  art(line, m) {
    const cs = 10, nx = Math.ceil(W / cs) + 1, ny = Math.ceil(H / cs) + 1;
    const f = new Float64Array(nx * ny);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const x0 = i * cs, y0 = j * cs;
      // rotate and gently warp the domain so features do not line up with the frame
      const x = x0 * 0.866 - y0 * 0.5 + 60 * Math.sin(y0 / 210), y = x0 * 0.5 + y0 * 0.866 + 60 * Math.sin(x0 / 260);
      const n = vnoise(x / 640 + 3, y / 640 + 7, 21) * 0.72 + vnoise(x / 300, y / 300, 22) * 0.22 + vnoise(x / 140, y / 140, 23) * 0.06;
      const env = 0.14 + 0.86 * smooth(0.18, 0.78, x / W);
      f[j * nx + i] = 0.5 + (n - 0.5) * 1.5 * env;
    }
    const V = (i, j) => f[j * nx + i];
    const thin = [], bold = [];
    const levels = [];
    for (let l = 0.2, k = 0; l < 0.8; l += 0.026, k++) levels.push([l, k % 5 === 0]);
    for (const [lv, strong] of levels) {
      // edge ids: horizontal edge (i,j)-(i+1,j) = j*nx+i, vertical edge (i,j)-(i,j+1) = nx*ny + j*nx+i
      const H_ = (i, j) => j * nx + i, V_ = (i, j) => nx * ny + j * nx + i;
      const segs = [];
      for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
        const a = V(i, j) > lv, b = V(i + 1, j) > lv, c = V(i + 1, j + 1) > lv, d = V(i, j + 1) > lv;
        const idx = a * 8 + b * 4 + c * 2 + d;
        if (idx === 0 || idx === 15) continue;
        const T = H_(i, j), R = V_(i + 1, j), B = H_(i, j + 1), L = V_(i, j);
        const centre = (V(i, j) + V(i + 1, j) + V(i + 1, j + 1) + V(i, j + 1)) / 4 > lv;
        const table = {
          1: [[L, B]], 2: [[B, R]], 3: [[L, R]], 4: [[T, R]], 6: [[T, B]], 7: [[T, L]], 8: [[T, L]], 9: [[T, B]],
          11: [[T, R]], 12: [[L, R]], 13: [[B, R]], 14: [[L, B]],
          5: centre ? [[T, L], [B, R]] : [[T, R], [L, B]],
          10: centre ? [[T, R], [L, B]] : [[T, L], [B, R]],
        };
        for (const s of table[idx]) segs.push(s);
      }
      const pt = id => {
        if (id < nx * ny) { const j = Math.floor(id / nx), i = id % nx, a = V(i, j), b = V(i + 1, j); return [(i + (lv - a) / (b - a)) * cs, j * cs]; }
        id -= nx * ny; const j = Math.floor(id / nx), i = id % nx, a = V(i, j), b = V(i, j + 1);
        return [i * cs, (j + (lv - a) / (b - a)) * cs];
      };
      const at = new Map();
      segs.forEach((s, k) => s.forEach(e => { if (!at.has(e)) at.set(e, []); at.get(e).push(k); }));
      const used = new Uint8Array(segs.length);
      const walk = (chain, end, push) => {
        for (;;) {
          const next = (at.get(end) || []).find(k => !used[k]);
          if (next === undefined) return;
          used[next] = 1;
          const [p, q] = segs[next]; end = p === end ? q : p; push(end);
        }
      };
      for (let k = 0; k < segs.length; k++) {
        if (used[k]) continue;
        used[k] = 1;
        const chain = [segs[k][0], segs[k][1]];
        walk(chain, chain[1], e => chain.push(e));
        walk(chain, chain[0], e => chain.unshift(e));
        (strong ? bold : thin).push(pathOf(chain.map(pt)));
      }
    }
    const grp = (d, w, o) => `<path d="${d.join('')}" stroke-width="${w}" stroke-opacity="${n3(o * m)}"/>`;
    return `<g fill="none" stroke="${line}" stroke-linejoin="round" stroke-linecap="round">${grp(thin, 0.9, 0.7)}${grp(bold, 1.5, 1)}</g>`;
  },
};

// ripple: concentric rings from an off-canvas origin, spacing drifts slowly, fading with distance
families.ripple = {
  mood: 'expanding, resonant',
  label: 'ripple',
  art(line, m) {
    const r = rng(31), cx = 1500, cy = 1010;
    const rmax = Math.hypot(cx, cy);
    const rings = [];
    let rad = 90, k = 0;
    while (rad < rmax + 40) {
      rad += 42 * (1 + 0.3 * Math.sin(k * 0.5 + 0.8) + 0.08 * (r() - 0.5));
      if (rad > Math.hypot(cx - W, cy - H) - 10) rings.push([rad, k]);
      k++;
    }
    const first = rings[0][0], last = rings[rings.length - 1][0];
    const out = rings.map(([rad, i]) => {
      const strong = i % 6 === 0;
      const far = (rad - first) / (last - first);
      const o = (strong ? 1 : 0.62) * (1 - 0.8 * smooth(0.05, 1.0, far));
      return `<circle cx="${cx}" cy="${cy}" r="${n1(rad)}" stroke-width="${strong ? 1.6 : 1}" stroke-opacity="${n3(o * m)}"/>`;
    });
    return `<g fill="none" stroke="${line}">${out.join('')}</g>`;
  },
};

// stripe: diagonal parallel hairlines carrying one gentle wave, dissolving toward the top left
families.stripe = {
  mood: 'directional, rhythmic',
  label: 'stripe',
  art(line, m) {
    const th = -28 * Math.PI / 180, t = [Math.cos(th), Math.sin(th)], n = [-Math.sin(th), Math.cos(th)];
    const us = [[0, 0], [W, 0], [0, H], [W, H]].map(p => p[0] * n[0] + p[1] * n[1]);
    const umin = Math.min(...us) - 60, umax = Math.max(...us) + 60;
    const thin = [], bold = [];
    const margin = 40, step = 24;
    for (let u = umin, k = 0; u <= umax; u += 20, k++) {
      const run = [];
      for (let s = -2200; s <= 2200; s += step) {
        const d = 30 * (0.7 + 0.3 * Math.sin(u / 240)) * Math.sin((2 * Math.PI * s) / 980 + u * 0.0055);
        const x = u * n[0] + s * t[0] + d * n[0], y = u * n[1] + s * t[1] + d * n[1];
        if (x > -margin && x < W + margin && y > -margin && y < H + margin) run.push([x, y]);
      }
      if (run.length > 1) (k % 8 === 0 ? bold : thin).push(pathOf(run));
    }
    const grp = (d, w, o) => `<path d="${d.join('')}" stroke-width="${w}" stroke-opacity="${n3(o * m)}"/>`;
    const fadeDef = `<defs><linearGradient id="stripe-fade-g" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="${W}" y2="${H}"><stop offset="0.04" stop-color="#000"/><stop offset="0.5" stop-color="#fff"/></linearGradient><mask id="stripe-fade" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="url(#stripe-fade-g)"/></mask></defs>`;
    return `${fadeDef}<g mask="url(#stripe-fade)" fill="none" stroke="${line}">${grp(thin, 0.9, 0.85)}${grp(bold, 1.4, 1)}</g>`;
  },
  tile(line, m) {
    // Lines run y = x + c + wave(x) with c on a 24 step and wave period 240, so the tile repeats in both directions.
    const out = [];
    for (let c = -288; c <= 264; c += 24) {
      const pts = [];
      for (let x = -24; x <= 264; x += 8) pts.push([x, x + c + 7 * Math.sin((2 * Math.PI * x) / 240)]);
      out.push(pathOf(pts));
    }
    return `<g fill="none" stroke="${line}" stroke-width="0.9" stroke-opacity="${n3(0.8 * m)}"><path d="${out.join('')}"/></g>`;
  },
};

// ---- outputs -------------------------------------------------------------------
const files = new Map();
const TILE = { light: { line: C.forest, m: 0.22 }, dark: { line: C.sage, m: 0.3 } };
for (const [name, fam] of Object.entries(families)) {
  for (const [s, cfg] of Object.entries(SURFACES)) {
    files.set(`${name}-${s}.svg`, art(`ejmlabs ${name} motif on ${s}`, W, H, fam.art(cfg.line, cfg.m), cfg.bg));
  }
  files.set(`${name}-lines.svg`, art(`${name[0].toUpperCase()}${name.slice(1)} lines, transparent`, W, H, fam.art(C.forest, 1)));
  if (fam.tile) for (const [v, cfg] of Object.entries(TILE)) files.set(`tiles/${name}-tile-${v}.svg`, tile(240, fam.tile(cfg.line, cfg.m)));
}

// ---- write or check -------------------------------------------------------------
const palette = new Set(Object.values(C).map(v => v.toLowerCase()).concat(['#fff', '#000']));
const problems = [];
for (const [rel, text] of files) {
  for (const hex of text.match(/#[0-9a-fA-F]{3,6}\b/g) || []) if (!palette.has(hex.toLowerCase())) problems.push(`${rel}: color ${hex} is not in the palette`);
  if (/NaN|undefined|\u2014/.test(text)) problems.push(`${rel}: contains NaN, undefined or an em dash`);
  const path = join(root, rel);
  if (check) { if (!existsSync(path) || readFileSync(path, 'utf8') !== text) problems.push(`${rel}: missing or out of date, run node scripts/build-motifs.mjs`); }
  else { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, text); }
}
if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
console.log(check ? `motifs ok (${files.size} files)` : `wrote ${files.size} files to motifs/`);
