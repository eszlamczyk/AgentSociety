# Simulation Findings — internet example run (2026-07-19)

Source data: `plan_logs/plan_logs.jsonl` (2670 plan entries, 100 agents),
`position_logs/position_logs.jsonl` (292 position entries, 55 agents),
`agentsociety_data/sqlite.db` (100 agent profiles). Sim span: ~1 day
(day0 06:00 → day1 05:55).

## 1. Systemic replanning loop

94 of 100 agents get stuck replanning the *same* `plan_target` back-to-back
every 5–15 sim-minutes, without ever progressing to a new need/target.

- Worst case: agent 68 replans `Contact with friends` **26 times in a row**
  over ~6 hours (day0 08:05 → 13:50), `need=social` the entire time, emotion
  drifting Distress → Fear with no resolution.
- Agent 96 shows the same pattern with `Sleep at home`: 5 consecutive
  replans between day0 15:15 and 17:30, then again 22:20 → 00:40 (day1).

Likely cause: the underlying need (`tired`, `social`, `hungry`) isn't being
marked satisfied after a `[device]` step executes, so the planner re-fires
a near-identical plan on the same unmet need every tick instead of
progressing. Worth investigating the need-decay / plan-completion logic in
`internetagent.py`.

Detection method: for each agent, sorted plans by sim_time; counted runs of
consecutive entries with the same `plan_target` where the gap between
entries is ≤60 sim-minutes.

| agent_id | max consecutive same-target | loop episodes (≥3) | total plans |
|---|---|---|---|
| 68 | 26 | 2 | 49 |
| 16 | 23 | 2 | 40 |
| 66 | 18 | 4 | 30 |
| 30 | 17 | 1 | 27 |
| 4  | 16 | 2 | 30 |
| 20 | 14 | 2 | 35 |
| 31 | 14 | 1 | 29 |
| 96 | 14 | 5 | 33 |
| 61 | 14 | 1 | 24 |
| 8  | 13 | 2 | 30 |

## 2. Mobility steps are silently dropped

45 of 100 agents never appear in `position_logs.jsonl` at all (never
generated a movement/position entry).

Of those 45, **27 had plans that explicitly contained mobility steps**
(e.g. "Go to the nearest grocery store", "Travel to meeting location",
"Return home") that were logged in the plan but never produced a
corresponding position log entry. This is not agents choosing to stay
home — it's planned movement that never executed. Worth checking whether
mobility-step dispatch/execution has a silent failure path.

## 3. Daytime "napping" is population-wide, not agent-specific

`Sleep`-target plans are almost as common at 12:00–17:00 as at
23:00–05:00:

```
 0:00    68   1:00    41   2:00    62   3:00    35   4:00    41   5:00    41
 6:00     0   7:00     0   8:00     0   9:00     0  10:00     0  11:00     3
12:00    41  13:00    51  14:00    55  15:00    47  16:00    35  17:00    22
18:00    32  19:00    25  20:00    36  21:00    35  22:00    46  23:00    61
```

No apparent circadian gating on the `tired` need. Combined with finding
#1, this produces the "multiple naps with doomscrolling between" pattern
(e.g. agent 96's five consecutive afternoon "Sleep at home" plans).

## 4. Employment is mostly fine, but occupation-skewed

Nearly every employed occupation gets at least one `Work`/`Start work`
plan over the day:

| occupation | agents | with ≥1 work plan | rate |
|---|---|---|---|
| Businessman | 12 | 12 | 100% |
| Doctor | 11 | 11 | 100% |
| Athlete | 12 | 12 | 100% |
| Artist | 13 | 13 | 100% |
| Teacher | 8 | 8 | 100% |
| Engineer | 13 | 13 | 100% |
| Manager | 12 | 12 | 100% |
| Other | 14 | 8 | 57% |
| Student | 5 | 2 | 40% |

But *volume* is skewed — average work-plans/day per agent:

| occupation | avg work-plans | avg sleep-plans |
|---|---|---|
| Manager | 11.2 | 3.5 |
| Doctor | 9.5 | 4.2 |
| Engineer | 5.8 | 7.5 |
| Teacher | 5.4 | 6.8 |
| Businessman | 4.2 | 10.1 |
| Athlete | 1.7 | 9.8 |

Athletes/Artists/"Other" occupations lean heavily toward sleep/social
loops instead of work, and (per finding #1's underlying data) are much
more likely to never move at all. This looks like a prompt-template bias
for those occupations rather than an execution bug — lower priority than
#1 and #2, but worth a look at the occupation-specific prompting in
`internetagent.py` / `utils/prompts.py`.

## Root cause analysis

The needs/emotion logic isn't in `examples/internet/` at all — `InternetAgent`
(`internetagent.py`) subclasses `SocietyAgent`, which lives in the vendored
framework package at `packages/agentsociety/agentsociety/cityagent/`. All
file:line refs below are relative to that directory.

**Main loop** (`societyagent.py:390` `forward()`) runs, per tick, in order:
`check_and_update_step()` → `needs_block.forward()` → `plan_generation()` →
`step_execution()`.

### Why #1 (replanning loop) happens

1. `needs_block.py:337` `determine_current_need()` — when there's no
   `current_plan`, it picks the highest-priority unmet need (hungry > tired >
   safe > social) and writes it to `current_need`. While a plan *is* active,
   it only interrupts for a **higher**-priority need (`current_need not in
   [...]` guards, lines 424-450) — so same-need re-interruption during an
   active plan is blocked, as expected.
2. But `needs_block.py:317` `update_when_plan_completed()` runs first, every
   tick, and as soon as a plan's `completed`/`failed` flag is set, it calls
   `evaluate_and_adjust_needs()` (an LLM call scoring the four satisfaction
   dimensions) and then **sets `current_plan` to `None`** (line 331).
3. Once `current_plan is None`, `determine_current_need()` falls back to the
   "no plan" branch (step 1) and picks a need again — if the LLM's
   satisfaction score for e.g. `social_satisfaction` is still ≤ threshold
   (`T_C`), it re-selects `"social"` and `plan_generation()`
   (`societyagent.py:369`) immediately generates a fresh, near-identical plan.
4. Steps finish fast because their duration is an LLM guess from a single
   intention string with no knowledge of the rest of the day: `OtherBlock`
   (`blocks/other_block.py:215`) dispatches each `[other]` step to either
   `SleepBlock` (`:45`, LLM-estimated minutes from a prompt that never sees
   wall-clock time) or `OtherNoneBlock` (`:108`, same issue, falls back to
   `random.randint(1, 180)` on a parse failure). A 2–4 step "Sleep at home"
   plan can therefore fully complete in under an hour.
5. Net effect: plan completes quickly → satisfaction re-scored by LLM → if
   still low, same need re-fires → near-identical plan generated → repeat.
   This is exactly the 5–15-minute repeating "Contact with friends" /
   "Sleep at home" loops in finding #1, and there's no time-of-day gate
   anywhere in this path, which is also why it fires at 3pm (finding #3).

### Why #2 (mobility planned but never executed) happens

`MobilityBlock` (`blocks/mobility_block.py:509`) dispatches each `[mobility]`
step, **per tick, via a separate LLM function-call choice**
(`agent/dispatcher.py:21` `BlockDispatcher.dispatch()`), to one of three
sub-blocks:

- `PlaceSelectionBlock` (`:157`) — only *picks a destination*. Returns
  `success: True, consumed_time: 5` (line ~278-283) without ever calling
  the environment to move the agent.
- `MoveBlock` (`:286`) — the one that actually calls
  `environment.set_aoi_schedules(...)` to move the agent (e.g. line 342,
  376, 408, 431), `consumed_time: 45`.
- `MobilityNoneBlock` (`:465`) — no-op completion.

`check_and_update_step()` (`societyagent.py:428`) only looks at whether the
step's `evaluation` dict is present and its `consumed_time` has elapsed — it
has no notion of "did MoveBlock actually run." So if the LLM dispatcher picks
`PlaceSelectionBlock` for a mobility step and the step's evaluation clock
runs out (or the plan gets interrupted by the loop in #1) before
`MoveBlock` is ever dispatched on a later tick, the mobility step is marked
complete/abandoned having only *chosen* a destination — no
`set_aoi_schedules` call ever fires, no position change, nothing in
`position_logs.jsonl`. Combined with #1 (plans getting nuked mid-flight via
`current_plan = None`), this is consistent with 27/45 no-movement agents
having mobility steps that never resulted in a logged position change.

### Suggested fix directions

- `needs_block.py:454` / `:465` and `update_when_plan_completed` (`:331`):
  don't null out `current_plan` and immediately allow same-need reselection
  in the same tick — add a cooldown, or require `evaluate_and_adjust_needs`
  to push satisfaction meaningfully above threshold before the same need can
  re-trigger a plan.
- `other_block.py` `SleepBlock`/`OtherNoneBlock` time-estimation prompts:
  pass current sim time-of-day into the estimate so "Sleep" at 3pm either
  gets rejected or produces a full-night duration instead of a random 1-30
  minute guess.
- `mobility_block.py`: make `PlaceSelectionBlock` and `MoveBlock` two halves
  of one atomic step (or have `check_and_update_step` verify a `to_place`
  position match before marking a `[mobility]` step's evaluation complete),
  so a step can't be considered "done" after only choosing a destination.

See `current_changelog.md` for the actual code/instrumentation changes
made while investigating this (readable_log.py's `[NO MOVEMENT]` flag,
and per-tick satisfaction logging in `internetagent.py` / `plan_logger.py`
/ `readable_plan_log.py`).

## Suggested next steps

1. Trace need-satisfaction logic for the replanning loop (#1) — check
   whether completing a `[device]` step actually clears/decrements the
   triggering need.
2. Trace mobility-step execution (#2) — check whether the mobility
   dispatcher can fail silently without logging or falling back to a new
   plan.
3. Add circadian gating (or at least discourage) `tired`-need plans
   during daytime hours (#3).
4. Review occupation-specific prompt templates for Athlete/Artist/Other
   to see why they skew toward sleep/social loops over work (#4).

## Addendum: empirical confirmation from the 20-agent run (2026-07-19)

After shrinking to 20 agents and adding satisfaction-delta logging (see
`current_changelog.md`), a fresh run confirmed #1 and #2 directly from
real numbers instead of hypothesis:

- **18/20 agents** hit a `>=3`-consecutive-same-target loop (worst: agent 13,
  23 in a row) — same rate as the 100-agent run (94/100), confirming the
  bug is per-agent, not an artifact of population size.
- **76% of need transitions (370/489)** were same-need repeats
  (`need_before == need`).
- On those 370 repeat events, the LLM's evaluation of the *relevant*
  satisfaction dimension moved by **-0.001 on average** (median exactly
  0.000). **69% of repeats showed an exact 0.000 delta** — the LLM
  essentially echoed back the same value it was shown. 97% of repeats
  were still at/below threshold after the "evaluation."
- Broken down by need: `hungry`/`tired` were the worst — **88-91% exact-zero
  delta** — while `safe`/`social` did get non-zero adjustments, but
  `social`'s mean delta was still slightly *negative* (-0.005). One agent's
  "Contact with friends" chain slid 0.34 → 0.29 → 0.20 → 0.18 → ... → 0.07
  over 45 minutes of "successful" 2-3 step replans — pure decay, no real
  recovery from evaluation.
- **Mobility: 13/19 agents (68%)** with at least one mobility-containing
  plan never produced a single position-log entry — consistent with (and
  slightly worse than) the 100-agent run's 27/45 (60%).

This directly motivated the fixes in `current_changelog.md`: a time-aware
evaluator (`TimeAwareNeedsBlock`) that's told each step's actual duration
and instructed to weight time spent over step-success text, a reliable
mobility block that can't mark a step done without actually moving, and
plan/duration prompt tweaks discouraging daytime sleep. Not yet re-run
against a live simulation to confirm the fixes work — that's the next step.

## Addendum: model swap to Bielik-11B surfaced three more bugs (2026-08-09/16)

`internet.py` was switched from `Qwen/Qwen3-Coder-30B-A3B-Instruct` to
`speakleash/Bielik-11B-v3.0-Instruct` (smaller, weaker instruction-following).
A fresh 20-agent full-day run on Bielik, with per-block debug instrumentation
added to `internetagent.py`/`utils/mobility_block_custom.py`, found mobility
had gotten *worse* — **13/19 agents (68%)** with mobility-containing plans
produced zero position-log entries, vs 27/45 (60%) pre-fix. Tracing this
directly against the debug output (not just the plan/position logs) found
three distinct causes, none of which were about raw need-decay speed (that
hypothesis was checked and ruled out: `alpha_H=0.15/hour` means hunger takes
5.3 real hours to decay from full to threshold — a realistic rate).

### Bug A: one failed step silently kills the whole plan

Ground-truth trace (agent 20, day0 11:20): a plan `Contact with friends`
(steps: social, social, **mobility**, **mobility**) was replaced by an
unrelated plan just 5 sim-minutes later, after only its first step ever
dispatched. `social_block.py`'s `FindPersonBlock` returns
`{"success": False, "evaluation": "No target found in social network."}`
**silently** (no warning logged) whenever an agent's friend list is empty —
a routine, non-rare condition. Vendored `societyagent.py`'s
`check_and_update_step()` treats *any* single step's `success: False` as
failing the **entire plan** (`current_plan["failed"] = True`), which
`update_when_plan_completed()` picks up on the very next check and nulls
`current_plan` immediately — abandoning every step queued behind the failed
one, including both mobility steps, without ever attempting them. Since
plans tend to put mobility steps after prep/social steps (not first), this
one silent, common failure mode was enough to explain most of the mobility
gap on its own.

### Bug B: MoveBlock's destination classifier is anchored toward "home"

Confirmed from all 60 place-analysis calls in the run: agent 9's "Take a
short walk indoors" and agent 11's "Commute to school" were both classified
`"home"` (the second one wrong — school isn't home), and both agents
happened to already be home, so `MoveBlock`'s already-there no-op shortcut
fired and `environment.set_aoi_schedules` was never called. Root cause: the
vendored `PLACE_ANALYSIS_PROMPT`'s only worked example is
`{"place_type": "home"}` — classic one-shot anchoring bias, worse on a
smaller/weaker model. Other misclassifications turned up in the same
sample too (e.g. "Return home from workplace" -> `workplace`, backwards),
though those don't cause silent no-ops since the agent isn't already there.

### Bug C: our own satisfaction-logging code had a tick-vs-plan scope bug

While tracing Bug A, plan rows showed `satisfaction_before` values that
didn't chain to the previous plan's `satisfaction_after` at all (e.g. a
"Contact with friends" plan logged `hunger: 0.075` as its starting point,
one tick after the previous plan had just raised hunger to `1.0`).
Root cause: `internetagent.py`'s `_pre_tick_satisfaction` snapshot was
captured once per **tick**, at the very top of `forward()` — but a plan's
completion (and its successor's generation) routinely happen **in the same
tick** (`SocietyAgent.forward()` runs `check_and_update_step` ->
`needs_block.forward()` [may complete the old plan] -> `plan_generation()`
[generates the new one] end-to-end whenever a step boundary is crossed, with
no "gap" tick in between). So the tick-start snapshot used for a freshly
generated plan's `_satisfaction_at_start` predated its own predecessor's
`evaluate_and_adjust_needs()` call within that same tick — every plan's
logged starting state was actually its *predecessor's* pre-evaluation
state, one plan-cycle stale.

**This also invalidates the "same-need-repeat" methodology used earlier in
this document and in `readable_plan_log.py`'s `[SAME NEED REPEATED]` flag**
(`need_before == need`, both fields from a single plan row). Once the
snapshot bug above is fixed, `need_before` and `need` become tautologically
equal for *every* row — `current_need` cannot change during a single plan's
own lifetime, so comparing a plan's own before/after need is comparing a
value to itself. The old, buggy tick-scoped snapshot was — by the same
same-tick-transition mechanic — usually capturing the *previous* plan's need
instead, which is why it read as a meaningful (if unreliable) cross-plan
signal before. The 76%→(pre-fix numbers above) were never a clean
measurement; they're not being retracted as "wrong direction," just marked
untrustworthy. See the validation-run section below for the corrected,
consecutive-plan-comparison version of this metric.

### Fixes applied (see current_changelog.md for the code)

- Bug A: `InternetAgent.check_and_update_step()` override — flips a failed
  step's `success` to `True` before delegating to the vendored logic, so
  the plan advances to the next step instead of being abandoned. The
  step's real failure text is left in `evaluation` so the satisfaction
  evaluator still sees what actually happened.
- Bug B: `utils/mobility_block_custom.py`'s `MoveBlock` now uses a prompt
  with three balanced worked examples (workplace/other/home) instead of
  one home-only example, plus a keyword gate — the already-there no-op
  shortcut only fires when the step's own intention text plausibly
  supports that destination category; otherwise it falls through to
  picking a real destination.
- Bug C: `InternetAgent.plan_generation()` now fetches the satisfaction/need
  snapshot live, at the point a new plan is actually created (after any
  same-tick predecessor evaluation has already run), instead of from a
  once-per-tick cache.

### Validation run (2026-08-16, 20 agents, Bielik, all three fixes applied)

- **Mobility gap: 3/19 agents (16%)**, down from 13/19 (68%) pre-fix and
  7/18 (39%) after the model swap alone (before this session's fixes) —
  substantial improvement. The three still-stuck agents (2, 6, 9) each only
  had 1-2 mobility-containing plans out of 13-36 total plans (much lower
  exposure than before); see the "remaining stuck agents" investigation
  below for what's still blocking them specifically.
- **Satisfaction chaining confirmed correct**: spot-checked agent 1's first
  six plans — each plan's `satisfaction_before` now exactly matches the
  *previous* plan's `satisfaction_after`, closing Bug C.
- **Corrected same-need-repeat rate**: comparing each plan's `need` to the
  *previous* plan's `need` (per agent, chronologically) instead of the
  now-tautological single-row `need_before == need` — **146/387 (37.7%)**
  of consecutive plan pairs share the same need. This is the first
  trustworthy measurement of this metric; not directly comparable to the
  pre-fix 76%/59% numbers above since the methodology changed, not just the
  code under test.
- **Caveat**: `run.log` (the `$DEBUG$`-instrumented stdout capture) wasn't
  captured for this run, so the validation above relies on `plan_logs.jsonl`
  / `position_logs.jsonl` aggregate numbers rather than direct per-step
  traces like the earlier investigation had. Re-run with
  `CLEAR_LOGS_ON_START=1 python3 internet.py 2>&1 | tee run.log` for full
  trace visibility if deeper debugging is needed.

### Remaining stuck agents (2, 6, 9): a different, already-known mechanism — not a new bug

`run.log` wasn't captured for the validation run, so this used
`internet_logs/device_usage_logs.jsonl` (has per-step `sim_time` and
`metadata.step_index`/`plan_target`) as a step-execution trace instead —
still ground truth, since it's written at actual dispatch time, just
without the top-level-dispatch/MoveBlock debug prints `run.log` would have
had.

**Agent 6's "Start Work" plan is the clearest evidence Bug A's fix is
working.** Steps: economy, economy, **mobility** ("Attend to patient
appointments"), economy, social, economy. `device_usage_logs.jsonl` shows
step_index 0, 1 executing, then **step_index 3, 4, 5 all executing
afterward too** — the plan continued straight through the mobility step at
index 2 instead of dying there, exactly the behavior the check-and-update
override was meant to produce. The mobility step itself produced no
position-log entry, but for a doctor already at their workplace attending
patients *at* that workplace, that's plausibly a legitimate no-op (nothing
to travel to), not a bug.

**Agents 2 and 9 both show the same pattern**: a plan runs several real
steps (confirmed via `device_usage_logs.jsonl` timestamps spanning up to 2
hours), then ends with the *next* need's satisfaction already below its
own threshold — e.g. agent 2's `whatever`-need "Leisure and Entertainment"
plan ended with `social_satisfaction: 0.182` (T_C=0.3), immediately
followed by a `social`-need plan; agent 9's `social`-need "Contact with
friends" plan (which reached step index 4 of 6 — "Plan the meeting
details" — per `device_usage_logs.jsonl`, but never dispatched step 5,
"Meet with the friend", the plan's actual payoff mobility step) ended with
`social_satisfaction` essentially unchanged (0.102 -> 0.1), and the next
plan's need is `social` again.

This is `determine_current_need()`'s ordinary priority-based interruption
(`needs_block.py`, vendored, untouched) — not the silent single-step-failure
bug fixed this session. Two things make `whatever`-need plans and
late-positioned mobility payoff steps specifically vulnerable to it: (1)
`whatever` has no priority-guard protection at all — *any* of the four core
needs crossing its threshold can interrupt a `whatever` plan, by design; (2)
a plan that hasn't yet reached its actual "meet the friend" / "attend the
event" step hasn't produced the outcome the evaluator should credit, so
the evaluator correctly declining to mark the need satisfied is *working
as intended*, not a bug — it's just that the same need then legitimately
re-fires for the next plan (matches the corrected 37.7% same-need-repeat
baseline above, not an anomaly).

This is the same mechanism `current_changelog.md` already discusses and
explicitly did **not** add a cooldown for, per prior direction ("sometimes
I can still be hungry after eating and decide to eat a second portion,
that's alright"). No further code change made here — flagging as
understood-but-intentionally-unaddressed rather than an open bug.
- `readable_plan_log.py`'s `[SAME NEED REPEATED]` flag still uses the
  now-tautological `need_before == need` single-row comparison — should be
  changed to compare consecutive plans per agent instead (same fix as the
  corrected metric above).
- The occupation-skew observation (finding #4) hasn't been revisited since
  the model swap or any of these fixes — still flagged as lower priority,
  not chased further.

## Addendum: mundane physical activities were rare, and mostly for a prompt-level reason (2026-08-16)

Follow-up question: are agents actually doing everyday out-of-home things —
gym/exercise, grocery runs, in-person socializing, commuting — at a
plausible rate? Measured against the validation run above (20 agents, one
day): "Contact with friends" plans fired 9.50/agent/day but only 11.6% of
them included a mobility step; gym/exercise was mentioned 0.40/agent/day
and *never* included a mobility step (0%); dedicated shopping-trip plans
were ~25% in-person, the rest pure online-order.

Root-caused to four things in `utils/prompts.py`, all upstream of any
per-agent randomness:
1. `CUSTOM_BLOCK_DISPATCH_PROMPT`'s `otherblock` catch-all explicitly listed
   "exercising", and its "when in doubt" fallback defaulted to `otherblock`
   — so even a plan step correctly typed `"mobility"` by planning could get
   redispatched to the wrong block at execution time.
2. Traced via `device_usage_logs.jsonl`: of 13 "Contact with friends" plans
   that never produced movement, 7 had already reached the mobility step's
   own index before failing to move — i.e. most of this specific failure
   mode was dispatch-time, not the priority-interruption mechanism from the
   section above.
3. `CUSTOM_DETAILED_PLAN_PROMPT`'s only worked JSON example was "Eat at
   home" — a single pattern for a weak model to imitate, with no equivalent
   shown for groceries, gym, or in-person socializing.
4. The device-usage guidance said devices "enable you to solve problems
   remotely without traveling", directly undercutting the prompt's own
   "don't replace physical activities" line elsewhere.

**Fixes** (`utils/prompts.py`): exposed the step's own planning-assigned
`type` to the dispatch prompt and made both the mobility rule and the
"when in doubt" fallback defer to it instead of guessing from wording;
removed "exercising" from `otherblock`'s catch-all; added explicit
either/or guidance for exercise (home workout vs. gym/park trip — agent's
own choice, not forced, per explicit design direction); made grocery
shopping default to an in-person trip pattern, online-only reserved for
cases that genuinely don't need a trip; added a "Typical step patterns"
section with five worked examples instead of relying on a single JSON
example to carry all the pattern-matching weight; softened the
devices-avoid-travel line to explicitly exclude grocery/gym/social as
default substitutes.

**Validated by a second run** (same day, all three fixes above applied,
279 plans): gym/exercise mobility rate 0% -> 69% (9/13 plans), and
manually inspected — a genuine mix of home workouts and gym/park trips,
not a new forced default in either direction. Dedicated shopping-trip
mobility rate ~25% -> 83% (5/6). Social-in-person mobility conversion
11.6% -> 38%, directly confirming the dispatch-bias fix as the dominant
lever for the "why do social plans fail to produce movement" question.
Work/commute held flat (~53% -> 47%, within noise), as expected since that
category wasn't targeted. Agents with a mobility-typed plan step but zero
actual movement all day: 1/20 (5%), down from 3/19 in the previous
validation run.

The one remaining non-mover (agent 10) was traced end-to-end and is a
different failure mode from anything above: dispatch, place-classification,
and destination-selection all behaved correctly and the step reported
`success: True`, but the underlying city simulator never produced a
visible `xy_position` change for that agent/destination pair, even though
a different agent independently sent to the exact same destination moved
fine. Reads as a simulator-level routing/pathfinding edge case rather than
anything in the prompt or dispatch logic — not chased further given it's
1/20 and outside the scope of these fixes.

## Addendum: social-network fix validated; the agent-10-style non-mover recurred (2026-08-22)

Full validation run (20 agents, Bielik, `run.log` captured, 253 plans, no
crashes) for the social-network seeding fix (`current_changelog.md`'s
"Fix: agents had no social network at all"). Confirmed: the
`"No target found in social network"` failure category (283/457, 62% of
all step failures pre-fix) is now **zero occurrences**; "Contact with
friends" share of plans dropped 37% -> 17.8%; the corrected
same-need-repeat rate dropped further, 37.7% -> 17.6%. All three
gym/grocery/dispatch-bias fixes and the mobility-execution fixes from the
prior two rounds held steady (mobility gap 11.1%, social-in-person
conversion 37.8%, shopping in-person 100%) — no regressions.

Two things worth flagging, neither a regression from this session's own
fixes:

1. **A new-looking `do_chat` failure mode, actually a pre-existing
   vendored-code fragility that had never been reachable before**: 21
   failures (`agent/prompt.py`'s `FormatPrompt.format()` choking, most
   likely on a literal brace character inside a chat message's free text)
   inside vendored `societyagent.py`'s `do_chat()`. Caught by `do_chat`'s
   own exception handler (agent silently skips replying to that message),
   never crashed the run. This only started happening now because agents
   finally have friends to receive chat messages from — see
   `current_changelog.md`'s 2026-08-22 entry for detail. Not fixed (would
   require touching vendored `societyagent.py`/`agent/prompt.py`).
2. **The "agent 10" simulator-level non-mover pattern recurred** (this
   run: agent 20, "Commute to school") — dispatch, place-classification,
   and destination-selection all correct, `PlaceSelectionBlock` picked a
   real destination, but no position-log entry ever appeared for that
   agent. Two occurrences across two runs (different agents, same
   destination-search-succeeds-but-no-visible-move signature) is enough
   that if it shows up a third time, it's worth tracing into the vendored
   simulator's `set_aoi_schedules`/pathfinding directly rather than
   continuing to treat it as a one-off.

See `current_changelog.md`'s 2026-08-22 entry for full numbers and the
debug-print noise cleanup done alongside this validation.
