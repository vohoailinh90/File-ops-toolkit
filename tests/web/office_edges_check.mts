// Behavior check for office/src/lib/edges.ts, run by tests/test_office_ui.py under Node's
// TypeScript type stripping. Exits non-zero on the first failed assertion.
import assert from "node:assert/strict"

import { edgeGeometry, relativeRect } from "../../office/src/lib/edges.ts"

const card = (x: number, y: number, w = 100, h = 60) => ({ x, y, w, h })

// A target below its source: leave the bottom edge, enter the top edge, both at the card centers.
const down = edgeGeometry(card(0, 0), card(200, 200))
assert.deepEqual(down.end, [250, 200])
assert.ok(down.d.startsWith("M50,60 "), down.d)
assert.ok(down.d.endsWith(" 250,200"), down.d)

// A target above its source: leave the top edge, enter the bottom edge.
const up = edgeGeometry(card(0, 200), card(200, 0))
assert.deepEqual(up.end, [250, 60])
assert.ok(up.d.startsWith("M50,200 "), up.d)

// Same row, target to the right: right edge to left edge, at the vertical centers.
const right = edgeGeometry(card(0, 0), card(200, 0))
assert.deepEqual(right.end, [200, 30])
assert.ok(right.d.startsWith("M100,30 "), right.d)

// Same row, target to the left: left edge to right edge.
const left = edgeGeometry(card(200, 0), card(0, 0))
assert.deepEqual(left.end, [100, 30])
assert.ok(left.d.startsWith("M200,30 "), left.d)

// Cards that overlap vertically by less than the slack still count as "below": no sideways loop for a 4px overlap.
const nearly = edgeGeometry(card(0, 0), card(0, 56))
assert.deepEqual(nearly.end, [50, 56])

// A control point sits halfway, so the curve leaves and arrives straight.
assert.match(down.d, /^M50,60 C50,130 250,130 250,200$/)
assert.match(right.d, /^M100,30 C150,30 150,30 200,30$/)

// relativeRect reads two viewport rectangles into the container's own coordinates.
const rect = (left: number, top: number, width: number, height: number) => ({ left, top, width, height }) as DOMRect
assert.deepEqual(relativeRect(rect(110, 220, 30, 40), rect(100, 200, 500, 500)), { x: 10, y: 20, w: 30, h: 40 })

console.log("office edges: ok")
