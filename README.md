# Tarnish

Autonomous multi-agent system that red-teams an LLM-powered target through its own input
surface, judges each attack against ground truth, **proposes a fix for every finding and, once a
fix is applied, re-runs the attack to prove it closes the hole**, and exports a client-facing
report. Find -> fix -> verify. Nothing is applied through Tarnish yet, so today every fix ships
as proposed-not-verified, and the report says which it is.

Runs on the coding-agent CLI you are already logged into: no account, no telemetry. One
exception, measured 2026-08-28: *generating* the attack payloads needs an API key, because
both the `claude` and `codex` CLIs refuse that prompt on AUP grounds. The target, judge,
recon and remediation roles stay keyless.

> Working codename. The default target is **your own repository**: Tarnish reads it, reconstructs
> the agent from your system prompt and tool schemas, and attacks that. `--live` drives a headless
> browser against a deployed target instead (configured in a YAML file, never hardcoded) — that is
> how **Aurea**, a CV-evaluation agent whose only input surface is an uploaded PDF, is exercised.

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

- `rescan` (Phase 1) - apply the fix, re-run the campaign; the fingerprint diff marks it
  `not_reproducing`, and only a fix that was actually applied is reported as verified.
- `prompt_level` (Phase 2) - if the target's system prompt is exposed, apply the hardening delta
  and re-run the attack automatically.
- `harness` (repo mode, default) - attack a reconstruction of your agent built from your own
  system prompt and tool schemas; the report states the exact, scoped claim ("this attack, at this
  layer" - never "the target is patched"). Nothing of yours is booted, called or charged.

`verification: None` means **proposed, not verified**, and the report says exactly that.

## Setup

```bash
uv sync                              # create the venv, install deps + the project
uv run playwright install chromium   # one-time: headless browser (~115MB), only for --live
```

`claude` or `codex` on your PATH covers the target, judge, recon and remediation roles -
Tarnish uses the CLI you are already logged into. **Payload generation is the exception:**
both CLIs refuse to generate attack payloads (measured 2026-08-28), so `explore` needs
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in a `.env` or it will find nothing. `check` only
replays stored proofs, so it stays keyless.

Tarnish drives a headless browser to attack web targets through their real input
surface (a PDF dropzone, a chat box), so any "drop your CV" page works with no
per-target API wiring.

## Running it

Point Tarnish at your own repo. It reads the code, attacks a reconstruction of your agent, and
tells you what reproduces — without booting your app, calling your provider, or touching a file
outside `.tarnish/`.

```bash
uv run tarnish init .          # read the repo -> .tarnish/profile.json (surfaces, prompt, tools)
uv run tarnish explore         # the campaign: 3 RAG specialists -> verdict vs control -> report
uv run tarnish check           # replay what explore proved. CI exit code, instrument named per row.
```

`explore` is the fuzzer; `check` is the regression suite. `explore` is expensive and
non-deterministic — it *discovers*. `check` replays what it found, cheaply, forever, and fails the
build on anything that reproduces and has not been marked `accepted` in `baseline.json` (an
accepted finding still reproduces — you decided to live with it). It is deterministic where it can
be and says when it isn't: two oracles decide without a model, the LLM judge decides the rest, and
each row names which one ran. It delivers each proof once, so a vulnerability that only reproduces
intermittently can pass a run — treat a green `check` as "did not reproduce here", not "closed".

`init` writes `.tarnish/profile.json`; `explore` writes `.tarnish/baseline.json`. **Commit both** —
they are the gate. `.tarnish/chroma/` and `.tarnish/checkpoints.sqlite` are scratch, and `init`
writes the `.gitignore` for them itself.

### The stronger claim: `--live`

Repo mode attacks a *reconstruction* of your agent, so its claim is scoped: "this attack, at this
layer". To attack the running app through its real input surface instead — a PDF dropzone, a chat
box — drive it with the browser transport:

```bash
uv run tarnish explore --live aurea    # Playwright against the deployed target in targets/aurea.yaml
uv run tarnish gate0 --target aurea    # one benign request only, no attacks
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
