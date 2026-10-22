---
name: ui-kit
description: Find and reuse pre-built, MIT-licensed UI components and page patterns from the Automation UI Kit repo (vohoailinh90/Automation-UI-Kit) before hand-building new UI. Use whenever a requirement involves creating or styling a screen, component, dashboard, form, table, or admin/internal-tool interface, in this repo or any other repo the current session is working in.
---

Find and reuse UI from the Automation UI Kit:

$ARGUMENTS

Source of truth: `vohoailinh90/Automation-UI-Kit` — a private repo owned by the
user, kept as a personal catalog of free/open-source UI (shadcn/ui-style
components on Radix UI + Tailwind CSS v4 + Recharts + lucide-react). Its own
README describes it as public; treat that as aspirational — access it the
same way as any other repo in scope, via `add_repo`.

## When to use this

Any time a requirement calls for building or restyling a UI surface — a
page, a form, a data table, a dashboard, a settings screen, a nav/sidebar
layout — check this kit **before** writing a component from scratch. Building
custom UI without checking is the wrong default when a ready, MIT-licensed
equivalent already exists.

**Exception:** if the target project already has an established, non-kit
component library or design system (its own `components/ui`-equivalent,
a different primitive set, an existing theme), follow the implementer's
normal "reuse existing patterns" rule instead — do not bolt the kit's Radix
components and tokens onto a project that already has its own. Only pull
from this kit when the project has no established UI system yet, or when
the user explicitly asks to use/migrate to it.

## Procedure

1. **Get the kit into the session**, if it isn't already. `add_repo` and
   `register_repo_root` are session/orchestrator-level tools:
   - `add_repo(owner: "vohoailinh90", repo: "Automation-UI-Kit", access: "read")`
   - Clone exactly as the tool instructs (single inline clone, generous
     timeout, depth 1) — do not re-clone if a working copy from earlier in
     this session already exists at the workspace path the tool reports.
   - `register_repo_root` once the clone is confirmed.
   - **T0** (main-session-only profile, no subagents per
     `agent-routing/policy.yaml`): the main session fetches the kit and
     continues using the checkout directly — there is no handoff.
   - **T1+**: fetch the kit from the main/orchestrating session **before**
     delegating UI work to the `implementer` subagent, then pass the
     resulting local workspace path to it so it can read from it with its
     existing `Read`/`Grep`/`Glob`/`Bash` tools — the `implementer` agent's
     tool list has no `add_repo`/`register_repo_root`, and because the kit
     is a private repo, a plain `Bash git clone` from the implementer would
     not have the credentials `add_repo` sets up, so it is not a reliable
     substitute. If the implementer discovers mid-task that the kit isn't
     fetched yet, it must stop and report that back rather than attempting
     the fetch itself.
2. **Discover the current inventory from the checkout itself**, not only
   from the table below — list `src/components/ui/`,
   `src/components/dashboard/`, `src/components/`, `src/hooks/`, `src/lib/`
   and `src/pages/` in the cloned working copy. The table is a quick-reference
   starting point; the kit's `HEAD` is unpinned, so it can have gained,
   renamed, or dropped files since this table was written. Match the
   requirement against what the checkout actually contains.
3. **Copy, don't rewrite**, whatever matches:
   - Follow every copied file's `@/` imports and copy what they point to as
     well. Most files in `src/components/ui/*.tsx` need only the `cn()`
     helper in `src/lib/utils.ts`, but some build on a sibling
     (`command.tsx` → `dialog.tsx`, `toggle-group.tsx` → `toggle.tsx`,
     `dashboard/kpi-card.tsx` → `ui/card.tsx`), and the market components
     reach into `src/lib/` and `src/hooks/` (`price-chart.tsx` needs
     `lib/market.ts`, `lib/theme-tokens.ts`, `hooks/use-theme-version.ts`
     and the types and `formatCandleDate` in `lib/candles.ts`).
   - Pull the matching page from `src/pages/*.tsx` for full-screen layouts
     (dashboard/list/settings patterns), and `src/components/layout/*` for
     the sidebar/topbar shell.
   - Install the same dependencies the copied files need (see the kit's
     `package.json`: the relevant `@radix-ui/react-*` packages, plus
     `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`,
     `recharts` for charts, `@tanstack/react-table` for the data table,
     `lightweight-charts` for the price chart, and `cmdk` for the command
     palette and ticker search).
   - Bring in the CSS variable theme tokens from `src/index.css` (the
     `:root`, `.dark`, and `@theme inline` blocks) **without clobbering an
     existing theme**: if the target project's global stylesheet already
     defines some of these token names, keep its existing values and add
     only the tokens it is missing; only copy the full blocks verbatim into
     a project that has no theme tokens of its own yet. The goal is the
     copied component rendering correctly, not repainting unrelated
     existing screens.
   - For a dashboard, copy only the blocks the requirement uses from
     `src/components/dashboard/`, plus `src/components/ui/chart.tsx` only
     if it draws a Recharts chart, and `toggle.tsx` + `toggle-group.tsx`
     only for a range selector (which needs `@radix-ui/react-toggle-group`).
     Make sure the status tokens the copied blocks use (`--success`,
     `--success-fill`, `--warning`, `--info`, `--destructive`) come along.
     Text and fill colors are separate tokens on purpose — `--success`
     passes 4.5:1 as text, `--success-fill` only 3:1 as a fill, and
     `--warning` is fill-only — so don't collapse them (the kit README's
     "Màu trạng thái" has the reasons).
   - Bring `THIRD_PARTY_NOTICES.md` along with any shadcn/ui-derived file.
   - Never copy the kit's mock data: `src/lib/mock.ts`, `automation.ts`,
     `orders.ts` and `portfolio.ts` as a whole; from the other modules only
     their sample part — `generateCandles` in `candles.ts` (its types and
     `formatCandleDate` are what `price-chart.tsx` needs), the sample tasks
     in `tasks.ts`, and the `instruments` list in `market.ts` (its
     conventions and formatters are reusable); and the values shown on
     every page in `src/pages/`. All of that is illustrative only. Copy a
     page for its layout, then replace the few aggregate functions it calls
     with the target project's real data.
4. **If nothing in the kit matches**, build the new component following the
   same conventions so it stays visually consistent with anything copied
   from the kit: a Radix primitive (or plain element) wrapped with `cva()`
   variants, styled through the same CSS variable tokens, composed with
   `cn()`. Don't mix a different design system into a project that already
   uses kit components.
5. Report which files were copied from the kit (path in the kit → path in
   the target repo) plus any dependency/theme changes made, so the
   implementation report stays auditable.

## Component inventory

| File | What it is |
| --- | --- |
| `components/ui/avatar.tsx` | User/entity avatar (Radix Avatar) |
| `components/ui/badge.tsx` | Status/label pill, cva variants |
| `components/ui/button.tsx` | Button, cva variants (default/outline/ghost/destructive/…) |
| `components/ui/card.tsx` | Card shell (header/content/footer) |
| `components/ui/chart.tsx` | shadcn/ui chart wrapper for Recharts 3: `ChartContainer`, tooltip, legend; series colors come from `--color-<key>` |
| `components/ui/command.tsx` | Command palette list (cmdk) |
| `components/ui/dialog.tsx` | Modal dialog (Radix Dialog) |
| `components/ui/dropdown-menu.tsx` | Dropdown/context menu (Radix) |
| `components/ui/input.tsx` | Text input |
| `components/ui/label.tsx` | Form label |
| `components/ui/select.tsx` | Select dropdown (Radix Select) |
| `components/ui/separator.tsx` | Divider line |
| `components/ui/sheet.tsx` | Slide-in side panel (Radix Dialog variant) |
| `components/ui/switch.tsx` | On/off switch (Radix Switch) |
| `components/ui/table.tsx` | Table primitives; the scroll container becomes keyboard-focusable only while the table overflows |
| `components/ui/tabs.tsx` | Tabbed views (Radix Tabs) |
| `components/ui/toggle.tsx`, `toggle-group.tsx` | Toggle button and segmented control (Radix), e.g. a 7 / 14 / 30-day range picker |
| `components/dashboard/kpi-card.tsx` | KPI card: label, big number, change badge, trend area. Direction (arrow) and good/bad (color) are separate, so "errors went up" is red |
| `components/dashboard/tracker.tsx` | Status-page strip of day blocks (Tremor Tracker style), readable by keyboard as a `slider` |
| `components/dashboard/bar-list.tsx` | Ranked horizontal bars with labels ("top N") |
| `components/dashboard/category-bar.tsx` | Proportion bar split into segments, with a legend that carries the numbers |
| `components/dashboard/progress-ring.tsx` | Circular progress with HTML content in the middle |
| `components/dashboard/status-badge.tsx` | Colored dot + neutral text status, for colors that fail contrast as text |
| `components/stat-card.tsx` | Simpler KPI/stat card, used on the original dashboard |
| `components/data-table.tsx` | Sortable table (TanStack Table) on the `table` primitives, with `aria-sort` and per-column responsive hiding |
| `components/price-chart.tsx` | Candlestick + volume chart (Lightweight Charts) with an O/H/L/C readout |
| `components/price-change.tsx` | Percent-change badge colored by the market's price convention |
| `components/sparkline.tsx` | Tiny inline trend line, plain SVG |
| `components/ticker-search.tsx` | ⌘K search over tickers and company names |
| `components/theme-provider.tsx`, `theme-toggle.tsx` | Light/dark theme context + toggle |
| `components/layout/app-layout.tsx`, `sidebar-nav.tsx`, `nav-items.ts` | App shell: grouped sidebar + topbar layout |
| `hooks/use-theme-version.ts`, `lib/theme-tokens.ts` | Resolve CSS color tokens to sRGB for canvas charts, and re-read them on theme change |
| `lib/market.ts` | Price color conventions (`east-asian` red-up, `western` green-up) and price/volume formatters |
| `pages/dashboard.tsx` | Stat cards + progress chart (Recharts) + upcoming milestones |
| `pages/tasks.tsx` | Task/milestone table with status-tab filtering + search |
| `pages/watchlist.tsx` | Stock watchlist: sortable table, candlestick chart, ⌘K ticker search, color-convention picker |
| `pages/settings.tsx` | Profile form + config toggles |
| `pages/automation.tsx` | Dashboard template for scheduled jobs/bots: KPIs, runs per day, a 30-day tracker per job, top errors, latest runs |
| `pages/orders.tsx` | Dashboard template for multi-step orders: status mix, who each order waits on, late and due-soon orders, on-time rate |
| `pages/portfolio.tsx` | Dashboard template for a stock portfolio: value, today's and unrealised P/L, sector allocation, holdings |

## Constraints

- The kit assumes React 19 + Tailwind CSS v4 + Vite. If the target project
  uses a different stack (older Tailwind, Next.js pages router, Vue,
  vanilla HTML, an Artifact), port the *visual design and structure*
  (spacing, radii, color tokens, component composition) rather than
  copying JSX that won't compile — do not silently force a stack change
  onto a project that didn't ask for one. The kit README's "Repo không
  phải React" section has the tokens as hex values for places that can't
  read CSS variables (Plotly, ttkbootstrap, Excel), plus notes for Jinja,
  Streamlit and Tkinter.
- Price colors depend on the market: Japan, China, Korea and Taiwan read
  red as up (`east-asian`); the US, Europe, **Vietnam** and Hong Kong read
  green as up (`western`). Take the convention from `lib/market.ts` rather
  than hard-coding red or green.
- This kit is for React/web app UI. It has no bearing on Artifacts, which
  follow the `artifact-design` skill instead — don't cross the two.
- Keep the copy scoped to what the requirement needs; don't pull in the
  whole kit "just in case."
