<!--
Fill every section; write "n/a" with a reason rather than deleting one. This text is the PR
description, so it describes the change and nothing about who reviews it.
-->

## Summary

<!-- What changes and why, in two or three sentences. Link the issue or requirement. -->

## Routing

- Requirement id:
- Execution profile: <!-- T0 | T1 | T2 | T3, from `scripts/route.py` (raw_score, final_tier) -->
- Overrides applied: <!-- none, or the override names -->
- Agent budget: <!-- base used / base ceiling; reserves used, reported separately -->
- Artifacts: <!-- T2/T3: paths under `artifacts/` (plan, critique, review); otherwise "none" -->

## Changes

<!-- One bullet per behavior that changed, not per file. -->

-

## Verification

<!-- Tick what you ran and paste the result; "n/a" and a reason for the rest. -->

- [ ] Tests: `<command>` — result
- [ ] Lint and type checks the repository runs — result
- [ ] `python3 scripts/layout_check.py` — a Python file, test or module was added or moved
- [ ] `python3 scripts/i18n_check.py` — user-facing text changed (`locales/ja.json` and `locales/en.json` together)
- [ ] `python3 scripts/mutation_check.py --all` — a fix ships with a test and its `tests/mutations/` entry
- [ ] Independent review the tier requires, if the route spawns one (T1 and T2 `code-reviewer`, T3 `code-reviewer-t3`) — ran, or n/a with the reason; the verdict lives in `artifacts/reviews/` and on the PR's threads, not here
- [ ] T3: integration / migration / security verification and the rollback consideration — evidence

Acceptance criteria, each with its evidence:

-

## Risk and rollback

<!-- What breaks if this is wrong, who notices, and how it is undone. "Revert this PR" counts only if it is true. -->

## Unresolved issues

<!-- "none", or each open question and who has to decide it. -->
