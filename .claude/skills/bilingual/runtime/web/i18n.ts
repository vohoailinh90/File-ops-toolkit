// Japanese/English runtime for web apps. Framework-free, no dependencies.
//
// Copy to `src/lib/i18n.ts`. The catalogs are the same `locales/<locale>.json`
// files the Python runtime reads, and `{name}` placeholders use the same
// pattern, so one pair of catalogs serves a tool's CLI and its web UI, and
// `scripts/i18n_check.py` checks both.

export const LOCALES = ["ja", "en"] as const
export type Locale = (typeof LOCALES)[number]

export const DEFAULT_LOCALE: Locale = "en"
export const FALLBACK_LOCALE: Locale = "en"

// Endonyms: each language named in itself, identical in every catalog, so they
// live in code rather than in a catalog a translator could "translate".
export const LANGUAGE_NAMES: Record<Locale, string> = { ja: "日本語", en: "English" }

export type Messages = { [key: string]: string | Messages }
// `count` selects the plural form, so it is a number: a string from a form
// control has to be converted by the caller, as the Python runtime requires too.
export type Params = { count?: number } & Record<string, string | number>
export type Translate = (key: string, params?: Params) => string

const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value)
}

/** "ja-JP" -> "ja", "en_US" -> "en", anything unsupported -> null. */
export function normalizeLocale(tag: string | null | undefined): Locale | null {
  if (!tag) return null
  const base = tag.trim().split(/[-_.@]/, 1)[0].toLowerCase()
  return isLocale(base) ? base : null
}

/** First supported locale among the candidates (saved choice, then navigator.languages). */
export function detectLocale(
  candidates: readonly (string | null | undefined)[],
  fallback: Locale = DEFAULT_LOCALE,
): Locale {
  for (const candidate of candidates) {
    const found = normalizeLocale(candidate)
    if (found) return found
  }
  return fallback
}

/**
 * {"a": {"b": "x"}} -> {"a.b": "x"}, into a map with no prototype, so a key
 * named `constructor` or `__proto__` is an ordinary key, as it is in Python,
 * and a missing one is undefined rather than an inherited Object member.
 */
export function flatten(messages: Messages, prefix = "", out: Record<string, string> = Object.create(null)) {
  for (const [key, value] of Object.entries(messages)) {
    const path = `${prefix}${key}`
    if (typeof value === "string") out[path] = value
    else flatten(value, `${path}.`, out)
  }
  return out
}

/** Replace each `{name}` with params[name]; an unknown name is left as written. */
export function formatMessage(template: string, params: Params = {}): string {
  return template.replace(PLACEHOLDER, (match, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : match,
  )
}

/**
 * A translate function for one locale. With `params.count`, `key_one` /
 * `key_other` is chosen by the CLDR plural rule of the locale whose catalog
 * supplies the message, so an English fallback says "1 file", not "1 files".
 * A missing key falls back to the fallback locale, then to the key itself, so
 * a gap shows on screen instead of throwing in front of a user.
 */
export function createTranslator(
  catalogs: Record<Locale, Messages>,
  locale: Locale,
  fallback: Locale = FALLBACK_LOCALE,
): Translate {
  const sources = [...new Set([locale, fallback])].map((name) => ({
    messages: flatten(catalogs[name]),
    plural: new Intl.PluralRules(name),
  }))
  const lookup = (key: string) => sources.map(({ messages }) => messages[key]).find((m) => m !== undefined)

  return (key, params = {}) => {
    let message: string | undefined
    const count: unknown = params.count
    if (count != null) {
      // The type already says number; this keeps untyped callers in step with
      // the Python runtime, which raises TypeError too.
      if (typeof count !== "number") throw new TypeError(`count must be a number, not ${typeof count}`)
      for (const { messages, plural } of sources) {
        message = messages[`${key}_${plural.select(count)}`] ?? messages[`${key}_other`]
        if (message !== undefined) break
      }
    }
    return formatMessage(message ?? lookup(key) ?? key, params)
  }
}

/**
 * A calendar date as each audience writes it, the same in every time zone.
 * long:  ja 2026年9月25日   en September 25, 2026
 * short: ja 2026/09/25      en 2026-09-25 (ISO: 09/25 vs 25/09 is ambiguous across US and EU readers)
 *
 * `value` is a `Date`, read as the local day it falls on (what a date picker
 * gives), or a date-only `"YYYY-MM-DD"` string, read as written. Pass a
 * date-only value from an API as the string: `new Date("2026-09-25")` is UTC
 * midnight, which is September 24 anywhere west of UTC.
 */
export function formatDate(value: Date | string, locale: Locale, style: "long" | "short" = "long"): string {
  const [y, m, d] = typeof value === "string" ? isoDateParts(value) : localDateParts(value)
  // The long form drops the era, so year 0 (1 BC) would print as "January 1, 1"
  // beside a short "0000-01-01", and year -1 as "January 1, 2". Python's date()
  // refuses them too. Five-digit years print the same way in both forms, so
  // only the lower bound is enforced.
  if (y < 1) throw new RangeError(`year ${y} is before year 1`)
  if (style === "long") {
    // Formatted at UTC from the parts, so no zone can move the day.
    const format = new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "en-US", { dateStyle: "long", timeZone: "UTC" })
    return format.format(utcMidnight(y, m, d))
  }
  const pad = (n: number, width = 2) => String(n).padStart(width, "0")
  return locale === "ja" ? `${pad(y, 4)}/${pad(m)}/${pad(d)}` : `${pad(y, 4)}-${pad(m)}-${pad(d)}`
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/

/** "2026-09-25" -> [2026, 9, 25]; anything else, or a day that does not exist, throws like Python's `date()`. */
function isoDateParts(value: string): [number, number, number] {
  const match = ISO_DATE.exec(value)
  if (match) {
    const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
    const day = utcMidnight(y, m, d)
    if (day.getUTCFullYear() === y && day.getUTCMonth() === m - 1 && day.getUTCDate() === d) return [y, m, d]
  }
  throw new RangeError(`not a YYYY-MM-DD calendar date: ${JSON.stringify(value)}`)
}

function localDateParts(value: Date): [number, number, number] {
  if (Number.isNaN(value.getTime())) throw new RangeError("invalid Date")
  return [value.getFullYear(), value.getMonth() + 1, value.getDate()]
}

/** Midnight UTC of a calendar day. Unlike Date.UTC, setUTCFullYear does not read years 0-99 as 1900-1999. */
function utcMidnight(y: number, m: number, d: number): Date {
  const day = new Date(0)
  day.setUTCFullYear(y, m - 1, d)
  return day
}
