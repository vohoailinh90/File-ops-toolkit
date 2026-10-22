# File Ops Toolkit

Local tool (Python 3.10+ backend, React web UI) that reads an Excel list and copies files from
server folders to a folder the user picks.

- Input: an `.xlsx`; row 1 is the header; from row 2, **column A** is the folder (a UNC share such
  as `\\server\share\...`, a drive path, or a `file:` link — text, hyperlink or `=HYPERLINK()`),
  **column B** is the file name.
- For each row the tool opens the folder (sub-folders too, unless turned off), finds every file with
  that name (a name without extension matches any extension) and copies all of them to the destination.
- Runs on the user's Windows PC, because that is where the share is reachable. `python app.py` opens the UI;
  `python app.py run LIST.xlsx DEST` runs without it.

## Hard rules

These are product invariants. Changing one is a T3 change that needs the owner's explicit approval.

- **Never modify or delete anything on the source share.** The source is only read.
- **Never overwrite a file in the destination.** An identical earlier copy is reported; a different file
  with the same name gets ` (2)`, ` (3)`… (`copier.py`).
- **Column B is untrusted.** A name with a path separator is rejected; matching is by string equality,
  never by wildcard or path join.
- **The local API can write to disk**: it binds to 127.0.0.1 only, needs the per-launch token and checks
  the Host header (`server.py`). Do not add CORS, a public bind or an unauthenticated endpoint.
- Web links (SharePoint, Google Drive) are not supported; such a row gets the status
  `unsupported_link` rather than a silent skip. Adding a provider is a new requirement.

## Routing

This repository carries the agent-routing harness (the "agent team"):

- Policy: `agent-routing/policy.yaml`; rubric: `agent-routing/complexity-rubric.md`;
  classifier: `.claude/skills/classify-requirement/SKILL.md`; roster: `.claude/agents/`.
- For any non-trivial change: score the six dimensions, extract signals as *actions the change performs*,
  run `python3 scripts/route.py --dimensions a,b,c,d,e,f --signals ...` (never apply overrides by hand),
  run it again with `--record --requirement <id>` when the session will execute it, stay inside
  `max_agent_invocations`, and verify independently before declaring success.
- T0 main session only. T1 main implements, `code-reviewer` verifies. T2 adds `architect` only when
  architecture scores 2 or a contract signal fires. T3 adds `architecture-critic` and `code-reviewer-t3`.
  The main session implements at every tier. Plans and reviews go in `artifacts/` (line caps in policy).
- Settings: `.claude/settings.json` enables the agent-budget hook, the session-budget hooks and the status
  line (`docs/agent-budget.md`, `docs/session-budget.md`).
- If a computable check exists, write it as a script or test, not as a reviewer's job.
  `tests/mutations/*.yaml` hold the mutations each test must catch; add one when you ship a fix with a test.
  A replacement that keeps the file's byte length can reuse a stale `.pyc` within the same second, so make
  the replacement a different length.

## Conventions

- **UI** comes from `vohoailinh90/Automation-UI-Kit` (`.claude/skills/ui-kit/SKILL.md`): copy a matching
  component into `web/src/components/ui/` before writing one. React 19 + Tailwind v4 + Radix.
- **Bilingual**: every user-facing string lives in `file_ops_toolkit/locales/{ja,en,vi}.json` (one set for
  the Python side and the web UI) and all three change in the same commit. `ja` and `en` are required by
  the template; `vi` is the owner's working language. `python3 scripts/i18n_check.py` is the verdict.
  Server errors travel as catalog codes (`errors.*`, `status.*`), never as sentences.
- **Layout**: root holds only entry points and config; the package is `file_ops_toolkit/`, tests are in
  `tests/`, the UI in `web/`. `python3 scripts/layout_check.py` is the verdict.

## Commands

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                                   # unit + server tests
python3 scripts/mutation_check.py --all  # every named test must fail when its behavior is removed
python3 scripts/i18n_check.py && python3 scripts/layout_check.py
cd web && npm ci && npm run typecheck && npm run lint && npm run build
```
