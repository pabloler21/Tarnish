# Tarnish

Autonomous multi-agent system that red-teams an LLM-powered target through its own input
surface, judges each attack against ground truth, **proposes a fix for every finding and
proves the fix closes the hole**, traces everything in Langfuse, and exports a client-facing
report. Find -> fix -> verify.

> Working codename. Default target: **Aurea** (`bot_curriculum`), a CV-evaluation agent whose
> only input surface is an uploaded PDF. The target is configurable (a YAML file), not hardcoded.

See `PLAN.md` for the full architecture and phase plan, and `CLAUDE.md` for build conventions.

## Non-negotiables

- **`uv` only** - no pip/poetry/conda.
- **Authorization gate** - Tarnish only attacks targets the operator has proven they own.
- **Judge != target model family** - anti score-inflation.
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
uv sync                      # create the venv, install deps + the project
uv run playwright install chromium   # one-time: download the headless browser (~115MB)
cp .env.example .env         # then fill in your Langfuse keys
```

Tarnish drives a headless browser to attack web targets through their real input
surface (a PDF dropzone, a chat box), so any "drop your CV" page works with no
per-target API wiring.

## Phase 0 - foundation (current)

```bash
uv run tarnish gate0 --target aurea
```

Sends **one benign** request (a clean control CV) to the target through the transport layer and
traces it in Langfuse under the `redteam` environment. No attacks yet.

Before it can hit the real target you must, in `targets/aurea.yaml`, set the real `endpoint`
and `target_model_family`, and put your Langfuse keys in `.env`.

## Tests

```bash
uv run pytest
```
