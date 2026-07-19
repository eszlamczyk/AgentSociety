"""
Time-aware duration estimate for generic ("other"-typed) plan steps.

The vendored OtherNoneBlock (agentsociety.cityagent.blocks.other_block) uses
TIME_ESTIMATE_PROMPT to guess a step's consumed_time from the intention text
alone — no current sim time, no notion of how much of the day has already
passed. It's also the dominant path for "other"-typed steps (SleepBlock only
handles steps the LLM dispatcher explicitly labels "sleep"; prep steps like
"Prepare for sleep" / "Check social media" / "Turn off lights" go through
OtherNoneBlock). Combined with the fallback of `random.randint(1, 180)` on any
parse failure, this is a major source of the fast, near-duplicate replanning
in findings.md finding #1 — plans built from several of these steps can
complete in well under an hour regardless of what they're actually about.

OtherNoneBlock/OtherBlock here just add current sim time to the same prompt
and wire the dispatcher to the new sub-block. Everything else (SleepBlock,
the block-selection dispatcher itself) is unchanged.
"""

import random

from agentsociety.agent import DotDict, FormatPrompt
from agentsociety.cityagent.blocks.other_block import (
    OtherBlock as _VendoredOtherBlock,
    OtherNoneBlock as _VendoredOtherNoneBlock,
)
from agentsociety.cityagent.blocks.utils import clean_json_response
from agentsociety.logger import get_logger

import json_repair

TIME_AWARE_TIME_ESTIMATE_PROMPT = """As an intelligent agent's time estimation system, please estimate the time needed to complete the current action based on the overall plan and current intention.

Overall plan:
{plan}

Current action: {intention}
Current simulated time: {current_time}
Current emotion: {emotion_types}

Use the current simulated time as context — e.g. a "quick check" first thing
in the morning should be short, but do not assume every action is short just
because it's a small step in a longer plan.

Examples:
- "Learn programming": {{"time": 120}}
- "Watch a movie": {{"time": 150}}
- "Play mobile games": {{"time": 60}}
- "Read a book": {{"time": 90}}
- "Exercise": {{"time": 45}}
- "Prepare for sleep": {{"time": 15}}
- "Turn off lights before bed": {{"time": 5}}
- "Check social media": {{"time": 10}}

Please return the result in JSON format (Do not return any other text), the time unit is [minute], example:
{{
    "time": 10
}}
"""


class OtherNoneBlock(_VendoredOtherNoneBlock):
    def __init__(self, toolbox, agent_memory=None):
        super().__init__(toolbox, agent_memory)
        self.guidance_prompt = FormatPrompt(template=TIME_AWARE_TIME_ESTIMATE_PROMPT)

    async def forward(self, context: DotDict):
        sim_day, sim_time = self.environment.get_datetime(format_time=True)
        await self.guidance_prompt.format(
            plan=context["plan_context"]["plan"],
            intention=context["current_step"]["intention"],
            current_time=f"day{sim_day} {sim_time}",
            emotion_types=await self.memory.status.get("emotion_types"),
        )
        result = await self.llm.atext_request(
            self.guidance_prompt.to_dialog(), response_format={"type": "json_object"}
        )
        result = clean_json_response(result)
        node_id = await self.memory.stream.add(
            topic="other",
            description=f"I {context['current_step']['intention']}",
        )
        try:
            parsed = json_repair.loads(result)
            consumed_time = int(parsed["time"])
            return {
                "success": True,
                "evaluation": f'Finished executing {context["current_step"]["intention"]}',
                "consumed_time": consumed_time,
                "node_id": node_id,
            }
        except Exception as e:
            get_logger().warning(
                f"An error occurred while evaluating the response at parse time: {str(e)}, original result: {result}"
            )
            return {
                "success": True,
                "evaluation": f'Finished executing {context["current_step"]["intention"]}',
                "consumed_time": random.randint(1, 180),
                "node_id": node_id,
            }


class OtherBlock(_VendoredOtherBlock):
    def __init__(self, toolbox, agent_memory, block_params=None):
        super().__init__(toolbox, agent_memory, block_params)
        # swap in the time-aware OtherNoneBlock and re-register it with the
        # dispatcher (same class name -> same dispatcher key, so this cleanly
        # replaces rather than duplicates the vendored entry).
        self.other_none_block = OtherNoneBlock(toolbox, agent_memory)
        self.dispatcher.register_blocks([self.sleep_block, self.other_none_block])
