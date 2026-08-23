# Agent Quality Report — Bielik-11B-v3.0-Instruct
_100 agents, ~1h simulated time, 1115 logged steps_

---

## 1. Success Rate

**100% of all steps marked as success** across all action types.

This is a red flag — the model never reports failure regardless of task. Either `success` is always hardcoded to `True` by the agent, or Bielik is not meaningfully evaluating whether the task was actually completed.

---

## 2. Behavioral Diversity

- Mean behavioral entropy per agent: **1.25 / 2.32 bits** (54% of theoretical max)
- **94/100 agents** are dominated by `work` steps
- 3 agents show fully monotone behavior (single action type throughout)
- Step count varies widely: min=4, median=8, max=60 — some agents are doing very little

Agents are more similar than they should be. Over half (54.3%) of agent pairs have cosine similarity >0.9 on their action-type distributions. Most agents just do `work→work→work` with occasional browse/shop.

---

## 3. Step Sequencing

Top transitions:

| Transition | Share |
|---|---|
| work → work | 34.3% |
| work → browse | 10.5% |
| browse → work | 8.4% |
| shop → work | 6.1% |
| browse → browse | 5.6% |

Heavy self-looping on `work` is somewhat realistic (a workday) but the model rarely transitions into leisure/social until later, and then also loops there. Lack of mixed-mode steps suggests the LLM is following its current plan rigidly rather than making varied decisions.

> This looks like correct assesment

---

## 4. Website Choice Coherence

| Action type | Top site | Top site share | Unique sites | Entropy |
|---|---|---|---|---|
| work | gmail.com | 25.6% | 55 | 3.93 bits |
| shop | ceneo.pl | 18.5% | 34 | 4.31 bits |
| social | instagram.com | 20.0% | 18 | 3.59 bits |
| stream | spotify.com | 15.3% | 22 | 4.09 bits |
| call | zoom.us | 50.0% | 4 | 1.75 bits |
| **browse** | google.com | **4.5%** | **109** | **6.33 bits** |

- `work`, `shop`, `social`, `stream` show reasonable coherence — the model picks sensible, recognizable sites with moderate consensus.
- `call` is very consistent (zoom.us dominates), possibly too rigid.
- **`browse` is essentially random** — 109 unique sites with no dominant choice (top site at 4.5%). The model appears to hallucinate arbitrary URLs when the task is open-ended browsing. This is the clearest quality failure.

---

## Summary

| Dimension | Assessment |
|---|---|
| Task success tracking | Broken — always True |
| Behavioral diversity | Low — agents too similar, work-dominated |
| Step sequencing | Rigid self-loops, realistic arc but low variance |
| Website coherence (structured tasks) | Good — sensible site choices for work/shop/social |
| Website coherence (open browsing) | Poor — near-random site selection |
| Monotone agents | 3/100 agents completely stuck in one action type |
