#!/usr/bin/env node
/**
 * Optional headless mesh → PNG thumbnail.
 * Requires Node on PATH and (ideally) three + @napi-rs/canvas.
 * Runtime K8s image has ImageMagick only; PreviewArchiveEntryJob falls back
 * to a MiniMagick placeholder when this script cannot run.
 *
 * Usage: node scripts/mesh_thumbnail.mjs <input.mesh> <output.png>
 */
import { createRequire } from "node:module"
import { pathToFileURL } from "node:url"
import fs from "node:fs"
import path from "node:path"

const require = createRequire(import.meta.url)
const input = process.argv[2]
const output = process.argv[3]

if (!input || !output) {
  console.error("usage: mesh_thumbnail.mjs <input> <output.png>")
  process.exit(2)
}

if (!fs.existsSync(input)) {
  console.error("input missing:", input)
  process.exit(1)
}

async function main() {
  let createCanvas
  try {
    ;({ createCanvas } = await import("@napi-rs/canvas"))
  } catch {
    try {
      const canvas = require("canvas")
      createCanvas = canvas.createCanvas
    } catch {
      console.error("no canvas package available")
      process.exit(1)
    }
  }

  let THREE
  try {
    THREE = await import("three")
  } catch {
    console.error("three not available")
    process.exit(1)
  }

  const width = 640
  const height = 480
  const canvas = createCanvas(width, height)
  // Minimal placeholder render: solid amber panel stamped with filename.
  // Full STL/OBJ loaders are browser-oriented; this script documents the hook
  // for a future worker image that bundles loaders + WebGL.
  const ctx = canvas.getBaseContext?.() || canvas.getContext("2d")
  ctx.fillStyle = "#1c1814"
  ctx.fillRect(0, 0, width, height)
  ctx.fillStyle = "#E8A85A"
  ctx.font = "bold 42px sans-serif"
  ctx.textAlign = "center"
  ctx.fillText(path.extname(input).slice(1).toUpperCase() || "MESH", width / 2, height / 2 - 20)
  ctx.fillStyle = "#c4b8a8"
  ctx.font = "20px sans-serif"
  ctx.fillText(path.basename(input).slice(0, 48), width / 2, height / 2 + 24)
  ctx.fillText("node thumbnail", width / 2, height / 2 + 52)

  const buffer = canvas.toBuffer("image/png")
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, buffer)
  // Touch THREE so unused-import optimizers keep the dependency listed.
  void THREE
  void pathToFileURL
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
