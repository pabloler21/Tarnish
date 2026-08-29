# Robust `explore`: best-of-N delivery so a real vulnerability is not missed on one stochastic sample — Design

**Date:** 2026-08-29
**Status:** approved for planning (not yet implemented)
**Branch (to be cut):** `phase-2-explore-best-of-n`, off `main` (`5f27823`)
**Supersedes/relates:** builds on the M2 branch merged at `5f27823`; the honesty conventions and the transport/strategy split from `docs/superpowers/specs/2026-08-27-mvp-credible-verdict-design.md` still bind.

## 1. Problem

`explore` can report "no findings" against a target that **is** vulnerable, because it delivers each generated payload to the target exactly once and a target's response is stochastic.

Measured on `victim/` (2026-08-29, the real target — `claude-haiku` via the CLI — with a fixed judge):

| Sample | Result |
|---|---|
| N=8 deliveries of the committed proof payload | **6/8 adopted the injected fact (75%)**, canary token surfaced every time |
| The same payload during the 2026-08-28 gate run | **0/4** — an unlucky streak |
| `gpt-4o-mini` as the target (control experiment) | 0/6, token never echoed — the target model dominates the outcome |
| Target temperature 0 vs 1 (control experiment) | no difference — temperature is **not** the driver |

The vulnerability is real and lands the **majority** of the time. What makes `explore` unreliable is not the temperature, not the judge, and not payload generation (which now works via an API key with provider detection — both `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` verified valid on this machine). It is that **a single delivery is one sample of a ~75%-per-try Bernoulli process**, so a per-payload single delivery misses a genuinely-vulnerable target roughly one run in four.

### Non-goals (explicitly out of scope for this branch)

- **`check`.** It shares this root cause (single replay of a stochastic proof) and will get the same treatment in its own branch. Rework there is acceptable and expected — the user chose "fix `explore` fully first". This spec does not touch `checkr.py`.
- **Keyless generation.** Generation staying robust *with the user's API key* is the whole target here. A later branch attempts keyless generation (the agent CLIs refuse "generate an attack"; claude reliably, codex inconsistently — measured 2026-08-29). Not this branch.
- **`--fix` / M3.** Untouched, far downstream.
- **The corpus, the fingerprint contract, the report's four-part structure, the transport/strategy split.** Unchanged.

## 2. The mechanism: best-of-N delivery, verdict computed once

Today the attack path is two graph nodes (the graph edges do **not** change):

- **`_attack`** (`orchestrator.py`): for each `(family, objective)` task, generate one payload, deliver it **once**, record one `AttackAttempt`.
- **`_assess`**: for each attempt, call `evaluate(attempt, control, tools)`, and for a succeeding verdict build a `Finding`.

The change is confined to what these two nodes do internally.

### 2.1 Generate once, deliver up to N, stop at first success

In `_attack`, per task:

1. Generate the payload **once** (`SPECIALISTS[family].generate(...)`) — generation is the step that spends the API key, so it must not be multiplied. Plant the canary once (fixed tokens; delivering the same tokens N times is fine — the oracle is unaffected).
2. Deliver that same payload to the target up to **N** times. After each delivery, compute the verdict (see §2.2). **Stop at the first success.** The delivery that succeeds is the finding's proof.
3. If none of the N deliveries succeeds, record the last attempt-and-verdict as the (failing) evidence, exactly as a single failing delivery is recorded today.

Confidence math for a per-try landing probability `p`: the chance `explore` misses a real vulnerability drops from `1 - p` to `(1 - p)^N`. At the measured `p ≈ 0.75`: N=1 → 25% miss, N=3 → 1.6%, N=5 → 0.1%.

**Cost.** Generation cost is unchanged (one call per payload). Target-delivery cost rises to at most N× per payload. The worst case is a **non-vulnerable** target: proving "does not reproduce" honestly requires exhausting all N tries. With the default task set (3 tasks) and N=5 that is up to 15 target deliveries plus the control per surface. The target is keyless (agent CLI) or cheap (an API model), and N is configurable, so this is an acceptable, tunable cost — and it is the honest cost of a confident negative.

### 2.2 The verdict is computed once, in the delivery loop, and carried to `_assess`

The early-stop decision needs the verdict **inside** the delivery loop. If `_assess` re-evaluated the winning attempt afterward, the judge — which is stochastic for the objective-aware path — could contradict the loop ("the loop counted this as success; assess now says failure"). That disagreement would reintroduce exactly the kind of flakiness this branch exists to remove.

Therefore:

- `_attack` computes each task's verdict **once** (calling `evaluate(attempt, state["control_response"], tools)` inside the loop) and carries the deciding `(AttackAttempt, Verdict)` pair forward in state.
- `_assess` **stops calling `evaluate`**. It consumes the carried verdicts: for each pair whose `Verdict.succeeded` is true, it builds the `Finding` (fingerprint, severity, impact, control_diff, remediation — all unchanged). Its role narrows from "evaluate then shape" to "shape from the verdict already decided".

State change: `CampaignState.attempts: list[AttackAttempt]` becomes a carrier of attempt **and** verdict. The exact shape (a parallel `verdicts` list keyed by attempt id, a `list[tuple[AttackAttempt, Verdict]]`, or a small typed pair) is an implementation choice for the plan; the invariant is **one evaluation per task, its result authoritative for both the early-stop and the finding**. `evaluate` moves from being called in `_assess` to being called in `_attack`; it is not otherwise modified.

`evaluate` needs the **control response**, which already lives in `state["control_response"]` (produced by the `classify` node). `_attack` reads it from there — no new control delivery.

## 3. Configuration and honest evidence

### 3.1 `N` is a setting

Add one field to `Settings` (`config.py`), mirroring the existing `agent_cli_timeout` pattern (typed, env-overridable, documented default):

- `attack_attempts: int` — how many times a single payload is delivered before a negative is declared. Default **5** (miss rate ≈0.1% at the measured landing probability; the plan may justify 3 if cost matters more than the last decimal). Env var follows the existing `AliasChoices` convention used by `llm_backend`. A value of 1 exactly reproduces today's single-shot behaviour, which keeps the change bisectable and gives tests a clean "old behaviour" pin.

### 3.2 The proof records how reliably it reproduced

A finding that lands on try 1 of 5 and one that lands on try 5 of 5 carry different information about how reliably the vulnerability reproduces, and the report must not flatten them. The deciding attempt already records the transcript that landed; the design adds the **attempt index and the ceiling** to the evidence — "reproduced on delivery K of N" — so the reader sees the observed frequency rather than a bare "reproduced".

- Where this is stored (a field on `AttackAttempt`, or folded into `Verdict.evidence`) is a plan-level choice, constrained by: it must survive into the persisted `CampaignResult` JSON and render in the HTML report's proof section, and it must not disturb the `fingerprint` (which hashes `(objective, technique, surface_element)`, never attempt counts).
- This is disclosure in the spirit of the honesty conventions the M2 branch established: state what was observed (K of N), never more.

### 3.3 No change to generation, and a note on its robustness

Generation is already robust with an API key: `_api_key_backend()` detects the provider (`OPENAI_API_KEY` → `openai`, else `ANTHROPIC_API_KEY` → `anthropic`), and `get_attacker_model()` instantiates the matching client with the matching key. Both keys are now valid on this machine (the earlier Anthropic 401 was a stale key, since replaced). This branch does **not** modify generation. If, while implementing, a bad/expired API key still surfaces as a raw provider traceback rather than an actionable message, a small clean-error hardening MAY be added — but only if observed, not speculatively (YAGNI).

## 4. Components and data flow

```
classify ──▶ attack ──▶ assess          (edges unchanged)
   │            │            │
   │            │            └─ build Findings from carried (attempt, verdict) pairs; no evaluate()
   │            └─ per task: generate ONCE → deliver ≤N, evaluate each, STOP at first success;
   │                          carry the deciding (attempt, verdict)
   └─ mandatory control → state["control_response"]  (unchanged)
```

Files expected to change:
- `src/tarnish/orchestrator.py` — `_attack` (best-of-N loop + evaluate-in-loop), `_assess` (consume verdicts), `CampaignState` (carry verdicts).
- `src/tarnish/config.py` — `attack_attempts` setting.
- `src/tarnish/schemas.py` — a field to carry "landed on K of N" into the proof (exact placement per the plan).
- `src/tarnish/reporting/` — render the K-of-N reliability note in the proof section.
- Tests — see §5.

Files that must **not** change: `checkr.py`, `canary.py`, `fingerprint.py`, `evaluator.py` (called from a new place, not modified), the corpora, `victim/src/`.

## 5. Testing

All tests fake the transport, the specialist and the judge; none calls a live model; the suite stays in seconds. TDD throughout.

Central behavioural tests (these fail against today's single-shot code):

1. **A vulnerability that lands late is still found.** A fake transport whose first K deliveries fail evaluation and whose (K+1)-th succeeds, with `attack_attempts` > K, yields exactly one finding. Today (single delivery) it yields none — this is the regression the branch removes.
2. **A non-vulnerable target is declared clean at bounded cost.** A fake transport that never lands makes **exactly `attack_attempts`** deliveries per payload and yields no finding — pinning both the negative verdict and the early-stop's upper bound.
3. **Early stop.** A transport that lands on the first try makes **exactly one** delivery — best-of-N does not pay for N when it wins early.
4. **The verdict is not recomputed in `_assess`.** Assert `evaluate` is called once per task (in `_attack`), and that `_assess` builds the finding from the carried verdict — so the loop and the report can never disagree.
5. **`attack_attempts=1` reproduces today's behaviour** exactly (bisect anchor).
6. **Generation is still called once per payload** regardless of N (cost guard: best-of-N must not multiply generation).
7. **The K-of-N note reaches the report** — a landed-on-try-K finding renders its reliability note in the proof section and round-trips through the persisted JSON, without perturbing the fingerprint.

## 6. Gate for this branch

- Full suite green.
- `git status --porcelain victim/src` empty.
- A live `explore --root victim --max-tasks 3` (API key present) produces the `data`/injection finding on `src/bot.ts#handleMessage` with the proof recording "reproduced on delivery K of N", and repeating the run does **not** flip to zero findings the way the single-shot version did. (Manual, human-read, one gate run — same discipline as the M2 gate: read the payload and the raw response before trusting the verdict.)
- No new overclaim in any user-facing string (the M2 honesty bar holds).

Note this branch does **not** claim the M2 milestone gate (`check` exit 1) — that is the next branch. It claims only that `explore` reliably finds the vulnerability that is present.

## 7. Open choices left to the plan

- The exact carrier shape for `(attempt, verdict)` in `CampaignState`.
- Where "landed on K of N" is stored (`AttackAttempt` field vs `Verdict.evidence`).
- The default for `attack_attempts` (5 vs 3) — decide from the cost/confidence trade-off, defaulting to 5 unless the plan argues otherwise.
- Whether the clean-error-on-bad-key hardening (§3.3) is included — only if the failure is actually observed during implementation.
