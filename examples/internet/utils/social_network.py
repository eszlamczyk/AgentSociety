"""
Seeds a social graph among the InternetAgent population.

SocietyAgent.StatusAttributes declares "social_network" with default_or_value=[]
(agentsociety/cityagent/societyagent.py), and nothing in this example ever
populates it — confirmed via a validation run's run.log: "No target found in
social network." / "Could not find target for message" were the single
largest step-failure category (283 of 457 total failures), and "Contact with
friends" plans made up 37% of all plans generated that day (up to 57% of one
agent's whole day) because the social need can never be durably satisfied
through a real relationship — it just keeps re-firing. See
metrics/current_changelog.md for the full trace.

social_block.py's FindPersonBlock reads memory.status.get("social_network", [])
and accesses relation.target_id / relation.kind / relation.strength via
attribute access, so entries must be actual SocialRelation instances (not
plain dicts) — matching how memory_config_generator.py's own file-data
loading path constructs them.

Call seed_social_network(engine, agent_ids) once, after engine.init() and
before the simulation's step loop, so every agent's social_network is
populated before its first plan of the day.
"""

import random

from agentsociety.memory.const import RelationType, SocialRelation
from agentsociety.simulation import AgentSociety

# Average number of relations per agent. With N agents, edge probability is
# derived as AVG_DEGREE / (N - 1) (Erdos-Renyi-style), so this scales
# sensibly if the agent count changes.
AVG_DEGREE = 4.0

# Relative likelihood of each relation kind, and the strength range each
# kind samples from (family relations run stronger than colleagues).
_KIND_WEIGHTS = {
    RelationType.FRIEND: 0.55,
    RelationType.FAMILY: 0.15,
    RelationType.COLLEAGUE: 0.30,
}
_STRENGTH_RANGE = {
    RelationType.FRIEND: (0.4, 0.9),
    RelationType.FAMILY: (0.6, 1.0),
    RelationType.COLLEAGUE: (0.3, 0.7),
}


async def seed_social_network(
    engine: AgentSociety,
    agent_ids: list[int],
    avg_degree: float = AVG_DEGREE,
    seed: int | None = None,
) -> None:
    """Populate every agent in agent_ids with a few reciprocal relationships.

    Builds an undirected relationship graph over agent_ids (Erdos-Renyi-style:
    each unordered pair gets an edge independently with probability
    avg_degree / (len(agent_ids) - 1)), assigns each edge a kind and
    strength, and writes each agent's resulting relation list to its
    "social_network" memory field. Relations are reciprocal — if A is B's
    friend, B is A's friend too, same kind and independently-sampled
    strength on each side.
    """
    rng = random.Random(seed)
    n = len(agent_ids)
    if n < 2:
        return
    edge_prob = min(1.0, avg_degree / (n - 1))

    relations: dict[int, list[SocialRelation]] = {aid: [] for aid in agent_ids}
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() >= edge_prob:
                continue
            a, b = agent_ids[i], agent_ids[j]
            kind = rng.choices(
                list(_KIND_WEIGHTS.keys()), weights=list(_KIND_WEIGHTS.values())
            )[0]
            lo, hi = _STRENGTH_RANGE[kind]
            relations[a].append(
                SocialRelation(target_id=b, kind=kind, strength=round(rng.uniform(lo, hi), 2))
            )
            relations[b].append(
                SocialRelation(target_id=a, kind=kind, strength=round(rng.uniform(lo, hi), 2))
            )

    # Guarantee nobody is fully isolated: an agent with zero relations after
    # the random pass gets one FRIEND edge to a random other agent.
    for aid in agent_ids:
        if relations[aid]:
            continue
        other = rng.choice([a for a in agent_ids if a != aid])
        lo, hi = _STRENGTH_RANGE[RelationType.FRIEND]
        strength_a = round(rng.uniform(lo, hi), 2)
        strength_b = round(rng.uniform(lo, hi), 2)
        relations[aid].append(
            SocialRelation(target_id=other, kind=RelationType.FRIEND, strength=strength_a)
        )
        relations[other].append(
            SocialRelation(target_id=aid, kind=RelationType.FRIEND, strength=strength_b)
        )

    for aid in agent_ids:
        await engine.update([aid], "social_network", relations[aid])

    degrees = sorted(len(v) for v in relations.values())
    print(
        f"$DEBUG$ - seed_social_network: {n} agents, "
        f"{sum(degrees) // 2} relations, degree min/median/max="
        f"{degrees[0]}/{degrees[len(degrees) // 2]}/{degrees[-1]}"
    )
