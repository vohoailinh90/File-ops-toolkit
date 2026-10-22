---
name: bilingual
description: Make an app or tool bilingual in Japanese and English (日本語/English) — message catalogs, a language switch, and Japan-specific formatting — using the copy-ready runtimes bundled with this skill. Use whenever a requirement adds or changes user-facing text (UI labels, CLI output and --help, error messages, notifications, generated reports, exports or e-mails) in a repository created from this template, or when the user asks for something to be bilingual, 二か国語, 日英対応, song ngữ, or to add Japanese or English.
argument-hint: "[app, tool or screen to make bilingual]"
---

Make this bilingual (Japanese/English):

$ARGUMENTS

Every app or tool built from this template ships its user-facing text in
Japanese **and** English unless the requirement explicitly says otherwise.
This skill changes *how* the text is implemented, never *who* implements it:
it runs inside whatever profile the requirement already scored to, adds no
role, and is not a reason to raise any rubric dimension.

## What ships with this skill

Copy these into the app; do not re-implement them.

| File | Copy to | What it is |
|---|---|---|
| `runtime/python/i18n.py` | `<package>/i18n.py` | Stdlib-only `Translator`: dotted keys, `{name}` placeholders, `_one`/`_other` plurals, locale detection (`--lang`, `$APP_LANG`, then `$LC_ALL` / `$LC_MESSAGES` / `$LANG` as POSIX reads them, then the OS locale, Windows included), fallback, `format_date` |
| `runtime/web/i18n.ts` | `src/lib/i18n.ts` | Framework-free twin of the above for the browser (`createTranslator`, `detectLocale`, `formatDate`) |
| `runtime/web/i18n-provider.tsx` | `src/components/i18n-provider.tsx` | React `I18nProvider` / `useI18n()`, shaped like the UI kit's `ThemeProvider`; safe to render on a server (`initialLocale`), remembers an explicit choice, sets `<html lang>` |
| `runtime/web/language-toggle.tsx` | `src/components/language-toggle.tsx` | 日本語 / English switch built only from UI-kit parts; sits next to `<ThemeToggle />` |
| `runtime/locales/{ja,en}.json` | `locales/` (Python) or `src/locales/` (web) | Starter catalogs — replace the sample strings |

Both runtimes read the **same** catalog files with the same placeholder
syntax, so a tool with a CLI and a web UI keeps one pair of catalogs.

`scripts/i18n_check.py` (repository root) is the gate. It is a script, not a
review step, because "is every key in both languages with the same
placeholders" is computable — see *Deterministic work is not agent work* in
`CLAUDE.md`.

## Procedure

1. **Check for an existing i18n system first.** If the target project already
   uses one (i18next, react-intl, gettext/Babel, Qt Linguist…), follow it and
   do not bolt this runtime on beside it — the same rule the `ui-kit` skill
   applies to existing UI systems. Only its catalogs' completeness still
   matters; point `i18n_check.py` at them if they are JSON in this shape.
2. **Copy the runtime** for the stack (table above). Other stacks — Tkinter,
   Streamlit, a CLI — use the Python runtime; a non-React web page uses
   `i18n.ts` alone. For a React UI, also follow the `ui-kit` skill: put
   `<I18nProvider>` around the app next to `<ThemeProvider>` and
   `<LanguageToggle />` in the header next to `<ThemeToggle />`. With
   server rendering, pass the request's locale as `initialLocale` and
   render the same value as `<html lang>` in the layout — the provider can
   set `lang` only in the browser.
3. **Move every user-facing string into the catalogs**, writing `en.json` and
   `ja.json` in the same change — never one now and the other later.
   - Keys are dotted by feature: `report.export.done`, `errors.file_not_found`.
   - One key per whole sentence, with placeholders:
     `"{name}'s report"` / `"{name}さんのレポート"`. Never build a sentence
     by concatenating fragments — Japanese word order differs, so fragments
     cannot be reordered by a translator.
   - Counts use `key_one` / `key_other` and `t(key, count=n)`, with `n` a
     number (convert a form field's string first). Japanese has
     a single form, so its `_one` and `_other` are usually identical; the
     suffixes are reserved for plurals.
   - Language names come from `LANGUAGE_NAMES` (日本語 / English, each in
     its own language), not from the catalogs.
   - Not user-facing, so stays English and out of the catalogs: log lines
     meant for developers, code identifiers, config keys, and this template's
     own harness (`scripts/`, hooks, evals).
4. **Let the user choose the language.** CLI: a `--lang {ja,en}` flag
   (`choices=tr.locales`), falling back to `$APP_LANG`, then the first of
   `$LC_ALL`, `$LC_MESSAGES`, `$LANG` that is set — alone, as POSIX reads
   them, so `LC_ALL=C` means English — then, only if none is set, the OS
   locale.
   Desktop / Streamlit: a setting that calls `tr.set_locale()` and re-renders
   the labels. Web: `<LanguageToggle />`. Detection defaults to English when
   nothing matches; pass `default="ja"` if the audience is Japanese-first.
5. **Apply the formatting rules** below.
6. **Run the gate** and fix every error:

   ```bash
   python3 scripts/i18n_check.py                     # every locales/ dir in the repo
   python3 scripts/i18n_check.py src/locales         # or just one
   ```

   Warnings (text identical in both languages) are either fixed or named in
   the implementation report with the reason (a brand name, "PDF", "OK").
7. **Look at both languages for real**: run the tool with `APP_LANG=ja` and
   `APP_LANG=en` (or flip the toggle) and read the output. Tests that assert
   on user-facing text cover at least one path in each language.
8. **Report** which strings are uncertain translations — domain terms above
   all (設計変更 vs. 仕様変更, 見積 vs. 見積もり) — so a human can confirm
   them, rather than presenting a guess as settled.

## Japanese/English rules that bite

- **Dates**: `format_date` / `formatDate` — ja `2026年9月25日` or
  `2026/09/25`, en `September 25, 2026` or ISO `2026-09-25`. Never a
  numeric `09/25/2026` in English: US and European readers disagree on it.
  In the browser, pass a date-only value (a due date, a birthday) to
  `formatDate` as its `YYYY-MM-DD` string: `new Date("2026-09-25")` is UTC
  midnight, the 24th anywhere west of UTC. A `Date` is read as the local
  day it falls on, which is what a date picker gives.
- **Numbers and money**: both languages group with `,` and use `.` for
  decimals. JPY has **no** decimals (`¥1,235` or `1,235円`), USD has two.
  Do not convert to 万/億 unless the requirement asks.
- **Fonts**: Japanese needs a Japanese-capable font or it renders as boxes.
  Web: the kit's default system font stack reaches the OS Japanese fonts;
  add `"Noto Sans JP"` only if a design calls for one look everywhere. Tkinter on Windows: `"Yu Gothic UI"` or
  `"Meiryo UI"`. matplotlib: set `rcParams["font.family"]` to an installed
  font (`"Yu Gothic"` / `"Meiryo"` on Windows, `"Hiragino Sans"` on macOS,
  `"Noto Sans CJK JP"` on Linux) — without it every Japanese chart label is
  tofu.
- **Encoding**: read and write text as UTF-8 explicitly. CSV meant for
  Japanese Excel: `encoding="utf-8-sig"` (the BOM is what makes Excel read it
  as UTF-8); use `cp932` only when a legacy system demands Shift_JIS. A
  Python CLI whose output may be piped on Windows:
  `sys.stdout.reconfigure(encoding="utf-8")`, or run with `PYTHONUTF8=1`.
- **Layout**: the same message differs in length between the languages, in
  both directions. Do not fix widths to one language's text; let buttons,
  labels and table headers wrap or grow, and look at both. Japanese has no
  spaces, so never split on `" "` to truncate or wrap.
- **Tone**: labels and buttons are short nouns/verb stems (保存, 実行,
  エクスポート); sentences and messages are polite です/ます
  (「ファイルを保存しました」). English uses sentence case, not Title Case,
  for messages.

## Guardrails

- Do not add an i18n dependency (i18next, Babel, gettext) to a project that
  has none; the bundled runtimes cover apps and tools of this size.
- Do not machine-translate silently: you write the Japanese, and you flag
  what you are unsure of (step 8).
- Do not put HTML or markup in messages; compose it in the UI around `t()`.
- A catalog is data, not code: never `eval` it, and never pass a message to
  `str.format` (the runtimes' regex substitution exists so a stray `{` in a
  translation cannot crash the app).
