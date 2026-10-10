import asyncio
import inspect
import copy
import os
import time

from dotenv import load_dotenv
load_dotenv()

import agentsociety.vectorstore.vectorstore as _vs
_vs_source = inspect.getsourcefile(_vs.VectorStore)
with open(_vs_source) as _f:
    _vs_code = _f.read()
if "query_points" in _vs_code:
    print("---- THIS IS A PATCHED VERSION ----")
else:
    print("WARNING: unpatched vectorstore detected — simulation may crash (QdrantClient.search removed)")

from agentsociety.cityagent import default, DEFAULT_DISTRIBUTIONS
from agentsociety.cityagent.blocks.economy_block import EconomyBlock, EconomyBlockParams
from agentsociety.cityagent.blocks.mobility_block import MobilityBlockParams
from agentsociety.cityagent.blocks.other_block import OtherBlockParams
from agentsociety.cityagent.blocks.social_block import SocialBlockParams
from agentsociety.configs import (
    AgentsConfig,
    Config,
    EnvConfig,
    ExpConfig,
    LLMConfig,
    MapConfig,
)
from agentsociety.configs.agent import AgentConfig
from agentsociety.configs.exp import WorkflowStepConfig, WorkflowType
from agentsociety.environment import EnvironmentConfig
from agentsociety.llm import LLMProviderType
from agentsociety.simulation import AgentSociety
from agentsociety.storage import DatabaseConfig
from internetagent import InternetAgent, START_WEEKDAY
from internet_memory_config import memory_config_internetagent
from metrics.collect import MetricsCollector
from utils import guardrails
from utils.mobility_block_custom import MobilityBlock as ReliableMobilityBlock
from utils.other_block_custom import OtherBlock as TimeAwareOtherBlock
from utils.social_block_custom import SocialBlock as NetworkAwareSocialBlock
from utils.prompts import TIME_AWARE_SLEEP_PROMPT
from utils.social_network import seed_social_network

config = Config(
    llm=[
        LLMConfig(
            provider=LLMProviderType.PLGrid,
            base_url = None,
            api_key=os.environ["PLGRID_API_KEY"],
            model="speakleash/Bielik-11B-v3.0-Instruct",
            concurrency=2000,
            timeout = 60
        )
    ],
    env=EnvConfig(
        db=DatabaseConfig(
            enabled=True,
            db_type="sqlite",
            pg_dsn=None,
        ),
    ),
    map=MapConfig(
        file_path="../../agentsociety_data/beijing.pb",
    ),
    agents=AgentsConfig(
        citizens=[
            AgentConfig(
                agent_class=InternetAgent,
                number=100,
                memory_config_func=memory_config_internetagent,
                memory_distributions=copy.deepcopy(DEFAULT_DISTRIBUTIONS),
                blocks={
                    ReliableMobilityBlock: MobilityBlockParams(),
                    EconomyBlock: EconomyBlockParams(),
                    NetworkAwareSocialBlock: SocialBlockParams(),
                    TimeAwareOtherBlock: OtherBlockParams(
                        sleep_time_estimation_prompt=TIME_AWARE_SLEEP_PROMPT
                    ),
                },
            )
        ]
    ),  # type: ignore
    exp=ExpConfig(
        name="control group - 100 agents full day",
        workflow=[
            WorkflowStepConfig(
                type=WorkflowType.STEP,
                days=1,
                steps=12,
                ticks_per_step=5 * 60
            ),
        ],
        environment=EnvironmentConfig(
            start_tick=6 * 60 * 60,    # Start at 06:00 AM
        ),
    ),
    logging_level="info"
)
config = default(config)


TICKS_PER_STEP = 5 * 60   # 5 minutes of sim time per step
N_STEPS = 288             # 288 * 5min = 24hr


async def main():
    # Count the vendored blocks' own fallback warnings (random POI category,
    # plan parse failures, ...) alongside our explicit guardrail bumps — see
    # utils/guardrails.py. Must be installed before any block logs anything.
    guardrails.install_log_counter()

    engine = AgentSociety.create(config)
    metrics = None
    try:
        await engine.init()

        citizen_ids = await engine.filter(types=(InternetAgent,))
        await seed_social_network(engine, citizen_ids, seed=0)

        all_pois = engine.environment.map.get_all_pois()
        all_aois = engine.environment.map.get_all_aois()
        aois_with_pois = [a for a in all_aois if len(a["poi_ids"]) > 0]
        print(f"[map] POIs: {len(all_pois)}, AOIs: {len(all_aois)}, AOIs with POIs: {len(aois_with_pois)}")

        metrics = MetricsCollector(out_dir=os.environ.get("METRICS_OUT_DIR", "metrics/output/100_agent_fullday_controll"))

        for step in range(N_STEPS):
            day, tick = engine.environment.get_datetime()
            t0 = time.perf_counter()
            logs = await engine.step(TICKS_PER_STEP)
            wall = time.perf_counter() - t0

            fired = guardrails.snapshot_and_reset()
            metrics.record(tick=tick, wall_time_s=wall, llm_log=logs.llm_log, guardrails=fired)
            fired_note = f" guardrails={sum(fired.values())}" if fired else ""
            print(f"[step {step+1}/{N_STEPS}] tick={tick} wall={wall:.1f}s{fired_note}")

    finally:
        if metrics is not None:
            metrics.close()
        totals = guardrails.totals()
        if totals:
            print("[guardrails] total firings this run: " + ", ".join(
                f"{name}={count}" for name, count in sorted(totals.items(), key=lambda kv: -kv[1])
            ))
        else:
            print("[guardrails] no guardrail fired this run")
        await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
