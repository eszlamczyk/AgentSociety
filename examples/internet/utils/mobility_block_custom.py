"""
Reliable mobility execution.

The vendored MobilityBlock (agentsociety.cityagent.blocks.mobility_block)
dispatches each [mobility] plan step to exactly ONE of three sub-blocks per
tick, chosen by an LLM function call: PlaceSelectionBlock (only *picks* a
destination, never moves the agent), MoveBlock (calls
environment.set_aoi_schedules to actually move), or MobilityNoneBlock (no-op).

check_and_update_step() only checks whether a step's evaluation dict exists
and its consumed_time has elapsed — it has no notion of "did MoveBlock
actually run". So if the dispatcher picks PlaceSelectionBlock and the plan
gets interrupted (e.g. by a need change) before MoveBlock is ever dispatched
on a later tick, the [mobility] step is marked complete having only chosen a
destination — no environment call, no position change. See findings.md
finding #2: 27/45 (100-agent run) and 13/19 (20-agent run) agents with
mobility-containing plans never produced a single position log entry.

MobilityBlock here removes the per-tick dispatcher choice for the two real
sub-actions: every [mobility] step always runs PlaceSelectionBlock followed
immediately by MoveBlock in the same call, so a step can never be marked done
having only selected a destination.

MoveBlock here is an instrumented, de-biased copy of the vendored class (see
current_changelog.md's "0/20 movers on Bielik" investigation): vendored
MoveBlock.forward() classifies the destination via a single LLM call
(PLACE_ANALYSIS_PROMPT) and silently falls back to `"home"` on any parse
failure — and that prompt's own one-shot example response is
`{"place_type": "home"}`. If an agent is already at home (true for every
agent at day-start) and the "home" branch fires — whether the model
genuinely answered "home" or the except-fallback picked it — MoveBlock
returns success without ever calling `environment.set_aoi_schedules`, and
position never changes.

Confirmed directly (not just hypothesized) from a 20-agent Bielik run's
run.log: of 60 place-analysis calls, agent 9's "Take a short walk indoors"
and agent 11's "Commute to school" were both classified "home" — the second
one wrong, school isn't home — and both agents happened to already be home,
so both silently no-op'd with zero position change. Sampling all 60
responses turned up other clear misclassifications too (e.g. "Return home
from workplace" -> "workplace", backwards).

Two independent fixes here:
1. CUSTOM_PLACE_ANALYSIS_PROMPT replaces the vendored prompt's single
   home-only example with three balanced examples (workplace/other/home) so
   the model isn't anchored toward one answer, and says explicitly not to
   default to "home".
2. The home/workplace no-op shortcut (return success without calling
   set_aoi_schedules because the agent's already there) now only fires when
   the step's own intention text plausibly supports that destination (e.g.
   contains "home" for the home branch). If the classification lands on
   "home"/"workplace" AND the agent's already there AND the intention text
   doesn't support it, we no longer trust the classifier's silence-inducing
   answer — the step falls through to the generic destination-search branch
   and the agent actually goes somewhere, rather than a step like "commute
   to school" silently completing as "already home, nothing to do."
"""

import random

import json_repair

from agentsociety.agent import DotDict, FormatPrompt
from agentsociety.cityagent.blocks.mobility_block import (
    MobilityBlock as _VendoredMobilityBlock,
    MoveBlock as _VendoredMoveBlock,
)
from agentsociety.cityagent.blocks.utils import clean_json_response
from agentsociety.logger import get_logger

# Same shape as the vendored PLACE_ANALYSIS_PROMPT, but with three balanced
# worked examples instead of one ({"place_type": "home"}) — that single
# example anchors weaker models toward answering "home" for anything
# ambiguous (confirmed: Bielik classified "Commute to school" as "home").
CUSTOM_PLACE_ANALYSIS_PROMPT = """
As an intelligent analysis system, please determine the type of place the user needs to visit based on their input requirement.
User Plan: {plan}
User requirement: {intention}
Other information:
-------------------------
{other_info}
-------------------------

Your output must be a single selection from {place_list} without any additional text or explanation.
Match the destination to what the requirement actually describes. Do not default to "home" — only
choose it when the requirement is explicitly about going home or returning home.

Examples:
- requirement "Commute to the office" -> {{"place_type": "workplace"}}
- requirement "Walk to the nearest cafe" -> {{"place_type": "other"}}
- requirement "Return home after work" -> {{"place_type": "home"}}

Please respond in json format (Do not return any other text), example:
{{
    "place_type": "workplace"
}}
"""

# Keyword gate for the home/workplace no-op shortcut below: only trust
# "you're already there, nothing to do" when the step's own words plausibly
# mean that destination. Confirmed case this catches: "Commute to school"
# classified as "home" while the agent happened to already be home — without
# this gate that silently no-ops instead of actually sending the agent
# somewhere.
_HOME_KEYWORDS = ("home", "house", "apartment")
_WORKPLACE_KEYWORDS = ("work", "office", "job", "shift", "school", "class", "meeting", "commute")


def _intention_supports(intention: str, keywords: tuple[str, ...]) -> bool:
    text = (intention or "").lower()
    return any(kw in text for kw in keywords)


class MoveBlock(_VendoredMoveBlock):
    def __init__(self, toolbox, agent_memory):
        super().__init__(toolbox, agent_memory)
        self.placeAnalysisPrompt = FormatPrompt(CUSTOM_PLACE_ANALYSIS_PROMPT)

    async def forward(self, context: DotDict):
        agent_id = await self.memory.status.get("id")
        place_knowledge = await self.memory.status.get("location_knowledge")
        known_places = list(place_knowledge.keys())
        places = ["home", "workplace"] + known_places + ["other"]
        intention_text = context["current_step"]["intention"]
        await self.placeAnalysisPrompt.format(
            plan=context["plan_context"]["plan"],
            intention=intention_text,
            place_list=places,
            other_info=self.environment.environment.get("other_information", "None"),
        )
        raw_response = await self.llm.atext_request(
            self.placeAnalysisPrompt.to_dialog(),
            response_format={"type": "json_object"},
        )
        print(f"$DEBUG$ - MoveBlock place-analysis raw response (agent {agent_id}, intention={intention_text!r}): {raw_response!r}")
        try:
            response = clean_json_response(raw_response)
            response = json_repair.loads(response)["place_type"]  # type: ignore
        except Exception as e:
            get_logger().warning(
                f"MobilityBlock: Place Analysis: wrong type of place, raw response: {raw_response}"
            )
            print(f"$DEBUG$ - MoveBlock: place-analysis parse FAILED ({e}), falling back to 'home'. raw={raw_response!r}")
            response = "home"

        # Distrust a home/workplace classification that would otherwise
        # silently no-op (agent's already there) when the step's own words
        # don't support it — fall through to the generic destination-search
        # branch instead so the agent actually moves.
        if response == "home" and not _intention_supports(intention_text, _HOME_KEYWORDS):
            nowPlace = await self.memory.status.get("position")
            home_pos = await self.memory.status.get("home")
            if "aoi_position" in nowPlace and nowPlace["aoi_position"]["aoi_id"] == home_pos["aoi_position"]["aoi_id"]:
                print(f"$DEBUG$ - MoveBlock: distrusting no-op 'home' classification for intention={intention_text!r} (already home, no home-related keywords) — picking a real destination instead")
                response = "other"
        elif response == "workplace" and not _intention_supports(intention_text, _WORKPLACE_KEYWORDS):
            nowPlace = await self.memory.status.get("position")
            work_pos = await self.memory.status.get("work")
            if "aoi_position" in nowPlace and nowPlace["aoi_position"]["aoi_id"] == work_pos["aoi_position"]["aoi_id"]:
                print(f"$DEBUG$ - MoveBlock: distrusting no-op 'workplace' classification for intention={intention_text!r} (already at workplace, no workplace-related keywords) — picking a real destination instead")
                response = "other"

        if response == "home":
            home = await self.memory.status.get("home")
            home = home["aoi_position"]["aoi_id"]
            nowPlace = await self.memory.status.get("position")
            node_id = await self.memory.stream.add(
                topic="mobility",
                description="I returned home",
            )
            if (
                "aoi_position" in nowPlace
                and nowPlace["aoi_position"]["aoi_id"] == home
            ):
                print(f"$DEBUG$ - MoveBlock: agent {agent_id} NO-OP (already home) — no set_aoi_schedules call")
                return {
                    "success": True,
                    "evaluation": "Successfully returned home (already at home)",
                    "to_place": home,
                    "consumed_time": 0,
                    "node_id": node_id,
                }
            await self.environment.set_aoi_schedules(
                person_id=agent_id,
                target_positions=home,
            )
            number_poi_visited = await self.memory.status.get("number_poi_visited")
            number_poi_visited += 1
            await self.memory.status.update("number_poi_visited", number_poi_visited)
            return {
                "success": True,
                "evaluation": "Successfully returned home",
                "to_place": home,
                "consumed_time": 45,
                "node_id": node_id,
            }
        elif response == "workplace":
            work = await self.memory.status.get("work")
            work = work["aoi_position"]["aoi_id"]
            nowPlace = await self.memory.status.get("position")
            node_id = await self.memory.stream.add(
                topic="mobility",
                description="I went to my workplace",
            )
            if (
                "aoi_position" in nowPlace
                and nowPlace["aoi_position"]["aoi_id"] == work
            ):
                print(f"$DEBUG$ - MoveBlock: agent {agent_id} NO-OP (already at workplace) — no set_aoi_schedules call")
                return {
                    "success": True,
                    "evaluation": "Successfully reached the workplace (already at the workplace)",
                    "to_place": work,
                    "consumed_time": 0,
                    "node_id": node_id,
                }
            await self.environment.set_aoi_schedules(
                person_id=agent_id,
                target_positions=work,
            )
            number_poi_visited = await self.memory.status.get("number_poi_visited")
            number_poi_visited += 1
            await self.memory.status.update("number_poi_visited", number_poi_visited)
            return {
                "success": True,
                "evaluation": "Successfully reached the workplace",
                "to_place": work,
                "consumed_time": 45,
                "node_id": node_id,
            }
        elif response in known_places:
            the_place = place_knowledge[response]["id"]
            nowPlace = await self.memory.status.get("position")
            node_id = await self.memory.stream.add(
                topic="mobility",
                description=f"I went to {response}",
            )
            if (
                "aoi_position" in nowPlace
                and nowPlace["aoi_position"]["aoi_id"] == the_place
            ):
                print(f"$DEBUG$ - MoveBlock: agent {agent_id} NO-OP (already at {response}) — no set_aoi_schedules call")
                return {
                    "success": True,
                    "evaluation": f"Successfully reached {response} (already at {response})",
                    "to_place": the_place,
                    "consumed_time": 0,
                    "node_id": node_id,
                }
            await self.environment.set_aoi_schedules(
                person_id=agent_id,
                target_positions=the_place,
            )
            number_poi_visited = await self.memory.status.get("number_poi_visited")
            number_poi_visited += 1
            await self.memory.status.update("number_poi_visited", number_poi_visited)
            return {
                "success": True,
                "evaluation": f"Successfully reached {response}",
                "to_place": the_place,
                "consumed_time": 45,
                "node_id": node_id,
            }
        else:
            next_place = context.get("next_place", None)
            nowPlace = await self.memory.status.get("position")
            node_id = await self.memory.stream.add(
                topic="mobility",
                description=f"I went to {next_place}",
            )
            if next_place is not None:
                await self.environment.set_aoi_schedules(
                    person_id=agent_id,
                    target_positions=next_place[1],
                )
            else:
                aois = self.environment.map.get_all_aois()
                aois_with_pois = [a for a in aois if len(a["poi_ids"]) > 0]
                if not aois_with_pois:
                    return {
                        "success": False,
                        "evaluation": "No AOIs with POIs available in map",
                        "consumed_time": random.randint(1, 30),
                        "node_id": node_id,
                    }
                r_aoi = random.choice(aois_with_pois)
                r_poi = random.choice(r_aoi["poi_ids"])
                poi = self.environment.map.get_poi(r_poi)
                next_place = (poi["name"], poi["aoi_id"])
                await self.environment.set_aoi_schedules(
                    person_id=agent_id,
                    target_positions=next_place[1],
                )
            number_poi_visited = await self.memory.status.get("number_poi_visited")
            number_poi_visited += 1
            await self.memory.status.update("number_poi_visited", number_poi_visited)
            return {
                "success": True,
                "evaluation": f"Successfully reached the destination: {next_place}",
                "to_place": next_place[1],
                "consumed_time": 45,
                "node_id": node_id,
            }


class MobilityBlock(_VendoredMobilityBlock):
    def __init__(self, toolbox, agent_memory, block_params=None):
        super().__init__(toolbox, agent_memory, block_params)
        # swap in the instrumented MoveBlock and re-register it with the
        # dispatcher (same class name -> same dispatcher key, so this
        # cleanly replaces rather than duplicates the vendored entry) —
        # same pattern as utils/other_block_custom.py's OtherBlock.
        self.move_block = MoveBlock(toolbox, agent_memory)
        self.dispatcher.register_blocks(
            [self.place_selection_block, self.move_block, self.mobility_none_block]
        )

    async def forward(self, agent_context: DotDict):
        self.trigger_time += 1
        context = agent_context | self.context

        select_result = await self.place_selection_block.forward(context)
        print(f"$DEBUG$ - PlaceSelectionBlock result: success={select_result.get('success')} evaluation={select_result.get('evaluation')!r}")
        if not select_result.get("success", True):
            return self.OutputType(
                success=False,
                evaluation=select_result.get(
                    "evaluation", "Failed to select a destination"
                ),
                consumed_time=select_result.get("consumed_time", random.randint(1, 30)),
                node_id=select_result.get("node_id"),
            )

        # place_selection_block wrote context["next_place"] in place; move_block
        # reads it from the same context object.
        move_result = await self.move_block.forward(context)

        consumed_time = select_result.get("consumed_time", 0) + move_result.get(
            "consumed_time", 0
        )
        return self.OutputType(
            success=move_result.get("success", True),
            evaluation=move_result.get("evaluation", "Moved"),
            consumed_time=consumed_time,
            node_id=move_result.get("node_id"),
        )
