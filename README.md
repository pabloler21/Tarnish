# Tarnish

Autonomous multi-agent system that red-teams an LLM-powered target through its own input
surface, judges each attack against ground truth, **proposes a fix for every finding and
proves the fix closes the hole**, and exports a client-facing report. Find -> fix -> verify.
Runs on the coding-agent CLI you are already logged into: no API key, no account, no telemetry.

> Working codename. Default target: **Aurea** (`bot_curriculum`), a CV-evaluation agent whose
> only input surface is an uploaded PDF. The target is configurable (a YAML file), not hardcoded.

See `PLAN.md` for the full architecture and phase plan, and `CLAUDE.md` for build conventions.

## Non-negotiables

- **`uv` only** - no pip/poetry/conda.
- **Authorization gate** - Tarnish only attacks targets the operator has proven they own.
- **Falsifiability comes from the mandatory control**, not from knowing the target's model.
  Operators paste a URL and don't know what model runs behind it, so Tarnish never asks.
- **No finding without a proposed fix; no fix presented as verified without a re-run** - the
  same falsifiability discipline as the attack side.

## How each finding is verified

A proposed fix is worthless unless it can be shown to close the specific finding. Three modes,
built cheapest-and-most-honest first:

- `rescan` (Phase 1) - apply the fix, re-run the campaign, the fingerprint diff marks it `fixed`.
- `prompt_level` (Phase 2) - if the target's system prompt is exposed, apply the hardening delta
  and re-run the attack automatically.
- `harness` (Phase 3) - apply the mitigation as a local wrapper; the report states the exact,
  scoped claim ("this mitigation, at this layer, blocks this attack" - not "the target is patched").

`verification: None` means **proposed, not verified**, and the report says exactly that.

## Setup

```bash
uv sync                              # create the venv, install deps + the project
uv run playwright install chromium   # one-time: headless browser (~115MB), only for --live
```

No API key needed if you have `claude` or `codex` on your PATH - Tarnish uses the coding-agent
CLI you are already logged into. Otherwise put `OPENAI_API_KEY` in a `.env`.

Tarnish drives a headless browser to attack web targets through their real input
surface (a PDF dropzone, a chat box), so any "drop your CV" page works with no
per-target API wiring.

## Running a campaign

```bash
uv run tarnish run --target aurea         # control + attacks -> evaluate -> remediate -> report
uv run tarnish gate0 --target aurea       # one benign request only, no attacks
```

Findings land in `reports/<target>-<timestamp>.json` with an HTML report beside them.

## Optional: tracing

Tarnish runs with tracing off. A trace holds your system prompt, the payloads that worked and
your unfixed vulnerabilities - a dossier on how to attack you - so it stays local unless you
ask otherwise. To enable it, set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`; point
`LANGFUSE_HOST` at Langfuse Cloud or your own instance (the core is MIT and self-hostable).
The report itself never depends on Langfuse - it renders from the campaign JSON.

## Tests

```bash
uv run pytest
```
