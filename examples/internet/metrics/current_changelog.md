# Changelog — internet example instrumentation/debugging changes

Tracks actual code changes made while investigating the findings in
`findings.md`. See that file for the analysis/root-cause writeup — this
file is just "what changed and why."

## metrics/readable_log.py — show agents with zero movement

`build_timeline()` now unions agent ids from both the position log and the
loaded DB profiles (`sorted(set(by_agent) | set(profiles))`) instead of
only agents that appear in `position_logs.jsonl`. Agents with no position
entries print a `[NO MOVEMENT]` flag in their header (`0 moves 0m total`).

Why: previously agents that never moved were silently absent from the
readable output, hiding that 45/100 agents in the run never moved at all.
This surfaced findings #2 and #4 in `findings.md`.

Note: the full 100-agent roster only appears when a `sqlite.db` is found
(profiles loaded). Without a DB it falls back to movement-only agents.

## internetagent.py — capture satisfaction snapshot per tick

`InternetAgent.__init__`: added `self._pre_tick_satisfaction`, populated
each tick.

`InternetAgent.forward()`: right before calling `super().forward()`,
snapshots `hunger_satisfaction` / `energy_satisfaction` /
`safety_satisfaction` / `social_satisfaction` / `current_need` into
`self._pre_tick_satisfaction`. This captures the state *before*
`needs_block`'s time-decay and LLM `evaluate_and_adjust_needs()` run
inside `super().forward()`.

`InternetAgent.plan_generation()`: when a fresh plan is generated
(`cognition is not None`), also reads the *post*-tick satisfaction values
(needs_block already ran earlier this same tick) and passes both
snapshots to `log_plan_generated(...)`.

Why: we had no way to see the actual `*_satisfaction` float values or how
much the LLM's `evaluate_and_adjust_needs` evaluation moved them —
`agent_status` in `sqlite.db` only stores per-step thought text, not the
underlying numbers. This was the direct blocker to investigating *why*
the LLM keeps re-triggering the same need (finding #1's root cause writeup
in `findings.md`).

## utils/plan_logger.py — log satisfaction before/after each plan

`log_plan_generated()` gained two optional params: `satisfaction_before`,
`satisfaction_after` (each a dict with the four `*_satisfaction` keys,
`satisfaction_before` may also carry `current_need`). Each `plan_logs.jsonl`
entry now additionally includes:

- `need_before` — the need active going into this tick's evaluation
- `satisfaction_before` / `satisfaction_after` — the four values pre/post
- `satisfaction_delta` — per-key `after - before`, rounded to 4 decimals

Old log entries (and calls without these params) are unaffected —
all new fields default to `None`.

## metrics/readable_plan_log.py — render the satisfaction delta

`_format_plan()` now prints a `satisfaction: hunger 0.70->0.68 (-0.02)  ...`
line under each plan when the new fields are present, and flags
`[SAME NEED REPEATED]` next to the plan header when `need_before == need`
(the exact signature of finding #1's loop). Falls back cleanly (no extra
line) on logs that predate this change.

## What this unblocks

The next simulation run will produce `plan_logs.jsonl` entries with real
satisfaction numbers, so we can finally check empirically whether:
- the LLM's post-plan evaluation genuinely stays near/below threshold
  (confirming finding #1's hypothesis), or
- satisfaction does cross the threshold but something else re-triggers
  the same need anyway (a different bug than hypothesized).

No changes were made to the vendored framework
(`packages/agentsociety/agentsociety/`) — everything above is local to
`examples/internet/`.

## Agent count: 100 -> 20

`internet.py`: `number=100` -> `number=20`, plus renamed the experiment
name (`"control group - 20 agents full day"`) and metrics output dir
(`metrics/output/20_agent_fullday_controll`) to match. Both bugs in
`findings.md` are per-agent, not emergent multi-agent effects (a single
agent in isolation reproduced the worst loop), so a much smaller run is
enough to iterate on fixes and burns far less LLM budget. Occupation-level
population patterns (finding #4) need the full ~100-agent count back for a
final validation run.

## 20-agent run confirms + quantifies the bugs (see findings.md's addendum)

Ran with the new satisfaction logging. `plan_logger.py` and
`device_logger.py`/`antennas.py` all open their log files in **append**
mode and never clear between runs, so `plan_logs.jsonl` / `position_logs.jsonl`
now contain multiple runs mixed together — had to filter by the
`timestamp` field (wall-clock, ISO) against the run's `as_experiment.created_at`
to isolate the latest run's rows. Worth fixing (e.g. name log files by
experiment id, or clear at start of `internet.py`'s `main()`) if this
becomes a recurring annoyance — not done yet, flagged here instead.

## Fixes for findings #1–#3 (NOT the cooldown suggestion — explicitly skipped per user)

All four changes below are local to `examples/internet/`; nothing in
`packages/agentsociety/agentsociety/` was touched. None of them add a
cooldown/backoff before the same need can re-trigger a plan — that was
deliberately rejected ("sometimes I can still be hungry after eating and
decide to eat a second portion, that's alright").

### utils/needs_block_custom.py — `TimeAwareNeedsBlock` (fixes #1's root cause)

Subclasses the vendored `NeedsBlock`, overriding only
`evaluate_and_adjust_needs()`. Adds to the LLM evaluation prompt:
- each step's actual `consumed_time` inline in the evaluation text
- the current sim time and total minutes spent executing the plan
- explicit instruction to weight time spent over step "success" text,
  with rough benchmarks (a full night's sleep is 360-540 min, a real meal
  15-40 min, a real conversation 15+ min)

Wired in via `internetagent.py`: right after `super().__init__()` (which
already builds the vendored `self.needs_block`), it's replaced with a
`TimeAwareNeedsBlock` instance — there's no `agent_params` field for this
prompt like there is for `plan_generation_prompt`/`block_dispatch_prompt`,
so a config-level override wasn't possible; this is the smallest change
that avoids touching vendored code.

### utils/mobility_block_custom.py — `MobilityBlock` (fixes #2)

Subclasses the vendored `MobilityBlock` (same class name preserved via
import-alias trick, so the top-level block dispatcher's lookup key stays
`"mobilityblock"` — see the module docstring). Overrides `forward()` to
always run `PlaceSelectionBlock` immediately followed by `MoveBlock` in
the same call, instead of letting the per-tick LLM dispatcher pick only
one. This closes the gap where a `[mobility]` step could be marked
complete having only chosen a destination, with `environment.set_aoi_schedules`
never called.

Wired in via `internet.py`'s `blocks={}` dict, replacing `MobilityBlock`
with `ReliableMobilityBlock` (import alias for this class).

### utils/other_block_custom.py — `OtherBlock` / `OtherNoneBlock` (mitigates #1's fast-completion driver)

`OtherNoneBlock` handles most `[other]`-typed step duration estimates
(prep steps like "Check social media", "Prepare for sleep" before the
single "Sleep" step). Adds current sim time to the duration-estimate
prompt (previously intention-text-only, with a `random.randint(1, 180)`
fallback on parse failure — both blind to time of day). `OtherBlock` is a
thin wrapper that swaps in this new `OtherNoneBlock` and re-registers it
with its internal dispatcher (same class-name-preservation trick).

Wired in via `internet.py`'s `blocks={}` dict, replacing `OtherBlock` with
`TimeAwareOtherBlock` (import alias).

### utils/prompts.py — plan-generation + sleep-duration prompt tweaks (fixes #3)

- `CUSTOM_DETAILED_PLAN_PROMPT`'s "General rhythm" section: added an
  explicit circadian-rhythm line ("real sleep belongs at night... prefer a
  short rest/break over a full sleep plan" during the day), a one-line
  mention of work anchoring the day, and loosened the previously-fixed
  mealtime clock times (07:30/13:00/19:00) to "loosely around
  breakfast/lunch/dinner."
- New `TIME_AWARE_SLEEP_PROMPT` constant: adds `${status.current_day_info}`
  to the sleep-duration estimate prompt (this one *is* exposed via
  `OtherBlockParams(sleep_time_estimation_prompt=...)`, so no subclassing
  needed) — night sleep now estimates a real 360-540 min night, daytime
  sleep estimates a short 15-90 min rest instead of a random guess.

Wired in via `internet.py`: `OtherBlockParams(sleep_time_estimation_prompt=TIME_AWARE_SLEEP_PROMPT)`.

### Verification

`python3 -m py_compile` on all changed/new files, plus `import internet`
end-to-end (builds the full `Config` object, including constructing the
`blocks={}` dict with the new classes) — both succeeded. Not yet verified
against a live simulation run (needs LLM API access); that's the natural
next step.

## Attribute satisfaction delta to the plan that actually caused it

Found via manual inspection of a "Sleep at home" row that showed
`hunger 0.00->1.00 (+1.00)` — the sleep plan didn't cause that; an "Eat at
home" plan that had been running since two hours earlier finished in the
same tick, got evaluated (need=hungry), and the *next* need selected
(tired, since energy was already at 0) triggered the sleep plan being
logged — all in one tick. The old design logged satisfaction at
plan-*generation* time, but `evaluate_and_adjust_needs()` (which produces
the delta) always evaluates the *previous* plan, earlier in the same tick,
before a new plan gets generated for whichever need is selected next. So
the delta shown was consistently one plan off from the plan it was printed
next to.

Fix: moved logging from generation-time to completion-time.

- `internetagent.py` `plan_generation()`: no longer calls the logger.
  Instead, when a fresh plan is generated, stashes
  `_sim_time_at_start` / `_emotion_at_start` / `_satisfaction_at_start`
  (using the existing `self._pre_tick_satisfaction` snapshot) directly onto
  the `current_plan` dict and writes it back to memory. These extra keys
  ride along in `current_plan` across ticks (the framework only mutates
  specific keys like `steps`/`index`/`completed`, never reconstructs the
  dict), so they're still there whenever the plan eventually completes.
- `utils/needs_block_custom.py` `TimeAwareNeedsBlock.evaluate_and_adjust_needs()`:
  now calls `log_plan_generated(...)` itself, after the LLM evaluation
  completes (success or exhausted retries), using `completed_plan`'s own
  `target`/`steps` and the stashed start-of-plan context as
  `satisfaction_before`/`emotion`/`sim_time`, and the just-updated memory
  values as `satisfaction_after`. This fires from both places the vendored
  `evaluate_and_adjust_needs` gets called (normal completion via
  `update_when_plan_completed`, and interruption via
  `determine_current_need`'s needs-changed branch) since both call
  `self.evaluate_and_adjust_needs(...)`, which resolves to our override.

Net effect: one row per plan (`sim_time` = when it started, as before),
but the satisfaction delta shown is now genuinely that plan's own
before/after, not the previous plan's.

**Trade-off**: a plan that's still running when the simulation ends never
gets logged (there's no completion event to trigger it) — previously it
would have shown up with no satisfaction data. Acceptable for a full-day
run where the last plan of the day is a small fraction of the timeline.

**The existing `plan_logs.jsonl` (509 entries, cleaned earlier this
session) was produced by the OLD generation-time logging — its
satisfaction deltas are the misattributed kind described above. A fresh
run is needed to get correctly-attributed data.**

## Schema-constrained satisfaction evaluation (replaces free-form JSON + retry/repair)

Investigating a specific log line (`energy 0.00->0.00` after a 7-hour
sleep plan) surfaced a second, more concrete bug sitting underneath the
duration-blindness one: the vendored `evaluate_and_adjust_needs` asks the
LLM to name which JSON key it's updating (e.g. `hunger_satisfaction` for
the `hungry` need), but only ever demonstrates one example mapping
(`hungry` -> `hunger_satisfaction`). `tired` -> `energy_satisfaction` has
no lexical overlap and is never shown. If the model returns any other key
spelling, `if need_type in (...)` silently drops it — no warning, no log,
indistinguishable from "the LLM chose not to change it."

Fix: `utils/needs_block_custom.py`'s `evaluate_and_adjust_needs` now calls
`self.llm.atext_request(..., extra_body={"guided_json": SATISFACTION_SCHEMA})`
— vLLM constrained generation, confirmed supported by the framework itself
(`agentsociety/llm/llm.py`'s `atext_request`/`LLMActor.call` pass
`extra_body` straight through to the OpenAI SDK call, and the parameter's
own docstring gives `{"guided_json": schema}` as the example). Since our
own code already knows `current_need` before calling the LLM, the schema
requires **all four** satisfaction keys every time — the model never has
to name a key at all, which removes the mismatch risk by construction
rather than by hoping the model follows a convention.

This also fixes a second, independent limitation: the vendored design only
ever let the model touch the *current* need's dimension (or safe+social
together for `"whatever"`), so a plan with genuine side effects on another
need (e.g. "eat at home with a friend" plausibly raising both hunger and
social satisfaction at once) had no way to express that. Requiring all
four every time removes that restriction; the prompt instructs the model
to leave unaffected dimensions roughly where they were, not reset them.

**No fallback, and no retry-on-bad-shape** (explicit user requirement): if
`guided_json` isn't honored by PLGrid's backend, or the response doesn't
match the schema, `json.loads(response)` / `new_satisfaction[key]` raise
immediately and visibly — nothing catches or retries this. This is
deliberately separate from `atext_request()`'s own existing retry loop
(default `retries=10`, exponential backoff) for genuine transient
failures (connection errors, timeouts, API errors), which is untouched
and still applies underneath this call.

**Unverified**: nothing in this codebase previously used `guided_json`, so
whether PLGrid's specific deployment honors it is untested. The next run
will tell us directly — if it crashes, that's the answer, not a bug in
this change (see "no fallback" above).

## Smoke test: confirmed working (2026-07-19, 1 agent, 5 sim-hours)

Archived the 20-agent baseline run's logs to `archive/20_base_run/`
(`plan_logs/`, `position_logs/`, `internet_logs/`, `metrics_output/`) to
get clean working directories, then temporarily set `internet.py` to
`number=1` and `N_STEPS=60` (5 sim-hours instead of 24) to smoke-test the
`guided_json` evaluator end to end. Reverted both back to `number=20` /
`N_STEPS=288` afterward — the config in `internet.py` now is the real
20-agent full-day config.

Result: **no crash, 3/3 plan evaluations returned valid schema-conforming
JSON.** Confirms `guided_json` is honored by PLGrid's backend for this
model. Concretely, vs. the pre-fix 20-agent run:

- No more exact-zero-delta evaluations — every dimension moved by a real,
  non-trivial amount every time (e.g. `-0.05, -0.23, +0.33, +0.12` in one
  evaluation).
- No `[SAME NEED REPEATED]` loop in 3 plans (need sequence:
  `none -> safe -> whatever -> safe`), vs. the old run's 18/20 agents
  hitting a >=3x same-target loop.
- Plans now run 20 minutes to 4 hours instead of the old 5-15 minute
  thrash. A 4-hour "Leisure and entertainment" plan correctly cost hunger
  0.89->0.32 and energy 0.69->0.35 — first real evidence the duration-aware
  prompt is doing its job.
- Multi-need side effects are showing up as intended: a `need=safe` "Work"
  plan (staff meeting, patient consultations) also moved
  `social_satisfaction` by +0.22.

Not exercised by this test: the mobility-execution fix (finding #2) —
1 agent over 5 hours didn't happen to generate a mobility-heavy plan whose
outcome we could inspect end-to-end. That still needs a full 20-agent run
to confirm.

The 1-agent test run's own logs are archived at
`archive/1_agent_structured_output_test/`. Working `plan_logs/`,
`position_logs/`, `internet_logs/` are now empty and ready for the next
full 20-agent run.

## Model swap: Qwen3-Coder-30B -> Bielik-11B, plus debug instrumentation (2026-08-09)

`internet.py`: `LLMConfig.model` changed from `Qwen/Qwen3-Coder-30B-A3B-Instruct`
to `speakleash/Bielik-11B-v3.0-Instruct` (different API key too — see the
file for the current value). Smaller, weaker instruction-following model;
motivated adding `$DEBUG$`-prefixed print instrumentation (not wired to any
log file, stdout only) to trace exactly what the framework does per step:

- `internetagent.py` `__init__`: wraps `self.dispatcher.dispatch` to print
  the step type/intention and which top-level block got selected for it.
  `forward()`: position-change log entries gained `step_type`/`emotion`/`need`
  fields.
- `utils/mobility_block_custom.py`: `MoveBlock` (new, instrumented copy of
  the vendored class) prints the raw place-analysis LLM response and flags
  each already-there no-op branch.
- `utils/needs_block_custom.py`: prints each raw `guided_json` response
  attempt, and gained bounded retry (`MAX_SCHEMA_RETRIES=3`) after
  observing Bielik return an extra unrequested key or a bare `{}` — see
  the file's own docstring for detail. (The original "no retry, raise
  immediately" design was for detecting whether `guided_json` was honored
  at all; once confirmed honored-but-imperfect, a bounded retry was the
  right next step.)
- `packages/agentsociety/agentsociety/llm/llm.py`: `atext_request()` /
  `LLMActor.call()` gained an `extra_body` passthrough parameter so
  `guided_json` (and similar vLLM extras) can be passed from example code
  without vendoring the whole LLM class.
- `packages/agentsociety/agentsociety/cityagent/blocks/economy_block.py`:
  `MonthEconomyPlanBlock` switched from regex-based `extract_dict_from_string`
  to `json_repair.loads` + explicit `response_format={"type": "json_object"}`
  — Bielik's free-form responses weren't matching the regex reliably.

A 20-agent full-day run with this instrumentation found mobility had gotten
*worse* on Bielik (13/19 agents, 68%, vs 27/45, 60%, pre-fix) — see
`findings.md`'s "model swap to Bielik-11B surfaced three more bugs" addendum
for the three root causes found by tracing this run's `run.log` directly.

## Fix: single failed step no longer fails the whole plan (2026-08-16)

Root cause (`findings.md` addendum, "Bug A"): vendored `societyagent.py`'s
`check_and_update_step()` treats *any* step's `evaluation["success"] = False`
as failing the entire plan — `current_plan["failed"] = True`, picked up
immediately by `update_when_plan_completed()`, which nulls `current_plan`
and abandons every step still queued behind the failed one. Confirmed via
`run.log`: agent 20's "Contact with friends" plan (social, social,
mobility, mobility) died right after step 0 got `social_block.py`'s
`FindPersonBlock` silently returning `success: False` ("No target found in
social network") — a routine, non-rare condition, not a crash or parse
error. Both mobility steps behind it were never attempted.

Fix: `internetagent.py` — new `InternetAgent.check_and_update_step()`
override. Before delegating to `super().check_and_update_step()`, checks
the current step's `evaluation["success"]`; if `False`, flips it to `True`
in place (and logs a `$DEBUG$` line noting the override fired) so the
vendored logic advances to the next step instead of ending the plan. The
step's own `evaluation` *text* (e.g. "Failed to execute...") is left
untouched, so `TimeAwareNeedsBlock.evaluate_and_adjust_needs()` still sees
what actually happened when it scores the plan afterward — this only
changes plan **control flow**, not what gets reported to the LLM evaluator.

Deliberately not a vendored-code change: kept local to `examples/internet/`
by overriding the method on `InternetAgent` rather than editing
`packages/agentsociety/agentsociety/cityagent/societyagent.py` directly.

## Fix: stale per-tick satisfaction snapshot (2026-08-16)

Root cause (`findings.md` addendum, "Bug C"): `internetagent.py`'s
`_pre_tick_satisfaction` was captured once per **tick**, at the top of
`forward()`, then stashed onto a freshly-generated plan as
`_satisfaction_at_start` in `plan_generation()`. But a plan's completion
and its successor's generation routinely happen in the **same tick**
(`SocietyAgent.forward()` runs check-step -> needs-block -> plan-generation
end-to-end whenever a step boundary is crossed, no gap tick in between) —
so the tick-start snapshot predated the *predecessor* plan's own
`evaluate_and_adjust_needs()` call within that same tick. Every fresh
plan's logged "starting" satisfaction was actually one plan-cycle stale.

Fix: removed `self._pre_tick_satisfaction` and the tick-start snapshot
entirely (`InternetAgent.forward()` no longer takes one).
`InternetAgent.plan_generation()` now builds the `_satisfaction_at_start`
dict from a **live** `memory.status.get(...)` fetch, taken right after
`super().plan_generation()` returns (i.e. after `needs_block.forward()`
has already run for this tick, so any same-tick predecessor evaluation is
reflected). Verified against the 2026-08-16 validation run: consecutive
plans' `satisfaction_before`/`satisfaction_after` now chain exactly.

**Side effect worth knowing about**: this makes `need_before` (also part of
the stashed snapshot) tautologically equal to `need` on every row, since
`current_need` cannot change during a single plan's own lifetime once the
snapshot is correctly plan-scoped. `readable_plan_log.py`'s
`[SAME NEED REPEATED]` flag (`need_before == need`) is now meaningless as
written — see "Known issues / next todos" below.

## Fix: MoveBlock destination classification bias (2026-08-16)

Root cause (`findings.md` addendum, "Bug B"): the vendored
`PLACE_ANALYSIS_PROMPT`'s only worked example is `{"place_type": "home"}` —
anchors a weaker model toward answering "home" for ambiguous intentions.
Confirmed from `run.log`: agent 11's "Commute to school" got classified
`"home"`; since the agent was already home, `MoveBlock`'s already-there
no-op shortcut silently returned success without calling
`environment.set_aoi_schedules`.

Fix, both in `utils/mobility_block_custom.py`'s `MoveBlock`:
1. New `CUSTOM_PLACE_ANALYSIS_PROMPT` (set via a new `__init__` override)
   — same shape as the vendored prompt, but with three balanced worked
   examples (workplace/other/home) instead of one, plus an explicit
   "don't default to home" instruction.
2. Keyword gate on the no-op shortcut: `_intention_supports()` checks the
   step's own intention text against `_HOME_KEYWORDS`
   (`home`/`house`/`apartment`) or `_WORKPLACE_KEYWORDS`
   (`work`/`office`/`job`/`shift`/`school`/`class`/`meeting`/`commute`)
   before trusting an already-there no-op. If the classification lands on
   `home`/`workplace`, the agent's already there, *and* the intention text
   doesn't support that category, the response is remapped to `"other"` so
   the step falls through to the generic real-destination-search branch
   instead of silently completing as a no-op.

## Validation run (2026-08-16, 20 agents, Bielik, all three fixes above applied)

Run via `CLEAR_LOGS_ON_START=1 python3 internet.py` (no `run.log` capture
this time — see "Known issues" below). Results, full detail in
`findings.md`'s validation-run section:

- Mobility gap (agents with mobility plans, zero position-log entries):
  **3/19 (16%)**, down from 13/19 (68%) pre-fix and 7/18 (39%) after the
  model swap alone.
- Satisfaction chaining confirmed correct (spot-checked agent 1).
- Corrected same-need-repeat rate (consecutive-plan comparison, not the
  now-tautological single-row one): **146/387 (37.7%)**.

## Known issues / next todos

- **`readable_plan_log.py`'s `[SAME NEED REPEATED]` flag is now
  tautological** (`need_before == need` always true post-fix — see the
  stale-snapshot fix above). Needs to be changed to compare each plan's
  `need` against the *previous* plan's `need` (per agent, chronologically)
  to remain meaningful. Not yet fixed.
- **`run.log` wasn't captured for the 2026-08-16 validation run** — the
  aggregate `plan_logs.jsonl`/`position_logs.jsonl` numbers are trustworthy,
  but there's no per-step `$DEBUG$` trace to directly confirm which
  mechanism (step-skip vs. MoveBlock distrust-fallback) fired for any given
  now-moving agent. Re-run with
  `CLEAR_LOGS_ON_START=1 python3 internet.py 2>&1 | tee run.log` if that
  level of confidence is needed again.
- **Agents 2, 6, 9 still have mobility-containing plans that never move**
  in the validation run — investigated using `internet_logs/device_usage_logs.jsonl`
  as a step-execution trace (no `run.log` for this run). Conclusion: not a
  new bug. Agent 6's "Start Work" plan is direct confirmation the
  single-step-failure fix works — it ran straight through its mobility step
  (index 2) to steps 3-5 instead of dying, the mobility step itself just
  being a plausible legitimate no-op (already at workplace). Agents 2 and 9
  both show ordinary `determine_current_need()` priority interruption (a
  `whatever`-need plan losing to any of the four core needs by design, and
  a `social`-need plan cut off before its final "meet the friend" payoff
  step, with the evaluator correctly not crediting an unreached outcome) —
  the same mechanism `current_changelog.md` already discusses and
  explicitly didn't add a cooldown for per prior direction. See
  `findings.md`'s "Remaining stuck agents" section for the full trace. No
  code change made; this is intentionally-unaddressed, not an open bug.
- The append-mode log files issue (`plan_logger.py`/`device_logger.py`/
  `antennas.py` never clearing between runs unless `CLEAR_LOGS_ON_START=1`
  is set) is mitigated but still opt-in, not the default — still flagged,
  not changed.
- Occupation-skew observation (finding #4) not revisited since the model
  swap.

## Investigated: how often do agents do mundane physical errands, and why so rarely (2026-08-16)

Prompted by the "why does social interaction fail so often" question — quantified
gym/exercise, grocery shopping, socializing-in-person, and work-commuting from
the validation run's `plan_logs.jsonl` (20 agents, 1 day):

| activity | plans/agent/day | with a mobility step | agents who ever do it |
|---|---|---|---|
| contact friends | 9.50 | 11.6% | 13/20 in-person ever, 7/20 never |
| work | 1.90 | 52.6% (commute) | 14/20 ever commute, 4/20 never |
| shopping/groceries | 0.40 | ~25% genuine trips | 4/20 ever shop at all |
| gym/workout | 0.40 mentions | **0%** | 3/20 (fitness occupations only) |

Root causes found in `utils/prompts.py`, all the same family of bug (anchoring
bias toward the one pattern the model is shown/told, same as the earlier
`MoveBlock` destination-classifier fix — just one layer up):

1. **`CUSTOM_BLOCK_DISPATCH_PROMPT`'s `otherblock` catch-all explicitly listed
   "exercising"**, directly contradicting the plan prompt's own "go to the gym"
   instruction — so even the rare workout that got planned never routed through
   `mobilityblock`.
2. **The same prompt's "When in doubt, choose otherblock" default** biases
   dispatch away from `mobilityblock` in general, and it doesn't even see the
   step's own `type` (already assigned during planning) to check against —
   already caught in the wild during the original investigation:
   `top-level dispatch for InternetAgent_18: step_type='mobility' ... -> OtherBlock`.
   Traced 13 "Contact with friends" plans that had a mobility step but produced
   no position-log entry against `device_usage_logs.jsonl`'s per-step trace: 7
   of 13 clearly reached the mobility step's own index before failing to
   move — i.e. most of this specific failure mode is dispatch-time, not the
   priority-interruption mechanism from the earlier investigation.
3. **`CUSTOM_DETAILED_PLAN_PROMPT`'s only worked example is "Eat at home"** —
   a single pattern for the model to imitate, with no equivalent shown for
   groceries, gym, or in-person socializing.
4. **Grocery-specific**: `INTERNET_AWARENESS_PROMPT`/the device-usage section
   said devices "enable you to solve problems remotely without traveling",
   directly undercutting the "don't replace physical activities" line
   elsewhere. Of 8 shopping-labeled plans all day, 6 were pure
   online-order-and-wait-for-delivery with zero physical step.

### Fixes (all in `utils/prompts.py`)

- `CUSTOM_BLOCK_DISPATCH_PROMPT`: added `${context.current_step["type"]}` to
  the prompt so dispatch can see planning's own type tag; mobilityblock's rule
  now explicitly says to pick it whenever type is "mobility" regardless of
  intention wording; "when in doubt" now defers to the declared type instead
  of defaulting to otherblock; "exercising" removed from the otherblock
  catch-all (replaced with "a workout already happening at the current
  location", which only applies once a mobility step has already gotten the
  agent there or a home workout was chosen).
- `CUSTOM_DETAILED_PLAN_PROMPT`: new "General rhythm" bullets giving exercise
  an explicit *either/or* — home workout (type "other", no travel) or
  gym/park (mobility there + other for the workout, phone use during is
  fine) — agent's choice based on mood/weather/time, not a hard requirement
  either way (per explicit user direction: don't force movement, let the
  agent decide). A second bullet makes grocery/errand shopping default to an
  in-person trip pattern, with pure online delivery reserved for cases that
  genuinely don't need one. New "Typical step patterns" section gives five
  worked step-shape examples (eating out, grocery run, gym workout, home
  workout, meeting a friend in person) instead of relying on the single
  "Eat at home" JSON example to carry all the pattern-matching weight. The
  device-usage section's "solve problems remotely without traveling" line
  softened to explicitly exclude grocery/gym/social as default substitutes.

**Verification**: `python3 -m py_compile utils/prompts.py` and
`import internet` (via the project venv) both succeed. **Not yet re-run
against a live simulation** — next step is a fresh validation run to check
whether gym/grocery/social-mobility rates actually move.

## Validation run (2026-08-16, 20 agents, Bielik, gym/groceries/dispatch-bias fixes applied)

User re-ran with `CLEAR_LOGS_ON_START=1 python3 internet.py 2>&1 | tee run.log`
(279 plans, one simulated day, `run.log` captured in full this time).

**Headline mobility-gap number**: agents with mobility-typed plan steps but
zero actual position change all day: **1/20 (5%)**, down from 3/19 (16%) in
the previous validation run and 68% pre-fix. `20/20` agents now have at
least one mobility-typed plan step, `19/20` produced at least one real
position change.

**Category breakdown (this run)**:
- **Gym/workout**: 13 plans mentioned it, 9 (69%) included a mobility step
  — up from 0% (0 of ~8) before the fix. Manually inspected all 13: it's a
  genuine mix, not a new default — home workouts (agents 6, 12, 18's first
  plan, agent 1's 03:55 plan) sit alongside gym/park trips (agents 1, 17,
  18's second plan), matching the "let the agent decide" design goal rather
  than forcing either direction.
- **Dedicated shopping-trip plans** (plan_target containing "Shopping" /
  "Grocery shopping", as opposed to "Eat at home" plans that merely mention
  checking grocery inventory before cooking): 6 plans, 5 (83%) went
  in-person. The one online-only case (agent 4, 19:10) reads as a genuine
  "already handled dinner another way" case, not a default.
- **Social-in-person** (plans/steps mentioning meeting/hanging out with a
  friend): 105 mentions, 40 (38%) included a mobility step — up from 11.6%
  before the fix. Directly answers the "why do social interactions fail so
  often" question from last round: the dispatch-bias fix (exposing
  `current_step["type"]` to the dispatcher, deferring to it instead of
  defaulting to otherblock) was the dominant lever, consistent with the
  prior finding that most of this failure mode was dispatch-time rather
  than priority-interruption.
- **Work/commute**: 43 plans, 20 (47%) mobility — flat vs. the ~53% baseline
  (within noise for a single-day run of this size); expected, since this
  category wasn't targeted by the fix and was already working.

**The one remaining non-mover (agent 10, "Grace")**: traced end-to-end via
`run.log`. Dispatch correctly routed the step to `MobilityBlock`
(`step_type='mobility'`), `MoveBlock` place-analysis correctly returned
`place_type='other'` (no home/workplace anchoring bias), `PlaceSelectionBlock`
successfully picked a destination (`('', 700002473)`), and the step's own
evaluation reported `success=True`. The same POI was independently selected
earlier in the run for a different agent (8), who *did* show a real position
change immediately after. Yet agent 10's `xy_position` never changed for the
entire simulated day (0 entries in `position_logs.jsonl` for agent_id 10) —
including on the very next tick, when position is checked at the top of
`forward()` before the following step executes. This means
`environment.set_aoi_schedules()` was called and returned without raising,
but the underlying city simulator never produced a visible position update
for this specific agent/destination pair — most plausibly a routing/pathfinding
edge case in the vendored simulator (e.g. no path found from agent 10's
current position to that POI) rather than anything in our prompt/dispatch
fixes, since every other step of the diagnostic chain (dispatch type, place
classification, destination selection, step evaluation) behaved correctly.
**Not the same mechanism as the previously-diagnosed agents 2/6/9**
(priority-interruption before reaching the mobility step) — this one
reached and "completed" the mobility step per our own bookkeeping, but the
simulator didn't move the agent. Not chased further given it's 1/20 and
outside the scope of the prompt-level fixes; worth another look if it
recurs across future runs.

**Conclusion**: all three fixes from the previous section (dispatch-bias,
exercise either/or, grocery in-person default) validated — each targeted
category moved in the expected direction, with the social-in-person number
in particular jumping from 11.6% to 38%.
