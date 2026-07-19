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
