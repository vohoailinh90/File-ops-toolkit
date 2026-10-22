---
name: classify-requirement
description: Classify a software requirement into the repository's T0-T3 execution profile using the scoring rubric and deterministic routing policy. Use before choosing subagents for non-trivial engineering work.
argument-hint: "[requirement text]"
---

Classify this requirement:

$ARGUMENTS

Use `agent-routing/complexity-rubric.md` and `agent-routing/policy.yaml` as the source of truth.

## Procedure

1. Parse the requirement semantically.
2. If repository context exists and the requirement refers to existing code, inspect only enough context to avoid a clearly wrong score.
3. Score each dimension from 0 to 2:
   - ambiguity
   - scope
   - architecture
   - dependencies
   - risk
   - verification
4. Sum the raw score (0-12). The resolver in step 7 recomputes it; a mismatch means a dimension was misread.
5. Extract routing signals as **actions the change performs**, using the verb-first vocabulary in `signal_taxonomy`. Ask "what does this change do?", not "what does this requirement mention?". A requirement that reads a payment record is not a payment change.
6. Drop any signal listed in `signal_taxonomy.read_only_exempt` before override matching. Read-only access to a sensitive domain never raises a tier — if it genuinely adds risk, that belongs in the risk or verification score, where it can be weighed.
7. Resolve the policy with the resolver, never by hand:

   ```bash
   python3 scripts/route.py --dimensions <ambiguity>,<scope>,<architecture>,<dependencies>,<risk>,<verification> \
       --signals <signal>,<signal>
   ```

   It drops read-only signals, applies every matching override (a tier can only rise), selects the profile, fires each `conditional_agents` arm independently (OR across entries, never AND), and adds a classification-time reserve such as `analyst_reserve` to the base ceiling when its condition holds. It never adds `escalation_reserve`: that is granted only after a reviewer formally escalates mid-review. Copy `raw_score`, `score_tier`, `signals`, `overrides_applied`, `final_tier`, `strategy`, `required_agents`, `max_agent_invocations` and `human_gate` from its output verbatim. If it reports `unknown_signals`, your vocabulary drifted from `signal_taxonomy`: rename the signal or drop it, then re-run.
8. Only if the script cannot run (no Python, no PyYAML): apply step 7's rules from `agent-routing/policy.yaml` by hand, say so in `rationale`, and expect the eval to check your route with `scripts/route.py --check`.
9. When this classification is for a requirement the session will now execute (not an eval), re-run the same command with `--record --requirement <id>` so the `PreToolUse` hook enforces the ceiling on every subagent spawn (`docs/agent-budget.md`).
10. Decide whether parallel execution has real value. Do not equate T3 with automatic parallelism, and remember that parallelism never raises the agent budget.

## Output format

Return exactly one YAML block with this shape:

```yaml
requirement_summary: "..."
classification:
  ambiguity: 0
  scope: 0
  architecture: 0
  dependencies: 0
  risk: 0
  verification: 0
raw_score: 0
signals: []
score_tier: T0
overrides_applied: []
final_tier: T0
strategy: main_session
required_agents: []
max_agent_invocations: 0
parallelizable: false
human_gate:
  required: false
  reason: null
rationale:
  - "..."
```

## Guardrails

- Do not inflate scores because the requirement uses sophisticated terminology.
- Do not lower risk because the code change is small.
- Unknowns that can materially alter design increase ambiguity.
- Signals must be verb-first actions. `authentication` is not a signal; `changes-authentication-flow` and `reads-authenticated-context` are, and only the first one can raise a tier.
- Security/payment/data-loss/irreversible **actions** must be passed to policy overrides. Mere proximity to those domains must not.
- When uncertain between adjacent scores, choose the lower score unless concrete evidence supports the higher one; overrides exist to protect high-risk domains.
- `required_agents` is the floor and `max_agent_invocations` is the ceiling. Never emit more required agents than the budget allows.
- Do not add a role for work that is deterministic. If the verification is counting, hashing, or conformance checking, the answer is a script, not an agent.
- Never pick an execution lane. Whether Codex executes the tier (`--lane codex`, `docs/codex-lane.md`) is the operator's choice after classification, and it never changes the tier, an override or a reserve.
