"""
Time-aware satisfaction evaluator.

The vendored NeedsBlock.evaluate_and_adjust_needs() (agentsociety.cityagent.
blocks.needs_block) asks an LLM to re-score the four satisfaction dimensions
after a plan completes/fails, but never tells it the current sim time or how
long each step actually took (step["evaluation"]["consumed_time"] is dropped
on the floor). That makes the evaluation blind to the difference between "sent
a message" and "spent 45 minutes in genuine conversation" — see findings.md
for the empirical confirmation (same-need repeat events show ~0 average delta
on the relevant satisfaction dimension).

TimeAwareNeedsBlock overrides only evaluate_and_adjust_needs to add:
  - current sim time (day + HH:MM:SS)
  - each step's actual consumed_time, inline in the evaluation text
  - explicit instruction to weight time spent over step "success" text
  - schema-constrained output (extra_body={"guided_json": ...}, vLLM
    constrained generation) instead of free-form JSON + retry/repair

Schema-constrained output fixes a separate, concrete bug: the vendored
prompt asks the LLM to name which satisfaction key it's updating (e.g.
"hunger_satisfaction" for the "hungry" need), but the mapping from need name
to key name is only demonstrated for "hungry" -> "hunger_satisfaction" in
the prompt's one example. "tired" -> "energy_satisfaction" has zero lexical
overlap and is never shown as an example. If the model ever returns a
slightly different key ("energy", "tired_satisfaction", ...), the vendored
code's `if need_type in (...)` check silently drops it — logged nowhere,
indistinguishable from "the LLM judged no change was warranted."

The schema below sidesteps this: we already know current_need in Python
before calling the LLM, so the model never has to name a key at all — every
response is required to contain all four satisfaction floats. This also
fixes a second issue: the vendored design only ever lets the model touch
the *current* need's dimension (or both safe+social for "whatever"), so a
plan with real side effects on another need (e.g. "eat at home with a
friend" plausibly raising both hunger and social satisfaction) had no way
to reflect that. Requiring all four every time removes that restriction —
the prompt tells the model to leave dimensions the plan didn't affect
roughly where they were, not to reset them.

Bounded retry-on-bad-shape (added after observing Bielik-11B on PLGrid
return an extra unrequested key, and separately a bare `{}`): if the
parsed response is missing any required key, re-ask up to
MAX_SCHEMA_RETRIES times. Extra/unrequested keys are harmless and kept
as-is (only SATISFACTION_KEYS are ever read). If every attempt still comes
back missing keys, this raises immediately and visibly rather than
treating missing data as "no change" — still no silent accept-and-move-on.
This is separate from (and doesn't touch) llm.atext_request()'s own
built-in retry loop (default retries=10, exponential backoff) for genuine
transient failures — connection errors, timeouts, API errors — which still
applies underneath each attempt exactly as before.

It also logs each plan's satisfaction outcome here, at completion time,
instead of at generation time (see internetagent.py's plan_generation()).
evaluate_and_adjust_needs() runs *before* a new plan is generated for
whatever need gets selected next in the same tick, so logging at generation
time meant the satisfaction delta shown was actually the *previous* plan's
evaluation, misattributed to the new plan about to start. Logging here
instead attributes the before/after delta to the plan that actually caused
it, using the start-of-plan context internetagent.py stashed onto
current_plan (_sim_time_at_start / _emotion_at_start / _satisfaction_at_start).

Everything else (time_decay, determine_current_need, thresholds/decay rates)
is inherited unchanged from the vendored NeedsBlock.
"""

import json

from agentsociety.cityagent.blocks.needs_block import NeedsBlock as _VendoredNeedsBlock

from utils.plan_logger import log_plan_generated

SATISFACTION_KEYS = (
    "hunger_satisfaction",
    "energy_satisfaction",
    "safety_satisfaction",
    "social_satisfaction",
)

# Some backends (confirmed: Bielik-11B on PLGrid) don't actually honor
# guided_json — observed responses included an extra unrequested key and,
# separately, a bare `{}`. Extra keys are harmless (we only ever read
# SATISFACTION_KEYS below); a response missing required keys gets re-asked
# up to this many times before we give up and raise loudly.
MAX_SCHEMA_RETRIES = 3

SATISFACTION_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "number", "minimum": 0, "maximum": 1} for k in SATISFACTION_KEYS},
    "required": list(SATISFACTION_KEYS),
    "additionalProperties": False,
}

TIME_AWARE_EVALUATION_PROMPT = """You are an evaluation system for an intelligent agent. The agent has performed the following actions to satisfy the {current_need} need:

Goal: {plan_target}
Current simulated time: {current_time}
Total time actually spent executing this plan: {total_minutes_elapsed} minutes

Execution log (each line shows the time actually spent on that step):
{evaluation_results}

Satisfaction levels going into this evaluation (0-1, where 1 = fully satisfied, 0 = completely unsatisfied):
- hunger_satisfaction: {hunger_satisfaction}
- energy_satisfaction: {energy_satisfaction}
- safety_satisfaction: {safety_satisfaction}
- social_satisfaction: {social_satisfaction}

Please return an updated value for ALL FOUR satisfaction dimensions.

Notes:
1. The dimension matching the current need ({current_need}) is the primary
   one this plan was meant to address — update it based on what actually
   happened, weighing time actually spent (shown above) over whether steps
   report "success". A plan that only spent a few minutes on preparatory
   steps (e.g. "check social media", "prepare for sleep") did NOT
   meaningfully satisfy the need — a real meal, a full night's sleep, or a
   substantive conversation takes real time. Raise satisfaction in
   proportion to time genuinely spent doing the thing itself, relative to
   what that need realistically requires (e.g. a full night's sleep is
   360-540 minutes, a real meal is 15-40 minutes, a real conversation is
   15+ minutes).
2. If the plan's steps clearly also addressed a DIFFERENT need as a side
   effect (e.g. "eat at home with a friend" can genuinely raise both
   hunger_satisfaction and social_satisfaction; a work meeting that
   included a shared meal could do the same), adjust that dimension too.
3. Any dimension the plan did NOT meaningfully affect should stay
   approximately equal to its value above — do not reset unrelated
   dimensions to 0 or 1, and do not invent progress on a need this plan
   had nothing to do with.
"""


class TimeAwareNeedsBlock(_VendoredNeedsBlock):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("evaluation_prompt", TIME_AWARE_EVALUATION_PROMPT)
        super().__init__(*args, **kwargs)

    async def evaluate_and_adjust_needs(self, completed_plan):
        evaluation_results = []
        total_minutes = 0
        for step in completed_plan["steps"]:
            step_eval = step.get("evaluation", {}) or {}
            if "evaluation" in step_eval:
                eva_ = step_eval["evaluation"]
            else:
                eva_ = "Plan failed or skipped, not completed"

            consumed = step_eval.get("consumed_time")
            try:
                consumed = int(consumed)
            except (TypeError, ValueError):
                consumed = None
            if consumed is not None:
                total_minutes += consumed
                time_note = f", took {consumed} min"
            else:
                time_note = ""

            evaluation_results.append(
                f"- {step['intention']} ({step['type']}{time_note}): {eva_}"
            )
        evaluation_results = "\n".join(evaluation_results)

        sim_day, sim_time = self.environment.get_datetime(format_time=True)
        current_need = await self.memory.status.get("current_need")

        await self.evaluation_prompt.format(
            current_need=current_need,
            plan_target=completed_plan["target"],
            evaluation_results=evaluation_results,
            current_time=f"day{sim_day} {sim_time}",
            total_minutes_elapsed=total_minutes,
            hunger_satisfaction=await self.memory.status.get("hunger_satisfaction"),
            energy_satisfaction=await self.memory.status.get("energy_satisfaction"),
            safety_satisfaction=await self.memory.status.get("safety_satisfaction"),
            social_satisfaction=await self.memory.status.get("social_satisfaction"),
        )

        # atext_request() still retries internally (default retries=10) on
        # connection errors / timeouts / API errors — untouched, applies
        # underneath every attempt below. What's handled here is a separate
        # failure mode: the backend not honoring guided_json's required-keys
        # constraint (missing keys, e.g. a bare `{}`). We re-ask up to
        # MAX_SCHEMA_RETRIES times; extra/unrequested keys are fine as-is
        # since only SATISFACTION_KEYS are ever read. Still no silent
        # accept-and-move-on: if every attempt comes back short, this raises
        # visibly rather than treating missing data as "no change".
        new_satisfaction = None
        last_response = None
        for attempt in range(1, MAX_SCHEMA_RETRIES + 1):
            response = await self.llm.atext_request(
                self.evaluation_prompt.to_dialog(),
                response_format={"type": "json_object"},
                extra_body={"guided_json": SATISFACTION_SCHEMA},
            )
            try:
                parsed = json.loads(response)
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            if all(key in parsed for key in SATISFACTION_KEYS):
                new_satisfaction = parsed
                print(f"$DEBUG$ - evaluate_and_adjust_needs: guided_json OK on attempt {attempt}/{MAX_SCHEMA_RETRIES}")
                break
            print(f"$DEBUG$ - evaluate_and_adjust_needs: guided_json missing keys on attempt {attempt}/{MAX_SCHEMA_RETRIES}, retrying")
            last_response = response
        else:
            raise ValueError(
                f"evaluate_and_adjust_needs: guided_json response missing required "
                f"keys after {MAX_SCHEMA_RETRIES} attempts; last response: {last_response!r}"
            )

        for key in SATISFACTION_KEYS:
            await self.memory.status.update(key, new_satisfaction[key])

        # Log this plan's own outcome now that it's known, attributed to the
        # plan itself (its own start time/steps/target/emotion, stashed by
        # internetagent.py at generation time) rather than whatever plan gets
        # generated next in this same tick.
        agent_id = await self.memory.status.get("id")
        agent_name = await self.memory.status.get("name", default_value=f"Agent_{agent_id}")
        satisfaction_after = {
            "hunger_satisfaction": await self.memory.status.get("hunger_satisfaction"),
            "energy_satisfaction": await self.memory.status.get("energy_satisfaction"),
            "safety_satisfaction": await self.memory.status.get("safety_satisfaction"),
            "social_satisfaction": await self.memory.status.get("social_satisfaction"),
        }
        log_plan_generated(
            agent_id=agent_id,
            agent_name=agent_name,
            sim_time=completed_plan.get("_sim_time_at_start", f"day{sim_day} {sim_time}"),
            plan_target=completed_plan.get("target"),
            steps=completed_plan.get("steps", []),
            current_need=current_need,
            emotion=completed_plan.get("_emotion_at_start"),
            satisfaction_before=completed_plan.get("_satisfaction_at_start"),
            satisfaction_after=satisfaction_after,
        )
