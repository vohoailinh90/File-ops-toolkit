// Behavior check for .claude/skills/bilingual/runtime/web/i18n.ts, run by
// tests/test_bilingual.py under Node's TypeScript type stripping. Exits
// non-zero on the first failed assertion.
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

import {
  createTranslator,
  detectLocale,
  formatDate,
  formatMessage,
  isLocale,
  normalizeLocale,
  type Messages,
} from "../../.claude/skills/bilingual/runtime/web/i18n.ts"

const localesDir = new URL("../../.claude/skills/bilingual/runtime/locales/", import.meta.url)
const read = (name: string): Messages => JSON.parse(readFileSync(new URL(`${name}.json`, localesDir), "utf-8"))
const catalogs = { ja: read("ja"), en: read("en") }

// locale detection
assert.equal(normalizeLocale("ja-JP"), "ja")
assert.equal(normalizeLocale("en_US"), "en")
assert.equal(normalizeLocale("fr-FR"), null)
assert.equal(normalizeLocale(""), null)
assert.equal(detectLocale(["fr", "ja-JP", "en"]), "ja", "first supported candidate wins")
assert.equal(detectLocale([null, undefined, "de"]), "en", "nothing supported -> default")
assert.equal(isLocale("ja"), true)
assert.equal(isLocale("vi"), false)

// messages
const en = createTranslator(catalogs, "en")
const ja = createTranslator(catalogs, "ja")
assert.equal(en("actions.save"), "Save")
assert.equal(ja("actions.save"), "保存")
assert.equal(ja("status.error", { message: "timeout" }), "エラーが発生しました: timeout")

// plurals: English has one/other, Japanese only other
assert.equal(en("files.processed", { count: 1 }), "Processed 1 file")
assert.equal(en("files.processed", { count: 3 }), "Processed 3 files")
assert.equal(ja("files.processed", { count: 1 }), "1 件のファイルを処理しました")

// a key missing from the active locale falls back, then shows the key itself
const partial = createTranslator({ ja: { only: { here: "日本語のみ" } }, en: { only: { en: "English only" } } }, "ja")
assert.equal(partial("only.en"), "English only")
assert.equal(partial("no.such.key"), "no.such.key")

// a plural supplied by the fallback is chosen by the fallback locale's rule
const fallbackPlural = createTranslator({ ja: {}, en: { n_one: "{count} file", n_other: "{count} files" } }, "ja")
assert.equal(fallbackPlural("n", { count: 1 }), "1 file")
assert.equal(fallbackPlural("n", { count: 2 }), "2 files")

// count is a number, as in the Python runtime; null or absent means no count
assert.throws(() => en("files.processed", { count: "1" as unknown as number }), TypeError)
assert.throws(() => en("files.processed", { count: true as unknown as number }), TypeError)
assert.equal(en("actions.save", { count: null as unknown as number }), "Save")

// names of Object members are ordinary keys, as in the Python runtime
const members = createTranslator({ ja: {}, en: JSON.parse('{"__proto__": "proto text", "constructor": "ctor text"}') }, "en")
assert.equal(members("__proto__"), "proto text")
assert.equal(members("constructor"), "ctor text")
assert.equal(en("toString"), "toString", "a missing member name degrades to the key")
assert.equal(en("constructor"), "constructor")

// placeholders: unknown names are left as written, and nothing is format-evaluated
assert.equal(formatMessage("{a} and {b}", { a: 1 }), "1 and {b}")
assert.equal(formatMessage("{constructor} {0} {", {}), "{constructor} {0} {")

// dates: the same calendar day in every zone. A Date is read as its local day,
// a "YYYY-MM-DD" string as written (new Date("2026-09-25") would be the 24th in LA).
for (const tz of ["America/Los_Angeles", "Asia/Tokyo", "UTC"]) {
  process.env.TZ = tz
  for (const day of [new Date(2026, 8, 25), "2026-09-25"]) {
    assert.equal(formatDate(day, "ja"), "2026年9月25日", tz)
    assert.equal(formatDate(day, "en"), "September 25, 2026", tz)
    assert.equal(formatDate(day, "ja", "short"), "2026/09/25", tz)
    assert.equal(formatDate(day, "en", "short"), "2026-09-25", tz)
  }
}
assert.throws(() => formatDate("2026-02-30", "en"), RangeError)
assert.throws(() => formatDate("25/09/2026", "en"), RangeError)
assert.throws(() => formatDate(new Date(Number.NaN), "en", "short"), RangeError)
// a year before 1 is refused rather than printed two ways (the long form drops the era)
for (const year of [0, -1]) {
  const early = new Date(2000, 0, 1)
  early.setFullYear(year)
  assert.throws(() => formatDate(early, "en"), RangeError, `year ${year}`)
  assert.throws(() => formatDate(early, "ja", "short"), RangeError, `year ${year}`)
}
assert.throws(() => formatDate("0000-01-01", "en"), RangeError)
assert.equal(formatDate("0001-01-01", "en", "short"), "0001-01-01")
// a five-digit year is a real Date and prints the same way in both forms, in every zone
for (const tz of ["America/Los_Angeles", "Asia/Tokyo", "UTC"]) {
  process.env.TZ = tz
  const far = new Date(10000, 0, 1)
  assert.equal(formatDate(far, "en"), "January 1, 10000", tz)
  assert.equal(formatDate(far, "en", "short"), "10000-01-01", tz)
  assert.equal(formatDate(far, "ja"), "10000年1月1日", tz)
  assert.equal(formatDate(far, "ja", "short"), "10000/01/01", tz)
}

console.log("web i18n runtime: ok")
