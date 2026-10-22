// React bindings for src/lib/i18n.ts, shaped like the UI kit's ThemeProvider.
// Copy to `src/components/i18n-provider.tsx`; the catalogs live in
// `src/locales/{ja,en}.json` (Vite imports JSON natively).
import * as React from "react"

import {
  createTranslator,
  DEFAULT_LOCALE,
  detectLocale,
  type Locale,
  type Translate,
} from "@/lib/i18n"
import en from "@/locales/en.json"
import ja from "@/locales/ja.json"

const catalogs = { ja, en }

const STORAGE_KEY = "app-locale"

type I18nState = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: Translate
}

const I18nContext = React.createContext<I18nState | null>(null)

// Storage can be blocked (private windows, strict site settings); the app must
// still render in a sensible language, it just won't remember the choice.
function readStoredLocale(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

// The browser's preference is external state, read through useSyncExternalStore:
// a server render never touches `navigator` or `localStorage`, hydration starts
// from the locale the server rendered, and a client-only app still paints its
// first frame in the preferred language.
function getPreferredLocale(): Locale {
  const browser = navigator.languages?.length ? navigator.languages : [navigator.language]
  return detectLocale([readStoredLocale(), ...browser])
}

function subscribeToLanguageChange(onChange: () => void) {
  window.addEventListener("languagechange", onChange)
  return () => window.removeEventListener("languagechange", onChange)
}

export function I18nProvider({
  children,
  initialLocale = DEFAULT_LOCALE,
}: {
  children: React.ReactNode
  /**
   * The locale a server render uses, e.g. from the request's Accept-Language.
   * Render the same value as `<html lang>` in the server layout: this provider
   * can set `lang` only in the browser, after hydration.
   */
  initialLocale?: Locale
}) {
  const preferred = React.useSyncExternalStore(
    subscribeToLanguageChange,
    getPreferredLocale,
    () => initialLocale,
  )
  const [chosen, setLocale] = React.useState<Locale | null>(null)
  const locale = chosen ?? preferred

  React.useEffect(() => {
    // `lang` drives screen-reader pronunciation and CJK font selection.
    document.documentElement.lang = locale
  }, [locale])

  React.useEffect(() => {
    // Only an explicit choice is remembered, so a user who never picked one
    // keeps following the browser's language.
    if (chosen === null) return
    try {
      localStorage.setItem(STORAGE_KEY, chosen)
    } catch {
      // Not persisted; the in-memory choice still applies.
    }
  }, [chosen])

  const t = React.useMemo(() => createTranslator(catalogs, locale), [locale])
  const value = React.useMemo(() => ({ locale, setLocale, t }), [locale, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = React.useContext(I18nContext)
  if (!context) throw new Error("useI18n must be used within an I18nProvider")
  return context
}
