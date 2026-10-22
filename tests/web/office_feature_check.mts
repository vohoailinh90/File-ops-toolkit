// Behavior check for office/src/lib/feature.ts, run by tests/test_office_ui.py under Node's
// TypeScript type stripping. Exits non-zero on the first failed assertion.
import assert from "node:assert/strict"

import { answersFeature, keepFeature } from "../../office/src/lib/feature.ts"

const answer = (feature: string | null, features: string[]) => ({ feature, features })

// No pick: any answer is drawn, whatever feature it was computed for.
assert.equal(answersFeature(answer("a", ["a", "b"]), null), true)
assert.equal(answersFeature(answer(null, []), null), true)

// A pick takes the answer computed for it, and refuses an answer that is still for the previous pick.
assert.equal(answersFeature(answer("b", ["a", "b"]), "b"), true)
assert.equal(answersFeature(answer("a", ["a", "b"]), "b"), false)

// A pick the answer does not list never matches (the feature was removed while picked): it is keepFeature's job to drop
// it, or every answer is refused and the page sits on the loading state.
assert.equal(answersFeature(answer("a", ["a"]), "b"), false)
assert.equal(answersFeature(answer(null, []), "b"), false)

// The pick is kept while the answer still lists it (also while that answer is for the previous pick) ...
assert.equal(keepFeature(answer("a", ["a", "b"]), "b"), "b")
assert.equal(keepFeature(answer("b", ["a", "b"]), "b"), "b")
// ... and dropped once it does not, which is what lets the next request ask for the default feature.
assert.equal(keepFeature(answer("a", ["a"]), "b"), null)
assert.equal(keepFeature(answer(null, []), "b"), null)
// Nothing to compare against yet, or no pick: unchanged.
assert.equal(keepFeature(null, "b"), "b")
assert.equal(keepFeature(answer("a", ["a"]), null), null)

console.log("office feature: ok")
