#!/usr/bin/env node
/**
 * Zero-dependency STL → PNG thumbnail (software z-buffer, no WebGL/GPU).
 *
 * Usage: node scripts/mesh_thumbnail.mjs <input.stl> <output.png> [width] [height]
 *
 * Exit codes: 0 ok, 1 render/IO failure, 2 usage
 */
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'

const input = process.argv[2]
const output = process.argv[3]
const width = Math.max(64, parseInt(process.argv[4] || '640', 10) || 640)
const height = Math.max(64, parseInt(process.argv[5] || '480', 10) || 480)

if (!input || !output) {
  console.error('usage: mesh_thumbnail.mjs <input.stl> <output.png> [width] [height]')
  process.exit(2)
}

if (!fs.existsSync(input)) {
  console.error('input missing:', input)
  process.exit(1)
}

const BG = [0x1c, 0x18, 0x14]
const LIGHT = normalize([0.45, 0.85, 0.55])
const AMBIENT = 0.28
const DIFFUSE = 0.72
const BASE_RGB = [0xcc, 0xcc, 0xcc]

function normalize (v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / len, v[1] / len, v[2] / len]
}

function cross (a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0]
  ]
}

function sub (a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

function dot (a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

function parseStl (buf) {
  if (buf.length >= 84) {
    const faceCount = buf.readUInt32LE(80)
    const expected = 84 + faceCount * 50
    // Binary STL: header 80 + uint32 count + 50 bytes/facet
    if (faceCount > 0 && expected <= buf.length + 50 && !looksLikeAscii(buf)) {
      return parseBinaryStl(buf, faceCount)
    }
  }
  return parseAsciiStl(buf.toString('utf8'))
}

function looksLikeAscii (buf) {
  const head = buf.subarray(0, Math.min(buf.length, 64)).toString('ascii').toLowerCase()
  return head.includes('solid') && !head.includes('\0')
}

function parseBinaryStl (buf, faceCount) {
  const tris = []
  let offset = 84
  const max = Math.min(faceCount, Math.floor((buf.length - 84) / 50))
  for (let i = 0; i < max; i++) {
    const nx = buf.readFloatLE(offset)
    const ny = buf.readFloatLE(offset + 4)
    const nz = buf.readFloatLE(offset + 8)
    const v0 = [buf.readFloatLE(offset + 12), buf.readFloatLE(offset + 16), buf.readFloatLE(offset + 20)]
    const v1 = [buf.readFloatLE(offset + 24), buf.readFloatLE(offset + 28), buf.readFloatLE(offset + 32)]
    const v2 = [buf.readFloatLE(offset + 36), buf.readFloatLE(offset + 40), buf.readFloatLE(offset + 44)]
    let n = [nx, ny, nz]
    if (!Number.isFinite(n[0]) || Math.hypot(n[0], n[1], n[2]) < 1e-8) {
      n = normalize(cross(sub(v1, v0), sub(v2, v0)))
    } else {
      n = normalize(n)
    }
    tris.push({ n, v: [v0, v1, v2] })
    offset += 50
  }
  return tris
}

function parseAsciiStl (text) {
  const tris = []
  const facetRe = /facet\s+normal\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)([\s\S]*?)endfacet/gi
  const vertRe = /vertex\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)/gi
  let m
  while ((m = facetRe.exec(text)) !== null) {
    const n = normalize([parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])])
    const body = m[4]
    const verts = []
    let vm
    vertRe.lastIndex = 0
    while ((vm = vertRe.exec(body)) !== null && verts.length < 3) {
      verts.push([parseFloat(vm[1]), parseFloat(vm[2]), parseFloat(vm[3])])
    }
    if (verts.length === 3 && verts.every(v => v.every(Number.isFinite))) {
      let nn = n
      if (Math.hypot(nn[0], nn[1], nn[2]) < 1e-8) {
        nn = normalize(cross(sub(verts[1], verts[0]), sub(verts[2], verts[0])))
      }
      tris.push({ n: nn, v: verts })
    }
  }
  return tris
}

function boundsOf (tris) {
  let minX = Infinity; let minY = Infinity; let minZ = Infinity
  let maxX = -Infinity; let maxY = -Infinity; let maxZ = -Infinity
  for (const t of tris) {
    for (const p of t.v) {
      if (p[0] < minX) minX = p[0]
      if (p[1] < minY) minY = p[1]
      if (p[2] < minZ) minZ = p[2]
      if (p[0] > maxX) maxX = p[0]
      if (p[1] > maxY) maxY = p[1]
      if (p[2] > maxZ) maxZ = p[2]
    }
  }
  return { min: [minX, minY, minZ], max: [maxX, maxY, maxZ] }
}

/** Isometric-ish view: rotate then orthographic project. */
function projectTris (tris, w, h) {
  const b = boundsOf(tris)
  const cx = (b.min[0] + b.max[0]) / 2
  const cy = (b.min[1] + b.max[1]) / 2
  const cz = (b.min[2] + b.max[2]) / 2
  const sx = (b.max[0] - b.min[0]) || 1
  const sy = (b.max[1] - b.min[1]) || 1
  const sz = (b.max[2] - b.min[2]) || 1
  const scale = 1 / Math.max(sx, sy, sz)

  // yaw ~35°, pitch ~30°
  const yaw = Math.PI / 5
  const pitch = Math.PI / 6
  const cyA = Math.cos(yaw); const syA = Math.sin(yaw)
  const cp = Math.cos(pitch); const sp = Math.sin(pitch)

  function xform (p) {
    let x = (p[0] - cx) * scale
    let y = (p[1] - cy) * scale
    let z = (p[2] - cz) * scale
    // yaw around Y
    const x1 = x * cyA + z * syA
    const z1 = -x * syA + z * cyA
    // pitch around X
    const y2 = y * cp - z1 * sp
    const z2 = y * sp + z1 * cp
    return [x1, y2, z2]
  }

  function xformN (n) {
    const x1 = n[0] * cyA + n[2] * syA
    const z1 = -n[0] * syA + n[2] * cyA
    const y2 = n[1] * cp - z1 * sp
    const z2 = n[1] * sp + z1 * cp
    return normalize([x1, y2, z2])
  }

  const projected = []
  let minX = Infinity; let minY = Infinity
  let maxX = -Infinity; let maxY = -Infinity
  for (const t of tris) {
    const v = t.v.map(xform)
    const n = xformN(t.n)
    // Back-face cull (camera looks down -Z toward origin)
    if (n[2] > 0.05) continue
    projected.push({ n, v })
    for (const p of v) {
      if (p[0] < minX) minX = p[0]
      if (p[1] < minY) minY = p[1]
      if (p[0] > maxX) maxX = p[0]
      if (p[1] > maxY) maxY = p[1]
    }
  }

  const pad = 0.08
  const spanX = (maxX - minX) || 1
  const spanY = (maxY - minY) || 1
  const margin = Math.max(spanX, spanY) * pad
  minX -= margin; maxX += margin
  minY -= margin; maxY += margin
  const fit = Math.min(w / ((maxX - minX) || 1), h / ((maxY - minY) || 1)) * 0.92
  const ox = w / 2 - ((minX + maxX) / 2) * fit
  const oy = h / 2 + ((minY + maxY) / 2) * fit // flip Y for image coords

  return projected.map(t => ({
    n: t.n,
    v: t.v.map(p => [p[0] * fit + ox, -p[1] * fit + oy, p[2]])
  }))
}

function shade (n) {
  const ndl = Math.max(0, -dot(n, LIGHT))
  const f = AMBIENT + DIFFUSE * ndl
  return [
    Math.min(255, Math.round(BASE_RGB[0] * f)),
    Math.min(255, Math.round(BASE_RGB[1] * f)),
    Math.min(255, Math.round(BASE_RGB[2] * f))
  ]
}

function rasterize (tris, w, h) {
  const pixels = Buffer.alloc(w * h * 4)
  const zbuf = new Float32Array(w * h)
  zbuf.fill(-Infinity)

  for (let i = 0; i < w * h; i++) {
    const o = i * 4
    pixels[o] = BG[0]
    pixels[o + 1] = BG[1]
    pixels[o + 2] = BG[2]
    pixels[o + 3] = 255
  }

  for (const t of tris) {
    const [a, b, c] = t.v
    const color = shade(t.n)
    fillTriangle(pixels, zbuf, w, h, a, b, c, color)
  }
  return pixels
}

function fillTriangle (pixels, zbuf, w, h, a, b, c, color) {
  const minX = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0])))
  const maxX = Math.min(w - 1, Math.ceil(Math.max(a[0], b[0], c[0])))
  const minY = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1])))
  const maxY = Math.min(h - 1, Math.ceil(Math.max(a[1], b[1], c[1])))
  const area = edge(a, b, c)
  if (Math.abs(area) < 1e-8) return

  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const p = [x + 0.5, y + 0.5]
      const w0 = edge(b, c, p) / area
      const w1 = edge(c, a, p) / area
      const w2 = edge(a, b, p) / area
      if (w0 < 0 || w1 < 0 || w2 < 0) continue
      const z = w0 * a[2] + w1 * b[2] + w2 * c[2]
      const idx = y * w + x
      if (z <= zbuf[idx]) continue
      zbuf[idx] = z
      const o = idx * 4
      pixels[o] = color[0]
      pixels[o + 1] = color[1]
      pixels[o + 2] = color[2]
      pixels[o + 3] = 255
    }
  }
}

function edge (a, b, c) {
  return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])
}

function crc32 (buf) {
  // Portable CRC-32 (IEEE) — avoid relying on zlib.crc32 Node version.
  let c = ~0
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) {
      c = (c >>> 1) ^ (0xedb88320 & -(c & 1))
    }
  }
  return (~c) >>> 0
}

function encodePng (rgba, w, h) {
  const raw = Buffer.alloc((w * 4 + 1) * h)
  for (let y = 0; y < h; y++) {
    const rowStart = y * (w * 4 + 1)
    raw[rowStart] = 0
    rgba.copy(raw, rowStart + 1, y * w * 4, (y + 1) * w * 4)
  }
  const compressed = zlib.deflateSync(raw, { level: 6 })

  function chunk (type, data) {
    const typeBuf = Buffer.from(type, 'ascii')
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length, 0)
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
    return Buffer.concat([len, typeBuf, data, crc])
  }

  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // RGBA
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', compressed),
    chunk('IEND', Buffer.alloc(0))
  ])
}

try {
  const buf = fs.readFileSync(input)
  const tris = parseStl(buf)
  if (!tris.length) {
    console.error('no triangles in STL')
    process.exit(1)
  }
  // Cap extreme meshes for worker memory/time
  const MAX_TRIS = 250_000
  const use = tris.length > MAX_TRIS ? tris.slice(0, MAX_TRIS) : tris
  const projected = projectTris(use, width, height)
  if (!projected.length) {
    console.error('all triangles culled')
    process.exit(1)
  }
  const pixels = rasterize(projected, width, height)
  const png = encodePng(pixels, width, height)
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, png)
} catch (err) {
  console.error(err)
  process.exit(1)
}
