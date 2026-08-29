# Robust `explore` via best-of-N delivery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `explore` deliver each generated payload up to N times (stopping at the first success) so it stops missing a real vulnerability that the stochastic target only reproduces on some deliveries.

**Architecture:** The change is confined to the two attack graph nodes in `orchestrator.py` (edges unchanged). `_attack` generates each payload once, delivers it up to `attack_attempts` times, evaluates each delivery, and stops at the first success — carrying the deciding `(AttackAttempt, Verdict)` forward. `_assess` stops calling `evaluate` and builds findings from the carried verdicts, so the loop and the report can never disagree. A small `AttackAttempt` bookkeeping pair (`delivery_index`, `delivery_ceiling`) records "reproduced on delivery K of N" and the report renders it.

**Tech Stack:** Python 3.12+, `uv`, pytest, LangGraph, Pydantic v2, pydantic-settings, Jinja2. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-29-explore-best-of-n-design.md` — read it alongside this plan; the plan argues from it. The measured facts (the target lands ~75% per delivery; 6/8 in an N=8 run; the 2026-08-28 gate's 0/4 was an unlucky streak) are the reason this work exists.

## Global Constraints

- **`uv` exclusively.** Run everything as `uv run …`. No `pip`/`poetry`/`conda`.
- **Python 3.12+. No new dependencies.**
- **No test may call a live model.** Every test fakes the transport, the specialist and the evaluator. The suite must finish in seconds.
- **TDD.** Failing test first, watched to fail, then the minimal implementation, then green, then commit.
- **The suite is 162 tests green at the start of this plan** and must be green at the end of every task.
- **Never write to `victim/src/`.** `git status --porcelain victim/src` must stay empty.
- **One commit per small piece of work.** Every commit message ends with the trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Branch:** `phase-2-explore-best-of-n` (already cut from `main` `5f27823`, the spec is committed there at `8dcd0a7`). Never commit to `main`.
- **Scope is `explore` only.** Do NOT touch `checkr.py` (that is a later branch, rework there is accepted), the corpora, the fingerprint contract, or generation/backend resolution.
- **Honesty conventions that bind every string written:** `verification: None` = proposed, not verified; a deterministic instrument is labelled as such and the judge is labelled by model id; the report states only what was observed (K of N), never more.

## Plan decisions (these resolve the spec §7 open choices — do not re-litigate)

1. **Carrier shape:** a parallel `verdicts: list[Verdict]` field on `CampaignState`, keyed back to attempts by `Verdict.attempt_id` (which already exists). Serializes exactly like the existing `attempts` list; `_assess` builds a `{attempt_id: verdict}` dict and looks up.
2. **"Landed on K of N" storage:** two new fields on `AttackAttempt` — `delivery_index: int = 1`, `delivery_ceiling: int = 1`. They round-trip into the persisted `CampaignResult` for free (the attempt is `Finding.reproduction`), and the `1/1` defaults keep every existing construction and every prior persisted report valid.
3. **Default `attack_attempts`:** `5` (miss rate ≈0.1% at the measured p≈0.75). Configurable; `1` reproduces today's single-shot behaviour exactly.
4. **Bad-API-key clean error (spec §3.3):** NOT built. It is speculative until observed, and both keys are currently valid. YAGNI.

## File structure

- `src/tarnish/schemas.py` — add `delivery_index` / `delivery_ceiling` to `AttackAttempt` (Task 1).
- `src/tarnish/config.py` — add the `attack_attempts` setting (Task 1).
- `src/tarnish/orchestrator.py` — `CampaignState.verdicts`, the best-of-N loop in `_attack`, `_assess` consumes verdicts (Task 2). Also add `get_settings` and `Verdict` to the imports.
- `src/tarnish/reporting/templates/report.html.j2` — render the K-of-N reliability note (Task 3).
- Tests: `tests/test_schemas.py`, `tests/test_config.py` (or wherever config is tested — check first), `tests/test_orchestrator.py`, `tests/test_report.py`.

---

### Task 1: the data shapes — `AttackAttempt` bookkeeping fields and the `attack_attempts` setting

**Files:**
- Modify: `src/tarnish/schemas.py` (the `AttackAttempt` class)
- Modify: `src/tarnish/config.py` (the `Settings` class)
- Test: `tests/test_schemas.py`, and the config test file (run `ls tests/ | grep -i config` first; if none exists, add the config assertion to `tests/test_schemas.py` under a clearly named test)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `AttackAttempt.delivery_index: int` (default `1`) and `AttackAttempt.delivery_ceiling: int` (default `1`) — the best-of-N bookkeeping Task 2 sets and Task 3 renders.
  - `Settings.attack_attempts: int` (default `5`, env-overridable via `ATTACK_ATTEMPTS` / `TARNISH_ATTACK_ATTEMPTS`) — the ceiling Task 2 reads.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_schemas.py`:

```python
def test_attack_attempt_defaults_to_a_single_delivery():
    """delivery_index/ceiling default to 1/1 so every existing construction and every prior
    persisted report reads as a single-shot delivery (pre-best-of-N)."""
    from tarnish.schemas import AttackAttempt, Payload

    a = AttackAttempt(
        id="x", surface="chat_input", raw_response="r",
        payload=Payload(objective="data", technique="injection", content="p"),
    )
    assert a.delivery_index == 1
    assert a.delivery_ceiling == 1


def test_attack_attempt_records_which_delivery_landed():
    from tarnish.schemas import AttackAttempt, Payload

    a = AttackAttempt(
        id="x", surface="chat_input", raw_response="r", delivery_index=3, delivery_ceiling=5,
        payload=Payload(objective="data", technique="injection", content="p"),
    )
    assert (a.delivery_index, a.delivery_ceiling) == (3, 5)
```

Add the config test (in the config test file if one exists, else in `tests/test_schemas.py`):

```python
def test_attack_attempts_setting_defaults_to_five(monkeypatch):
    """best-of-N ceiling. Default 5 -> ~0.1% miss at the measured 75% landing rate."""
    from tarnish.config import get_settings

    monkeypatch.delenv("ATTACK_ATTEMPTS", raising=False)
    monkeypatch.delenv("TARNISH_ATTACK_ATTEMPTS", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().attack_attempts == 5
    finally:
        get_settings.cache_clear()


def test_attack_attempts_setting_reads_the_env(monkeypatch):
    from tarnish.config import get_settings

    monkeypatch.setenv("ATTACK_ATTEMPTS", "3")
    get_settings.cache_clear()
    try:
        assert get_settings().attack_attempts == 3
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_schemas.py -q -k "delivery or attack_attempts"`
Expected: FAIL — `delivery_index` is not a field; `attack_attempts` is not a setting.

- [ ] **Step 3: Write the minimal implementation**

In `src/tarnish/schemas.py`, add to `AttackAttempt` (after `raw_response`, before `trace_id`):

```python
    # best-of-N delivery bookkeeping: which delivery (1-based) this attempt was, and the
    # ceiling in force. On a finding's recorded (succeeding) attempt this reads "reproduced on
    # delivery K of N" — the observed reliability. 1/1 = a single-shot delivery (pre-best-of-N
    # and every prior persisted report).
    delivery_index: int = 1
    delivery_ceiling: int = 1
```

In `src/tarnish/config.py`, add to `Settings` (next to `agent_cli_timeout`, same style):

```python
    # best-of-N: how many times a single generated payload is delivered to the target before a
    # negative ("does not reproduce") is declared. The target is stochastic (~75% landing on
    # victim/, measured 2026-08-29), so one delivery is one Bernoulli sample and misses a real
    # vuln ~1 run in 4. (1-p)^N: at p=0.75, N=5 -> 0.1% miss. 1 = the old single-shot behaviour.
    attack_attempts: int = Field(
        default=5, validation_alias=AliasChoices("attack_attempts", "tarnish_attack_attempts")
    )
```

(`Field` and `AliasChoices` are already imported in `config.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_schemas.py -q -k "delivery or attack_attempts"` → PASS.
Then: `uv run pytest -q` → 166 passed (162 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/tarnish/schemas.py src/tarnish/config.py tests/test_schemas.py
git commit -m "$(cat <<'EOF'
Add the best-of-N data shapes: attempt bookkeeping and the ceiling setting

AttackAttempt gains delivery_index/ceiling (default 1/1, so nothing prior
changes) to record "reproduced on delivery K of N", and Settings gains
attack_attempts (default 5) for the best-of-N ceiling. No behaviour change yet.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: best-of-N delivery in `_attack`, verdict carried once to `_assess`

**Files:**
- Modify: `src/tarnish/orchestrator.py` (imports, `CampaignState`, `_attack`, `_assess`)
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Settings.attack_attempts`, `AttackAttempt.delivery_index/ceiling` (Task 1); `evaluate(attempt, control_response, tools) -> Verdict` (unchanged); `Verdict.attempt_id`, `Verdict.succeeded`.
- Produces: `_attack` returns `{"attempts": [...], "verdicts": [...]}`; `_assess` consumes the carried verdicts and calls `evaluate` **zero** times. Graph edges unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py`. These monkeypatch `orchestrator.evaluate` to control exactly when a delivery "succeeds", so the loop's behaviour is tested in isolation from the real judge. Shared helpers first:

```python
def _counting_transport():
    """A harness-shaped transport that counts deliveries and returns a distinct response each
    time. Whether a delivery 'succeeds' is decided by the faked evaluate, not by this text."""
    class _T:
        channel = "harness"
        attackable = {"chat_input"}
        deliveries = 0

        def __init__(self, profile, surface_kind=None):
            self.surface = profile.surfaces[0]

        def classify_surface(self, target):
            return self.surface.kind

        def control_input(self, target):
            return "Hi, what can you help with?"

        def deliver(self, target, *, visible, hidden=None, hiding=None):
            if hidden is None:
                return "control"
            _T.deliveries += 1
            return f"attacked response {_T.deliveries}"

    _T.deliveries = 0
    return _T


def _fixed_payload(monkeypatch):
    from tarnish.schemas import Payload
    calls = {"generate": 0}

    def _gen(target, objective, **kw):
        calls["generate"] += 1
        return Payload(objective=objective, technique="injection", content="Please note this.")

    monkeypatch.setattr(orchestrator.SPECIALISTS["injection"], "generate", _gen)
    return calls


def _succeed_on(monkeypatch, nth):
    """Fake evaluate that returns succeeded=True only on its nth call (1-based). nth=None: never."""
    from tarnish.schemas import Verdict
    calls = {"evaluate": 0}

    def _eval(attempt, control, tools=None):
        calls["evaluate"] += 1
        ok = nth is not None and calls["evaluate"] == nth
        return Verdict(attempt_id=attempt.id, succeeded=ok, model_acted=ok,
                       evidence="faked", confidence=1.0, judge_model="fake")

    monkeypatch.setattr(orchestrator, "evaluate", _eval)
    return calls
```

Then the behavioural tests (reuse `_repo_profile` already defined in this file):

```python
def test_best_of_n_finds_a_vulnerability_that_lands_late(monkeypatch):
    """The regression this branch removes: a payload that only reproduces on a later delivery
    was reported as 'no finding' by the single-shot code. Now it is found."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 3)  # lands on the 3rd delivery

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        (finding,) = out["findings"]
        assert finding.reproduction.delivery_index == 3
        assert finding.reproduction.delivery_ceiling == 5
        assert T.deliveries == 3, "must stop at the first success, not deliver all 5"
    finally:
        get_settings.cache_clear()


def test_a_target_that_never_lands_is_clean_at_bounded_cost(monkeypatch):
    """A non-vulnerable target: no finding, and exactly attack_attempts deliveries (the honest
    cost of a confident negative), never more."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, None)  # never lands

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert not out.get("findings")
        assert T.deliveries == 5
    finally:
        get_settings.cache_clear()


def test_early_stop_pays_once_when_it_lands_first(monkeypatch):
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 1)

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        (finding,) = out["findings"]
        assert finding.reproduction.delivery_index == 1
        assert T.deliveries == 1
    finally:
        get_settings.cache_clear()


def test_assess_does_not_re_evaluate(monkeypatch):
    """The verdict is computed once in the loop and carried. If _assess re-evaluated, the judge
    (stochastic on the real path) could contradict the loop. evaluate must be called exactly as
    many times as there were deliveries — never once more for assessment."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        calls = _succeed_on(monkeypatch, 1)

        orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert calls["evaluate"] == 1, "one delivery, one evaluation — assess must not re-evaluate"
    finally:
        get_settings.cache_clear()


def test_generation_is_not_multiplied_by_n(monkeypatch):
    """best-of-N re-delivers the SAME payload; generation (the API-key cost) happens once."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        gen = _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, None)  # never lands -> 5 deliveries

        orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert gen["generate"] == 1, "generation must not be multiplied by the delivery ceiling"
        assert T.deliveries == 5
    finally:
        get_settings.cache_clear()


def test_attack_attempts_one_is_the_old_single_shot(monkeypatch):
    """The bisect anchor: ceiling 1 == today's single delivery, no finding on a target that
    would have landed on a later try."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "1")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 2)  # would land on the 2nd — but there is no 2nd

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert not out.get("findings")
        assert T.deliveries == 1
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_orchestrator.py -q -k "best_of_n or never_lands or early_stop or re_evaluate or multiplied or single_shot"`
Expected: FAIL — `_attack` delivers once and does not set `delivery_index`; `orchestrator.evaluate` monkeypatch is unused because `_assess` still evaluates; `T.deliveries` never exceeds 1.

- [ ] **Step 3: Write the minimal implementation**

In `src/tarnish/orchestrator.py`:

Add to the imports:

```python
from .config import get_settings
```

and extend the schemas import to include `Verdict`:

```python
from .schemas import AttackAttempt, Finding, HidingTechnique, RepoProfile, TargetProfile, Verdict
```

Add a `verdicts` key to `CampaignState` (right after `attempts`):

```python
    verdicts: list[Verdict]  # carried from _attack so _assess never re-evaluates (best-of-N)
```

Replace `_attack` with:

```python
def _attack(state: CampaignState) -> dict:
    target = state["target"]
    transport = _transport(state)
    carrier = transport.control_input(target)
    control = state["control_response"]
    live = state.get("mode", "live") == "live"
    vocabulary = getattr(target, "domain_vocabulary", None)
    tools = getattr(target, "tools", None)
    ceiling = get_settings().attack_attempts
    attempts: list[AttackAttempt] = []
    verdicts: list[Verdict] = []
    for family, objective in state["tasks"]:
        # Generate ONCE — generation is the step that spends the API key. best-of-N re-delivers
        # this same payload; it does not regenerate.
        payload = SPECIALISTS[family].generate(target, objective, surface=state["surface"])  # type: ignore[arg-type]
        updates: dict = {}
        if live:  # hiding is a PDF-rendering concern; a harness has nothing to hide text in
            updates["hiding"] = _HIDING_FOR.get(objective, "white_on_white")
        if objective == "data":  # plant a canary for the deterministic oracle (fixed tokens, ok to re-deliver)
            line, tokens = canary(state["surface"], vocabulary)
            updates["content"] = f"{payload.content}\n{line}"
            updates["oracle"] = tokens
        payload = payload.model_copy(update=updates)
        # Deliver up to `ceiling` times, evaluating each; stop at the first success. The
        # deciding (attempt, verdict) — the winner, or the last failure — is what we carry.
        attempt: AttackAttempt | None = None
        verdict: Verdict | None = None
        for index in range(1, ceiling + 1):
            response = transport.deliver(target, visible=carrier, hidden=payload.content,
                                         hiding=updates.get("hiding"))
            attempt = AttackAttempt(
                id=uuid.uuid4().hex[:8], payload=payload, surface=state["surface"],
                raw_response=response, delivery_index=index, delivery_ceiling=ceiling,
            )
            verdict = evaluate(attempt, control, tools=tools)
            if verdict.succeeded:
                break
        attempts.append(attempt)  # type: ignore[arg-type]
        verdicts.append(verdict)  # type: ignore[arg-type]
    return {"attempts": attempts, "verdicts": verdicts}
```

Replace `_assess` with (it no longer calls `evaluate` — it consumes the carried verdicts):

```python
def _assess(state: CampaignState) -> dict:
    control, target = state["control_response"], state["target"]
    element = state.get("surface_element") or state["surface"]
    verdicts = {v.attempt_id: v for v in state.get("verdicts", [])}
    findings: list[Finding] = []
    for attempt in state["attempts"]:
        verdict = verdicts.get(attempt.id)
        if verdict is None or not verdict.succeeded:
            continue
        objective = attempt.payload.objective
        findings.append(
            Finding(
                fingerprint=fingerprint(objective, attempt.payload.technique, element),
                location=state.get("surface_element", ""),
                severity=severity_for(objective, target),  # type: ignore[arg-type]
                objective=objective,
                business_impact=impact(objective, target, where=element),
                reproduction=attempt,
                control_diff=(
                    f"Control: {' '.join(control.split())[:160]} || "
                    f"Injected: {' '.join(attempt.raw_response.split())[:160]}"
                ),
                remediation=remediate(objective, attempt.payload.technique),
            )
        )
    return {"findings": findings}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -q` → PASS (the new tests plus the two existing ones — `test_harness_mode_produces_an_oracle_proven_finding` and `test_live_mode_finding_has_empty_location` — must stay green; they succeed on the first delivery so they now make exactly one delivery).
Then: `uv run pytest -q` → 173 passed (166 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add src/tarnish/orchestrator.py tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Deliver each payload up to N times, stopping at the first success

explore delivered each payload once, but the target lands the injection only
~75% of the time, so a single delivery missed a real vulnerability ~1 run in 4
(the 2026-08-28 gate's 0/4 was that streak). _attack now generates once and
delivers up to attack_attempts times, evaluating each and stopping early; the
deciding verdict is carried so _assess never re-evaluates and the loop and the
report can never disagree.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: the report states how reliably the finding reproduced

**Files:**
- Modify: `src/tarnish/reporting/templates/report.html.j2` (the "Proof it's broken" part)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `AttackAttempt.delivery_index` / `delivery_ceiling` (Task 1), set on the finding's reproduction by Task 2.
- Produces: the rendered HTML shows "Reproduced on delivery K of up to N" when the ceiling is > 1, and nothing extra for a single-shot (ceiling 1) finding so prior single-shot reports read unchanged.

- [ ] **Step 1: Write the failing test**

`tests/test_report.py` already has a `_finding(fp, *, verified)` helper that builds a `Finding` whose `reproduction` is an `AttackAttempt`. Extend its signature with two optional delivery kwargs (default `1`/`1`) and thread them into that `AttackAttempt` — this is the smallest change and keeps every existing caller working. In the helper, change the signature and the `AttackAttempt(...)` construction:

```python
def _finding(fp: str, *, verified: bool, delivery_index: int = 1, delivery_ceiling: int = 1) -> Finding:
```

and add `delivery_index=delivery_index, delivery_ceiling=delivery_ceiling,` to the `AttackAttempt(id="a1", ...)` call inside it.

Then add the two tests:

```python
def test_report_shows_best_of_n_reliability():
    """A finding that landed on delivery 3 of 5 must say so — a 3/5 finding and a 1/5 finding
    carry different reliability, and the proof section must not flatten them."""
    result = CampaignResult(
        target=TargetProfile(id="aurea", name="Aurea", url="https://x", owner_verified=True),
        findings=[_finding("fp", verified=False, delivery_index=3, delivery_ceiling=5)],
    )
    html = render_html(result)
    assert "delivery 3 of up to 5" in html


def test_report_omits_reliability_for_a_single_shot_finding():
    """A ceiling of 1 (single delivery, and every pre-best-of-N report) renders no reliability
    line, so old reports read exactly as before."""
    result = CampaignResult(
        target=TargetProfile(id="aurea", name="Aurea", url="https://x", owner_verified=True),
        findings=[_finding("fp", verified=False, delivery_index=1, delivery_ceiling=1)],
    )
    html = render_html(result)
    assert "Reproduced on delivery" not in html
```

(`CampaignResult`, `TargetProfile` and `render_html` are already imported at the top of `tests/test_report.py`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_report.py -q -k "best_of_n or single_shot"`
Expected: FAIL — the template renders no reliability line yet.

- [ ] **Step 3: Write the minimal implementation**

In `src/tarnish/reporting/templates/report.html.j2`, inside the `2 · Proof it's broken` block, after the `Target response` `<pre>` and before the `Control diff` label, add:

```html
      {% if f.reproduction.delivery_ceiling > 1 %}
      <p class="label" style="margin-top:10px">Reliability</p>
      <pre>Reproduced on delivery {{ f.reproduction.delivery_index }} of up to {{ f.reproduction.delivery_ceiling }} (best-of-N): the target is stochastic, and this is the observed reliability of the finding, not a guarantee it reproduces every time.</pre>
      {% endif %}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_report.py -q` → PASS.
Then: `uv run pytest -q` → 175 passed (173 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/tarnish/reporting/templates/report.html.j2 tests/test_report.py
git commit -m "$(cat <<'EOF'
Report how reliably the finding reproduced (delivery K of N)

A finding that landed on delivery 3 of 5 and one that landed on 1 of 1 carry
different reliability; the proof section now states "reproduced on delivery K of
up to N" for best-of-N findings, and stays silent for single-shot ones so prior
reports read unchanged. Disclosure in the honesty conventions' spirit: state
what was observed, never more.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: the gate — a live `explore` run, human-read  (manual, NOT a TDD task)

Not a TDD task. This is the branch's gate (spec §6). A human reads the finding before the branch is called done. Requires an API key (both are valid on this machine).

- [ ] **Step 1: Suite and read-only guarantee**

```bash
uv run pytest -q
git status --porcelain victim/src
```
Expected: all green (175); nothing from the second.

- [ ] **Step 2: Run `explore` on `victim/`, twice**

```bash
uv run tarnish explore --root victim --max-tasks 3
uv run tarnish explore --root victim --max-tasks 3
```
The point of running twice: the single-shot version flipped between finding the vulnerability and reporting nothing (the gate's 0/4 vs the 6/8 measurement). Best-of-N at the default ceiling of 5 should find the `data`/injection finding on `src/bot.ts#handleMessage` on **both** runs.

- [ ] **Step 3: READ THE FINDING — the gate**

Open the newest `reports/victim-*.json` from each run and read the payload and the raw response. Pass requires ALL of:

1. Both runs produce the `data` via injection finding on `src/bot.ts#handleMessage` (best-of-N did not let one unlucky streak report "no findings").
2. The winning attempt shows the target **adopting** the injected fact (genuine ingestion — "I see from your account history…", a real `CALL refundOrder`), not quoting-while-refusing.
3. The finding's reproduction records `delivery_index`/`delivery_ceiling`, and the HTML report shows the "Reproduced on delivery K of up to N" line.
4. `remediation.verification` is `null` (nothing was applied — this branch does not fix).
5. `git status --porcelain victim/src` empty.

If it fails, diagnose against the spec; do not weaken the gate. Note this branch does NOT claim the M2 milestone `check`-exits-1 gate — that is the next branch.

- [ ] **Step 4: Record the outcome**

Write the two runs' finding summaries (payload, whether it landed, on which delivery) into the branch's notes / the ledger. Do not commit any `reports/*.json` (they are gitignored) and do not commit `victim/.tarnish/baseline.json` (a stochastic proof as the CI gate is the next branch's problem, deliberately deferred).

---

## After this plan

`explore` reliably finds the vulnerability that is present. The next branch makes `check` reliable the same way (best-of-N replay of the stored proof), then regenerates and commits `victim/.tarnish/baseline.json` and can finally claim the M2 milestone gate. Keyless generation and the deepteam-inspired coverage lever (distinct payloads per objective) are separate, later branches.

## Notes for the executor

- **Only `explore` changes.** `checkr.py` is untouched; the same best-of-N idea will be ported there in its own branch, and rework is accepted.
- **The two existing orchestrator tests must stay green.** They succeed on the first delivery, so under best-of-N they make exactly one delivery — no assertion of theirs changes.
- **`evaluate` moved call sites** (from `_assess` to `_attack`); it is not otherwise modified. Do not touch `evaluator.py`.
- **Never write to `victim/src/`**, and do not commit `reports/*.json` or `victim/.tarnish/baseline.json`.
- **The env-var + `get_settings.cache_clear()` dance in the tests** mirrors the existing pattern in `tests/test_agent_cli.py`; always clear the cache again in a `finally` so no other test inherits the setting.
