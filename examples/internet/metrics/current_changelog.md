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
