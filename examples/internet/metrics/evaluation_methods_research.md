# Judge synthetic footprints against real noise floors

**Bottom line:** No single standard exists for showing that LLM-simulated digital footprints can stand in for real telecom, network and mobility data. The state of the art is a layered recipe. First, compute per-user statistics on both sides and compare their histograms with Jensen–Shannon divergence (JSD), plus Wasserstein or KS for continuous quantities. Second, add multivariate and classifier two-sample tests (MMD/energy distance, C2ST) and fidelity/diversity metrics (density/coverage, α-precision/β-recall). Third, check downstream utility: train on synthetic and test on real (TSTR), and check that the ranking of methods is preserved. For entity-resolution (ER) research one test matters more than the others: **the simulator must reproduce how identifiable real users are**. That means matching the unicity curve ε_p (real CDRs: **ε_4 > 0.95, ε_2 > 0.5** at antenna and 1-hour resolution), the gap between within-user and between-user distances, and the relative ranking of simple and deep linkers. Fidelity to marginal distributions is not enough. Two traps carry over directly to this project. First, an independent 2026 study found **AgentSociety-style simulators are "narratively plausible but not empirically realistic"**: they fail on trip lengths, OD flows, dwell times and transitions ([arXiv 2606.13835](https://arxiv.org/abs/2606.13835)). Second, raw distances computed at ~100 agents cannot be interpreted on their own. Every number therefore has to be read against three references: a real-vs-real noise floor at n ≈ 100, sim-vs-sim seed spread, and naive baselines. And it only means something after the dense 5-minute simulated ground truth has been degraded through the same observation model that produced the real data. The rest of this report gives the metrics, formulas, reference values and tools for each category, then a step-by-step protocol and checklist for when the real dataset arrives.

> **Verification legend.** Claims marked **[UNVERIFIED]** were flagged in the research notes as coming from secondary summaries, search snippets, prior knowledge that was not re-fetched, or text that could not be fully read. Check them in the primary source before quoting them in the thesis. Statements marked *(inference)* are recommendations synthesized from the cited mechanisms, not findings from a single paper.

---

## 1. Mobility: a shared JSD suite, with spatial joints scoring ~10× worse than scalars

### Metric suite and definitions

Individual-mobility generator papers share one evaluation recipe. For real and synthetic data separately, they compute a per-user or per-record statistic, histogram it, and report JSD (lower is better). JSD is defined as **JSD(P‖Q) = H(M) − ½[H(P) + H(Q)], with M = ½(P + Q)**. A systematic review counts JSD as by far the most-used similarity measure (~50+ uses), with KL second (~20) and EMD, RMSE, Kendall's τ, SRMSE and top-k F1 used occasionally. It also notes that **no reviewed paper assessed diversity** and that downstream-task evaluations are rare ([Kapp et al. review](https://arxiv.org/html/2407.09198)). Watch the units: `scipy.spatial.distance.jensenshannon` returns the JS *distance* (the square root of the divergence), and the result depends on the log base ([SciPy](https://docs.scipy.org/doc/scipy/reference/stats.html)).

| Metric | Definition | Origin / users |
|---|---|---|
| **Distance** | Distance between consecutive locations. Some papers use cumulative distance per user-day, so state which. | MoveSim lineage ([2306.09381](https://arxiv.org/pdf/2306.09381), [Geo-Llama](https://arxiv.org/pdf/2408.13918)) |
| **Radius of gyration** r_g | r_g = sqrt( (1/n) Σ_i ‖r_i − r_cm‖² ): RMS distance of visited points from their centroid | MoveSim lineage, CoPB, MIRAGE |
| **k-radius of gyration** r_g^(k) | r_g computed over the k most-visited locations only. r_g^(k) ≈ r_g marks a "k-returner"; r_g^(k) ≪ r_g marks a "k-explorer" | [Pappalardo et al. 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4569739) |
| **Duration** | Dwell time per location visit | MoveSim lineage |
| **DailyLoc** | Number of distinct locations per user per day | MoveSim lineage, CoPB |
| **G-rank / I-rank** | Visit-frequency distribution of the top-100 locations: global (G) or per-user averaged (I) | MoveSim lineage |
| **locfreq** | Share of visits per spatial cell | [CoPB](https://arxiv.org/html/2402.09836) |
| **odSim** | MSE between origin–destination transition-probability matrices | CoPB |
| **itdType / itdNum / itdErr** | Duration-weighted time share per trip purpose (JSD); number of intentions per day; error against a "typical day" built from a 30-min-slot majority vote | CoPB |
| **SD / SI** | Step distance and step interval between consecutive decision steps | [LLMob](https://arxiv.org/html/2402.14744) |
| **DARD** | Histogram of (time-of-day bin, activity category) tuples. LLMob uses 144 ten-minute bins | LLMob |
| **STVD** | Histogram of (time bin, lat, lon) tuples | LLMob |
| **Density / Trip / Length / Pattern** | Grid-density JSD; JSD of trip origin/destination; JSD of trip length; F1 over the top-n grid cells (16×16 grid) | [DiffTraj](https://arxiv.org/html/2304.11582) |

*Gap:* the original MoveSim (KDD'20) paper was not retrieved, so exact bin widths come from follow-up papers. CoPB does not state its bin widths or grid size, and DiffTraj does not state top-n ([CoPB](https://arxiv.org/html/2402.09836), [DiffTraj](https://arxiv.org/html/2304.11582)).

### Reference values show where "good" sits

Per-user scalar metrics reach JSD ≈ 0.01–0.07 for strong models, while joint spatial or spatio-temporal histograms stay around 0.3–0.6 even for state-of-the-art models. So expectations must be set **per metric, not globally**.

| Paper / data | Method | Selected JSDs |
|---|---|---|
| CoPB, Tencent / **ChinaMobile cell-tower** Beijing ([CoPB](https://arxiv.org/html/2402.09836)) | CoPB | radius 0.019/0.024, dayloc 0.029/0.066, g-rank 0.009/0.004, itdType 0.034/0.047, itdErr 0.194/0.247, **locfreq 0.282/0.267**, odSim 5.3e-5 |
| same | Vanilla LLM | radius 0.113/0.048, **dayloc 0.465/0.209**, itdErr 0.578/0.642, locfreq 0.603/0.436 |
| LLMob, Tokyo, **100 users**, 10-min ([LLMob](https://arxiv.org/html/2402.14744)) | LLMob-E | SD 0.053, SI 0.046, DARD 0.125, **STVD 0.559** |
| same | DeepMove / TrajGAIL | SD 0.008 / 0.128; DARD 0.534 / 0.598 |
| DiffTraj, Chengdu ([DiffTraj](https://arxiv.org/html/2304.11582)) | DiffTraj vs random perturbation | Density 0.0055 vs 0.0698; Length 0.0169 vs 0.2337; Pattern F1 0.823 vs 0.493 |

The **closest analogue to this project** is CoPB's ChinaMobile setting: 1,246 users with cellular base-station traces, trip purposes inferred from the nearest POI category, and only 200 seven-day LLM trajectories ([CoPB](https://arxiv.org/html/2402.09836)). Together with LLMob's DARD it maps directly onto "positions + trip purposes + antenna connections". Note the vanilla-LLM DailyLoc failure, a JSD of 0.465 against CoPB's 0.029. This is the signature you should expect if agents produce too many or too few stops.

### Classic mobility laws as sanity checks, and which survive a one-day run

The large-scale laws are mostly multi-week phenomena:

- **Gonzalez et al. 2008** (100k phone users, 6 months): heavy-tailed jumps and r_g, with each person's movement scaled by their own characteristic r_g ([arXiv 0806.1256](https://arxiv.org/abs/0806.1256)). The fitted values β ≈ 1.75 for jump size, Δr0 = 1.5 km, r_g0 = 5.8 km and β_r ≈ 1.65 are **[UNVERIFIED — secondary summaries]** ([review 2008.05611](https://arxiv.org/pdf/2008.05611)).
- **Song et al. 2010 (EPR):** exploration probability P_new = ρS^−γ with γ = 0.21; distinct locations grow as S(t) ~ t^0.6; visitation frequency follows Zipf f_k ~ k^−1.2 ([arXiv 1010.0436](https://arxiv.org/pdf/1010.0436)).
- **Predictability:** the 93% upper bound is disputed. Later work gives 81–85% once reachability is accounted for, and a 2019 critique questions the estimator ([PubMed](https://pubmed.ncbi.nlm.nih.gov/20167789/), [1608.01939](https://arxiv.org/pdf/1608.01939), [PMC7514921](https://pmc.ncbi.nlm.nih.gov/articles/PMC7514921/)).
- **Visitation law:** visitors ∝ (distance × frequency)^−2 ([Schläpfer 2021](https://www.isi.it/wp-content/uploads/2024/01/the-universal-visitation-law-of-human-mobility_s41586-021-03480-9.pdf)).

A single simulated day cannot test S(t), long-run Zipf, predictability or the visitation law in their original form. The best single-day check is **Schneider et al. 2013**: only **17 daily-mobility motifs cover up to 90% of person-days** across survey and phone datasets ([MIT DSpace](https://dspace.mit.edu/handle/1721.1/89420)).

Testable one-day analogues *(inference)*:

- the JSD of daily-motif frequencies between real and simulated person-days;
- intra-day jump-length and r_g distributions;
- the share of time spent at the top-1 and top-2 locations, as a proxy for preferential return;
- the ratio r_g^(2)/r_g, as a returner/explorer proxy.

An LLM population that produces many complex multi-stop chains will show inflated DailyLoc and motif-JSD. Exact per-motif frequencies from Schneider were not retrieved, so compute them from the real data.

### Recommended comparison and tools

*(inference, from the notes)*

- **Spatial unit:** use antenna Voronoi cells on both sides.
- **Binning:** fix bins on the pooled real data, log-spaced for distances and r_g.
- **Statistics:** report JSD together with KS and Wasserstein-1 on the continuous per-user quantities.
- **Uncertainty:** bootstrap CIs over users and over simulation seeds.
- **Sensitivity:** report results at antenna level and at a coarser district level. locfreq and OD JSD rise sharply with finer grids.

**Tools:**

- [scikit-mobility](https://scikit-mobility.github.io/scikit-mobility/reference/measures.html) implements radius_of_gyration, k_radius_of_gyration, jump_lengths, random/uncorrelated/real_entropy, frequency_rank, waiting_times, home_location and visits_per_time_unit. Its EPR model family is a cheap mechanistic baseline.
- trackintel, LibCity and MobilityDB are relevant but were **[UNVERIFIED — not researched]**.
- The [MIRAGE](https://arxiv.org/html/2409.13790) "Beyond Datasaurus" paper shows that matched summary statistics can hide unrealistic trajectories, and that model rankings flip depending on which downstream predictor is used. Always pair JSD with a task.

---

## 2. Temporal activity: JSD misses a commute that is 30 minutes late

The temporal metrics used in generator papers are JSD on step intervals and dwell times, and JSD on time-of-day × activity histograms: LLMob DARD with 144 ten-minute bins, CoPB itdType/itdErr with 30-minute slots ([LLMob](https://arxiv.org/html/2402.14744), [CoPB](https://arxiv.org/html/2402.09836)). MIRAGE reports JSD on inter-event "Interval" and on "Category". Its ablation found that switching from raw timestamps to temporal distances made similarity 15.2% worse ([MIRAGE](https://arxiv.org/html/2409.13790)).

JSD and KL have a structural weakness here. **They ignore the distance between bins**, so a morning peak shifted by 30 minutes scores the same as a random shift. Wasserstein/EMD captures that shift ([review](https://arxiv.org/html/2407.09198)). KL is also asymmetric and undefined for empty reference bins.

Classic temporal statistics come from Goh & Barabási, who separated burstiness from memory. For human dynamics, memory is weak and burstiness comes from the inter-event time distribution ([arXiv physics/0610233](https://arxiv.org/abs/physics/0610233)). The standard formulas are below. They are **[UNVERIFIED — formulas not read on the fetched page; check the PDF]**:

- **Burstiness:** B = (σ_τ − m_τ)/(σ_τ + m_τ) ∈ [−1, 1]. B = −1 is periodic, 0 is Poisson, and values near 1 are bursty.
- **Memory:** M = (1/(n−1)) Σ (τ_i − m₁)(τ_{i+1} − m₂)/(σ₁σ₂).

The time-series literature adds:

- **ACD:** the difference in autocorrelation between real and synthetic series;
- **MDD:** a per-time-step histogram difference using the real data's bin centers;
- **SD and KD:** skewness and kurtosis differences;

all from [TSGBench](https://arxiv.org/html/2309.03755v2). DoppelGANger's temporal-fidelity number is the **MSE between average autocorrelation curves**: DG 0.0009 versus HMM 0.6030 on Wikipedia traffic ([ar5iv 1909.13403](https://ar5iv.labs.arxiv.org/html/1909.13403)).

**Recommended for a 5-min-step simulator** *(inference)*: build 288-bin (5-min) and 24-bin (hourly) curves on both sides for:

- the share of agents away from home;
- trips started;
- antenna-connection events;
- web/IP events;
- chat messages;
- the share of agents in each trip purpose.

Compare each curve with JSD *and* Wasserstein-1. Use KS with effect sizes on per-user departure times and dwell times. Compute B per user on web and chat inter-event times.

One critical caveat: **telecom event times are driven by phone usage, not by movement**. Compare simulated antenna-event inter-event times with real ones only after the observation model of Section 8 is applied. Otherwise, compare stay segments after running the same stay-detection on both sides. No source in the notes gives canonical real values of B or M for individual CDR inter-event times, so measure them on the real data.

---

## 3. Network traffic and web/app usage: per-field distances, rank preservation and diversity

### Header and flow fidelity

Network-traffic generation has **no standard evaluation**. A 2026 survey names two common strategies: TSTR/TRTS classifiers, and distribution distances ([arXiv 2603.08901](https://arxiv.org/pdf/2603.08901)). The working consensus has three parts:

- **Categorical fields** (IP, port, protocol): JSD, total variation distance (TV) or Hellinger distance.
- **Continuous or temporal fields** (flow size, duration, inter-arrival): EMD/W1.
- **Downstream:** TSTR accuracy, plus Spearman rank preservation of candidate algorithms.

Key systems:

- **NetShare** (SIGCOMM'22) reports 46% better fidelity than baselines and preservation of downstream rank ordering ([NSF PAR](https://par.nsf.gov/servlets/purl/10406016)). Its exact per-field list and EMD normalization are **[UNVERIFIED — full text not opened]**. A later NSDI'26 deck describes the standard protocol: JSD + EMD on src/dst IP, ports, protocol and TTL, plus EMD for temporal fields ([slides](https://www.usenix.org/system/files/nsdi26_slides-lu-runwei.pdf)). The [NetShare repo](https://github.com/netsharecmu/NetShare) integrates SDMetrics and a side-by-side dashboard.
- **DoppelGANger** (IMC'20):
  - W1 on bandwidth CDFs: DG 0.68/0.74 versus HMM 3.46/7.98.
  - TSTR reaches ~80% of real-data accuracy.
  - Spearman rank preservation: GCUT 1.00 for DG, 0.01 for HMM.
  - The paper warns that **low-diversity generators trivially "preserve" rankings**, because every predictor scores alike on them ([ar5iv](https://ar5iv.labs.arxiv.org/html/1909.13403)).
- **NetSSM** uses JSD, TVD and Hellinger at attribute and header level ([2503.22663](https://arxiv.org/pdf/2503.22663)).
- **CPT-GPT** (cellular control plane) uses the KS statistic on per-state sojourn times ([2411.07345](https://arxiv.org/pdf/2411.07345)).
- **TrafficLLM** uses JSD plus classifier F1 ([2504.04222](https://arxiv.org/html/2504.04222v1)).
- **TrafficGPT** argues that NLP metrics (BLEU, perplexity) do not capture traffic fidelity, and it reports malformed TLS packets. **Protocol and format validity is therefore its own metric for LLM generators** ([2403.05822](https://arxiv.org/pdf/2403.05822)).

### Web/app behavior

The closest public schema match to this simulator is the **Tsinghua App Usage dataset**: 1,000 users, 2,000 apps and 9,800 base stations over one week in Shanghai, with fields user, timestamp, base-station ID, app ID and bytes, plus POI counts per base station ([project page](https://fi.ee.tsinghua.edu.cn/appusage/)). It is non-commercial use only. **LSApp** has 292 users and ~600k records, but its session count depends heavily on the inactivity cutoff: 61,632 sessions at 5 min in the original paper, against 76,247 reported elsewhere ([IEEE DataPort](https://ieee-dataport.org/documents/lsapp-large-dataset-sequential-mobile-app-usage), [2101.03394](https://arxiv.org/pdf/2101.03394)). That makes the **sessionization threshold a hidden degree of freedom** that must be identical on both sides. Other behavioral anchors:

- Revisitation: a simple model explains 92% of app-use variability ([Jones et al. UbiComp'15](https://researchportal.bath.ac.uk/en/publications/revisitation-analysis-of-smartphone-app-use/)).
- About 200 distinct apps cover more than 97% of Tsinghua users ([2605.29863](https://arxiv.org/pdf/2605.29863)).
- No published Zipf exponent or per-user entropy values for domain or app popularity were found. **Compute them on the real data.**

**Recommended metric set** *(inference)*:

| Metric | Formula / method | Comparison |
|---|---|---|
| Domain/app rank-frequency | MLE Zipf exponent; Jaccard@k; rank-biased overlap or Spearman on the shared top-k | Exponent difference against the noise floor |
| Per-user entropy | H_u = −Σ_i p_i log p_i over eTLD+1 domains, IP /24 or ASN, and cells | KS/W1 on the distribution across users |
| Distinct items per user | count | KS/W1 |
| Hour-of-day profile | 24- or 288-bin histogram | JSD + W1 |
| Session length and inter-session gap | Same inactivity threshold on both sides | KS/W1 on log values |
| Revisitation | Share of visits to already-seen items; inter-revisit time | KS |
| Categorical fields | Domain, IP prefix, cell, category | JSD/TV |
| Per-user feature correlations | CDF of per-user Pearson correlation (DoppelGANger-style) | KS |
| Diversity / mode collapse | Number of unique values, tail of rank-frequency, coverage of real categories | Ratio to real at n = 100 |
| Format validity | Valid IPs, ASN/domain consistency, plausible bytes | Pass rate |

LLM agents tend toward a small set of "famous" domains. **Diversity and coverage checks matter as much as fidelity**, and they must be read before any rank-preservation result.

---

## 4. Social/communication graph: compare at matched size, or the distance is meaningless

### Metrics and reference values

Three families are used.

**(a) Scalar and distributional statistics:**

- in/out degree and strength;
- reciprocity;
- clustering, as a z-score against a degree-preserving null;
- assortativity and k-core;
- the tie-weight distribution;
- the **Onnela overlap–weight curve**, with overlap O_ij = n_ij / ((k_i − 1) + (k_j − 1) − n_ij), where n_ij is the number of common neighbors.

**(b) MMD over sets of per-graph statistic distributions**, following GraphRNN: MMD² = E k(x,x′) + E k(y,y′) − 2E k(x,y) over degree, clustering and 4-orbit distributions. Degree and clustering use an EMD-based kernel; orbit counts use an RBF kernel ([GraphRNN](https://ar5iv.labs.arxiv.org/html/1802.08773)).

**(c) Alignment-free graph distances.**

Reference values from phone networks:

- **Onnela et al. 2007** (4.6M nodes, 18 weeks, ~20% population coverage) ([PMC1863470](https://pmc.ncbi.nlm.nih.gov/articles/PMC1863470)):
  - giant component 84.1%;
  - degree P(k) ∝ (k + 10.9)^−8.4;
  - tie weight w₀ = 280 s, γ_w = 1.9;
  - **overlap increases with tie strength for ~95% of links**;
  - removing weak ties first fragments the network at f_c = 0.80; removing strong ties first gives no transition.
- **Karsai et al. 2011:** single-link inter-event times P(τ) ~ τ^−0.7 over 3.5 decades. Burstiness slows spreading more than weight-topology correlations do ([ar5iv 1006.2125](https://ar5iv.arxiv.org/html/1006.2125)).
- **Saramäki et al. 2014:** egos keep a persistent "social signature", the rank-ordered share of calls across alters ([Oxford Martin](https://www.oxfordmartin.ox.ac.uk/publications/persistence-of-social-signatures-in-human-communication)).
- **Mac Carron et al. 2016:** layered ego structure consistent with Dunbar layers ([1604.02400](https://arxiv.org/abs/1604.02400)). Exact layer sizes, reciprocity and assortativity reference values, and co-location/communication overlap numbers were **not retrieved**.

### Choosing distances and handling size

Tantardini et al. compared network-comparison methods ([Sci Rep 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6879644/)):

- Methods that need node correspondence (DeltaCon, Euclidean) do not apply when the node sets differ.
- With matched size and density, almost every method works.
- **Across different sizes and densities, graphlet methods win:** DGCD-129 (directed) reaches AUPR 0.928 and GCD-11 (undirected) 0.688. NetLSD manages 0.386, against a random baseline of 0.322.

MMD rankings flip with kernel and σ choices, so report those choices and run a sensitivity sweep ([O'Bray et al. ICLR'22](https://arxiv.org/pdf/2106.01098)). Average within-ensemble graph distance depends on N ([2008.02415](https://arxiv.org/pdf/2008.02415)). Tools: NetworkX/igraph for statistics; [netrd](https://netrd.readthedocs.io/en/latest/distance.html) for Portrait Divergence and NetLSD (NetLSD treats graphs as undirected and unweighted, and Hamming distance needs equal N).

**Protocol for 100 agents against a large real graph** *(inference)*:

1. Build a reference distribution from many ~100-node real subgraphs. Use snowball/BFS samples or induced subgraphs on activity-matched users, because uniform node sampling destroys clustering.
2. Report the simulated value as a percentile or z-score within that distribution.
3. Normalize clustering and path length by same-N configuration-model nulls.
4. Use DGCD-129/GCD-11 for whole-graph comparison.
5. Apply the same edge filters on both sides, for example reciprocal-only ties.

**One simulated day yields far fewer weak ties than an 18-week window.** Compare against one-day real slices, not against multi-week graphs.

Two cross-modal checks are especially useful for this project:

- the Jaccard or correlation between the *co-location graph* (agents sharing an antenna in the same time window) and the *chat graph*, on both sides;
- per-link inter-message burstiness, B per edge.

---

## 5. General frameworks: marginals, then multivariate tests, then classifiers, then fidelity/diversity

### Distribution distances

| Distance | Definition | Use when | Tool |
|---|---|---|---|
| KS | sup_x \|F_P(x) − F_Q(x)\|, in [0, 1] | Continuous per-user quantities. Report the statistic; p-values become tiny at large n | `scipy.stats.ks_2samp`; SDMetrics KSComplement |
| Wasserstein-1 | ∫\|F_P − F_Q\|dx, in the feature's own units | Heavy tails (on log1p values); shifted peaks | `scipy.stats.wasserstein_distance` |
| TV | ½Σ\|p_i − q_i\| | Categorical | SDMetrics TVComplement |
| JSD | see Section 1 | Binned or categorical; bounded and symmetric; sensitive to binning | `scipy.spatial.distance.jensenshannon` (returns the square root) |
| MMD | ‖μ_P − μ_Q‖ in an RKHS, with an unbiased U-statistic estimator and permutation null | Multivariate per-user vectors | MMDAgg ([Schrab et al. JMLR'23](https://jmlr.org/papers/v24/21-1289.html)) aggregates over bandwidths, avoiding the median heuristic |
| Energy distance | 2E\|X−Y\| − E\|X−X′\| − E\|Y−Y′\| | Multivariate, no bandwidth to choose | `dcor`, `hyppo` **[UNVERIFIED — background]** ([Székely & Rizzo](https://doi.org/10.1016/j.jspi.2013.03.018)) |

The SDMetrics QualityReport has two layers ([docs](https://docs.sdv.dev/sdmetrics/data-metrics/quality.md)):

- **Column Shapes:** KS or TV complement per column.
- **Column Pair Trends:** correlation or contingency similarity per pair. Since version 0.27 it drops pairs with |Pearson| ≤ 0.5 or Cramér's V ≤ 0.3. Weak behavioral correlations therefore vanish from the score, so disclose or disable this filter.

Its sequence-aware MSAS metrics fit per-user event logs directly ([SequenceLengthSimilarity](https://docs.sdv.dev/sdmetrics/data-metrics/quality/sequencelengthsimilarity), [StatisticMSAS](https://docs.sdv.dev/sdmetrics/data-metrics/quality/statisticmsas), [InterRowMSAS](https://docs.sdv.dev/sdmetrics/data-metrics/quality/interrowmsas)):

- SequenceLengthSimilarity compares per-user sequence lengths;
- StatisticMSAS compares a per-sequence statistic;
- InterRowMSAS compares consecutive-row differences.

### Classifier two-sample tests

**C2ST** trains a classifier to separate real (label 1) from synthetic (label 0) samples and uses held-out accuracy as the test statistic. Under H0, accuracy is approximately N(½, 1/(4n_te)) **[UNVERIFIED — background]** ([Lopez-Paz & Oquab](https://arxiv.org/abs/1610.06545)). Related scores:

- **pMSE** = mean (p̂_i − c)², where c is the synthetic share of the pooled data ([Snoke et al.](https://arxiv.org/abs/1604.06651)) **[UNVERIFIED — background]**;
- the TimeGAN/TSGBench **discriminative score** |acc − 0.5|, from a GRU sequence classifier ([TSGBench](https://arxiv.org/html/2309.03755v2)).

Design *(inference)*:

- Train at user level with stratified k-fold, and balance the two sides to equal n.
- Train two model families, linear and GBDT. A gap between them shows whether marginals or interactions give the simulation away.
- Report AUC with a bootstrap CI and a permutation p-value.
- Read the GBDT discriminator's SHAP values, then drop the top feature and retrain, repeatedly. This **leave-top-k-out AUC curve** shows whether one artifact or a diffuse mismatch drives detectability.

**Harmonize rounding, units, time zones and ID formats first**, or the AUC will be ≈1 for trivial reasons.

### Fidelity versus diversity

These metrics split realism into "are synthetic users plausible?" and "do synthetic users cover the real population?":

- **Density and coverage** ([Naeem et al. ICML'20](https://arxiv.org/abs/2002.09797)) **[UNVERIFIED — definitions from background]**. Each real point X_i gets a ball whose radius is its k-th nearest-neighbor distance among real points (k = 5).
  - Density = (1/kM) Σ_j Σ_i 1[Y_j ∈ B(X_i)]. It is about 1 when the distributions match.
  - Coverage = the share of real balls that contain at least one synthetic point.
- **α-precision, β-recall and authenticity** ([Alaa et al. ICML'22](https://proceedings.mlr.press/v162/alaa22a.html)).

Read them in pairs. **High precision with low coverage means plausible but homogeneous agents**, the classic LLM persona flattening. Compute them on rank-transformed per-user vectors, and subsample the real side to n = 100, because recall and coverage depend on sample size.

### Utility

**TSTR** means train on synthetic, test on real. Report it against **TRTR** (train and test on real) as the ceiling, and add TRTR at n = 100 as a fair learning-curve ceiling. TRTS (train on real, test on synthetic) adds a complementary check ([Esteban et al.](https://arxiv.org/abs/1706.02633)). Synthcity's `feat_rank_distance` checks whether models trained on synthetic data rely on the same features as models trained on real data ([synthcity](https://github.com/vanderschaarlab/synthcity)).

### Toolkits

| Toolkit | What it gives you | Notes |
|---|---|---|
| [SDMetrics](https://docs.sdv.dev/sdmetrics/) | Interpretable scorecard + MSAS sequence metrics | |
| [Synthcity](https://github.com/vanderschaarlab/synthcity) | PRDC, α-precision, MMD, detection_xgb/mlp/linear, performance metrics | Score external data via the `Metrics` layer; the signature is **[UNVERIFIED]** |
| [SynthEval](https://github.com/schneiderkamplab/syntheval) | pMSE, NN adversarial accuracy, rank-based benchmark aggregation | |
| [TSGBench](https://github.com/YihaoAng/TSGBench) | ACD, MDD, C-FID, DS/PS | Ranks with Friedman + Conover tests and critical-difference diagrams |
| Gretel, Table Evaluator | | **[UNVERIFIED — APIs not checked]** |

**None of these tools computes a real-vs-real noise floor.** Wrap each one in a harness that also scores real-A against real-B.

### Sequence-specific metrics

- Per-user sequence length.
- Inter-event time distribution.
- Burstiness.
- ACF at 24 h (and 168 h once multi-day runs exist).
- Event-type entropy.
- First-order transition matrices, compared by row-wise JSD weighted by real row mass.
- 2–3-gram profiles.
- C-FID on TS2Vec embeddings ([PSA-GAN](https://arxiv.org/abs/2108.00981)).

DTW and Euclidean distance assume paired series, so use them only inside nearest-neighbor or kernel frameworks for unpaired populations. HoTPP detects mode collapse by comparing predicted-label entropy with ground-truth entropy ([2406.14341](https://arxiv.org/html/2406.14341v3)).

---

## 6. ER utility: match identifiability, not just distributions

This is the category that decides whether the data can *substitute* for real data in user-identification research. A simulator can match every marginal and still be useless for ER if its users are more separable or less separable than real users.

### Unicity and the coarsening law

**Definition** ([de Montjoye 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC3607247/)):

- Draw p points I_p from user u's trace.
- Let S(I_p) be the set of traces that contain all of those points.
- u is unique if |S(I_p)| = 1.
- **ε_p** is the fraction of unique users.

Reference values on 1.5M users, 15 months, ~6,500 antennas and 1-hour bins:

- **ε_4 > 0.95**, **ε_2 > 0.5**;
- 11 points identified every sampled trace;
- **coarsening law ε = α − (v·h)^β, with β = 0.157 − 0.007p**, where v is spatial aggregation in antennas and h is temporal aggregation in hours. Halving resolution at p = 4 lowers identifiability by only ~9.3%.
- Coarsening one dimension only protects less than medium coarsening in both.

Scale effects ([Farzanehfar et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC7961185/)):

- ε_3 falls from 0.98 at 100K users to 0.93 at 1M; at 1M, ε_2 = 0.69 and ε_4 = 0.98.
- Unicity is convex and slowly decreasing in N.
- Placing antennas uniformly at random overestimates unicity. El Emam-style estimators underestimate it: 0.3 against an empirical 0.7.
- **Flag:** the paper's abstract (93% at 60M people, lower bound 22%) and its body (ε_4(20M) ≈ 0.99, lower bound 0.73) differ. Always quote N and p with any number from it.

Related results:

- Credit cards: 4 points identify 90% of 1.1M people ([Science 2015](https://dspace.mit.edu/handle/1721.1/96321)).
- Top-N locations (Zang & Bolot, 25M US users): top-2 or top-3 locations give small anonymity sets at cell level. The figures "up to 35% unique from 2 locations; ~3% with daily pseudonym rotation" come via a survey and are **[UNVERIFIED — full text not retrieved]** ([Blondel et al.](https://arxiv.org/pdf/1502.03406)).
- Browsing histories: 99% of ~52K Firefox profiles were unique, with re-identifiability rising with the number of domains (~50% at 50 or more domains, more than 80% at 150 or more) ([Bird et al. SOUPS'20](https://usenix.org/conference/soups2020/presentation/bird)). An earlier study found 94% unique among 400K profiles ([Help Net Security](https://www.helpnetsecurity.com/2020/08/27/browsing-histories-track-users/)).

**ER validity test 1 — unicity curves** *(inference)*:

- Compute ε_p for p = 1…10 on both datasets.
- Use matched resolutions: antenna or IP /24 level, crossed with 1 h, 4 h and full-day bins.
- Use matched N by repeatedly subsampling the real data to N = 100. Never extrapolate the synthetic population upward, and never compare a 100-agent ε_4 with a 1M-user ε_4.
- Fit β(p). A simulator whose identifiability falls off with coarsening much faster or slower than β ≈ 0.13–0.15 has the wrong concentration structure, even if one point on the curve matches.
- Report results by activity decile, because heavy users need more points to identify.
- Note: with a one-day window and N = 100, ε_p will be far from the 15-month literature values. **The real one-day, 100-user slice is the reference, not the published numbers.** Unicity at N ≈ 100 is not quantified anywhere in the sources.

### Linkage benchmarks, metrics and baselines

- **DPLink** (WWW'19) links identities across heterogeneous mobility datasets and reports hit-precision ([DOI](https://www.doi.org/10.1145/3308558.3313424)).
- Multi-service linkage reports AUC ([ACM TIST](https://dl.acm.org/doi/10.1145/3439817)).
- The **TUL** literature reports Acc@1, Acc@5 and Macro-F1 at |U| = 200–800 ([MainTUL](https://arxiv.org/pdf/2205.03773), [HGTUL](https://arxiv.org/pdf/2502.07549)). TULVAE's Acc@1 of 59.9% on Foursquare with 270 users is **[UNVERIFIED — secondary review]** ([Liner](https://liner.com/review/trajectoryuser-linking-via-variational-autoencoder)).
- **"TUL is easier than you think":** simple heuristics plus a non-parametric classifier match or beat deep TUL models ([2212.07081](https://arxiv.org/abs/2212.07081v1)).
- **CIKM Cup 2016** cross-device linking used pairwise F1. The top score was 0.420, the runner-up 0.417, and a classification-only approach 0.292; learning-to-rank beat pairwise classification ([1612.07117](https://arxiv.org/pdf/1612.07117), [1610.03928](https://ar5iv.labs.arxiv.org/html/1610.03928)).

**ER validity test 2 — linker panel and rank preservation** *(inference)*:

- Run the same linkers on real 100-user subsamples and on the simulation: a top-k frequency/TF-IDF baseline, a kNN or non-parametric classifier, and one deep model (TUL or DPLink style).
- Report Acc@1, Acc@5, MRR, Macro-F1, AUC and pairwise F1.
- The simulation passes if (i) its scores fall inside the real noise band and (ii) the **Spearman or Kendall correlation of method rankings** is preserved.
- If the deep model's gain over simple baselines is much larger on synthetic data than on real data, the simulator is "too structured".
- Remember DoppelGANger's warning: low diversity inflates rank preservation.

### Dataset difficulty

Papadakis et al. found most popular ER benchmarks too easy ([2307.01231](https://arxiv.org/pdf/2307.01231), [ICDE'24](https://helios2.mi.parisdescartes.fr/~themisp/publications/icde24-dlmatching.pdf)). Their checks are linearity measures, classification-complexity measures, the gap between linear and non-linear matchers, and the gap to an oracle. **[UNVERIFIED — the direction of the linearity measure looks internally inconsistent in the summary: it reports >0.87 "for new, harder" datasets. Check the PDF before quoting.]**

Behavioral analogue *(inference)*:

- Split each user's log into A and B halves. With one day: morning/afternoon, odd/even 5-min slots, or **modality A versus modality B**, for example antenna trace versus web/IP log.
- Compute within-user distances d(A_u, B_u) and between-user distances d(A_u, B_v), using Jaccard, TF-IDF cosine or DTW/EDR.
- Report:
  - separation AUC;
  - **d′ = |μ_b − μ_w| / sqrt((σ_b² + σ_w²)/2)**;
  - the equal error rate (EER);
  - **NNDR_u = d(A_u, B_u) / min_{v≠u} d(A_u, B_v)**. The fraction of users with NNDR < 1 equals 1-NN Acc@1;
  - the rank of the true match, which gives MRR;
  - fingerprint entropy compared with log₂N.
- If the synthetic data is much more linearly separable than the real data, the simulator makes ER too easy.

No published reference values exist for these on real CDR or browsing data, so the real dataset must supply them.

### Privacy versus ER utility

**Anonymeter** (PoPETs'23) measures risk as **R = (r_train − r_control)/(1 − r_control)**, with Wilson CIs and a naive-attack sanity check. An attack where r_naive ≥ r has failed and should be excluded, not reported as zero risk. Synthetic tabular data showed the *lowest* linkability risk ([ar5iv](https://ar5iv.labs.arxiv.org/html/2211.10459)). The repo was archived on 2025-11-21 ([GitHub](https://github.com/DatawizzAI/Datomize-anonymeter)). DCR-style proxies miss membership leakage, so use membership-inference attacks instead ([DCR Delusion](https://arxiv.org/html/2505.01524v1)).

*(inference)* There are two different "linkabilities":

- **Real-to-synthetic linkage** should be ~0 by construction for an LLM simulation. Checking it catches persona leakage if real logs were ever used to seed agents.
- **Within-synthetic linkage** is the ER signal, and it must match real levels.

Report both.

---

## 7. LLM-agent simulation: plausible narratives, flattened diversity, single runs

Evaluation of LLM-agent simulations falls into four families:

1. **Human-judged believability.** Generative Agents uses interview rankings converted to TrueSkill ([2304.03442](https://arxiv.org/abs/2304.03442)).
2. **Individual predictive fidelity.** Park et al. 2024 report GSS accuracy normalized by participants' own test-retest consistency: interview-based agents 83%, survey-based 82%, combined 86%, demographics-only 74% ([2411.10109](https://arxiv.org/abs/2411.10109)). Older v1 figures circulating online (85%, r ≈ 0.98) are **[UNVERIFIED]**.
3. **Distributional trace similarity.** LLMob's JSD suite. Swapping backbones (GPT-3.5, GPT-4o-mini, Llama-3-8B) changes JSD little ([LLMob](https://arxiv.org/pdf/2402.14744v3)).
4. **Directional replication of stylized facts.** AgentSociety, OASIS, S3.

Only families 2 and 3 give hard numbers, and **family 3 is the one that applies to footprints**.

**AgentSociety's own validation is mostly directional** ([2502.08691](https://arxiv.org/html/2502.08691v1)):

- In the polarization experiment, 39% of agents became more polarized in the control condition and 52% under homophilic interaction.
- In the hurricane experiment, simulated trips "deviated in magnitude and speed at peak" from SafeGraph data.
- The "One Day Life" experiment reports no radius of gyration or JSD.
- The authors state social interaction is mainly online messaging.

The independent evaluation of AgentSociety and CitySim against Paris and Shanghai data found ([2606.13835](https://arxiv.org/abs/2606.13835)):

- semantic activity distributions roughly right;
- failures on trip lengths, OD flows, dwell times and transitions;
- **mobility diversity that is unstable under default prompting**.

Its metric definitions were read only at abstract or snippet level, and the degenerate "stays home almost all day" agents are **[UNVERIFIED — snippet]**. **This project should not inherit any realism claim from AgentSociety.**

Failure modes and how to measure them:

| Failure mode | Evidence | Metric |
|---|---|---|
| Flattening / homogeneity | Wang et al., Nat. Mach. Intell. 2025 ([2402.01908](https://arxiv.org/abs/2402.01908v1)); LLM personas give homogeneous results ([NeurIPS'25 position](https://papers.neurips.cc/paper_files/paper/2025/file/5fc150b75e8b509735564de16bc3527b-Paper-Position_Paper_Track.pdf)) | Variance ratio of per-agent statistics against real; coverage/β-recall; within-group cosine similarity |
| Caricature | CoMPosT ([EMNLP'23](https://aclanthology.org/2023.emnlp-main.669/)) | Individuation classifier + exaggeration score |
| Over-conformity / herding | Stronger than in humans on matched Reddit data, per OASIS ([2411.11581](https://arxiv.org/pdf/2411.11581)) | Agreement / sycophancy rate in chat against a human corpus |
| Over-polite, over-long text; hallucinated memories | [Larooij & Törnberg](https://arxiv.org/html/2504.03274v1) | Message-length distribution, distinct-n, Vendi score |
| Low tonal variety | [2506.01839](https://arxiv.org/pdf/2506.01839) **[UNVERIFIED — attribution]** | Entropy and Vendi score of tone/emotion labels |
| Unstable mobility diversity; under-represented long tails | [2606.13835](https://arxiv.org/abs/2606.13835), [2508.08726](https://arxiv.org/pdf/2508.08726) (snippets) | DailyLoc, r_g dispersion; share of zero-trip agents |
| Archetype caching breaks local contagion | [2608.11215](https://arxiv.org/pdf/2608.11215) **[UNVERIFIED — attribution]** | Between-agent dispersion |

The **Vendi score** = exp(von Neumann entropy of the eigenvalues of the normalized similarity kernel), read as the "effective number of distinct items" ([Friedman & Dieng](https://arxiv.org/abs/2210.02410)).

Validation practice in this field is weak. **Larooij & Törnberg reviewed 35 generative-ABM papers** ([AI Review](https://link.springer.com/article/10.1007/s10462-025-11412-6)):

- 43% used only subjective validation.
- None ran a proper sensitivity analysis.
- Most relied on a single run.
- They call LLM-as-judge "self-evidently problematic".

They recommend operational validity, profile alignment, multiple runs and side-by-side comparison with human data. Pattern-oriented modelling ([Grimm et al. 2005](https://pubs.usgs.gov/publication/70161783)) supplies the right frame: **match several patterns at individual, population and emergent scales at the same time**.

Diversity should be measured at three levels *(inference)*:

- **across agents:** variance ratio of per-agent statistics against the real population;
- **within an agent across days:** this needs multi-day runs;
- **content:** distinct-n and Vendi score.

---

## 8. Sim-vs-real alignment: degrade the simulation before comparing it

Real CDR and network logs pass through a biased measurement layer. A clean 5-minute simulated trace will look systematically different even if the underlying behavior is right. The cited mechanisms:

- CDRs **underestimate travel distance and entropy but estimate r_g reasonably well** ([Zhao et al. IJGIS 2016](https://research.polyu.edu.hk/en/publications/understanding-the-bias-of-call-detail-records-in-human-mobility-r/)). Contrasting evidence also finds r_g underestimated **[UNVERIFIED — secondary]**.
- Sampling follows calling rate, so **heavy callers are over-represented** ([Ranjan et al.](https://www.researchgate.net/profile/Gyan-Ranjan-6/publication/262319014_Are_call_detail_records_biased_for_sampling_human_mobility_ACM_SIGMOBILE_Mob_Comput_Commun_Rev/links/57a2161408ae5f8b258b3661/Are-call-detail-records-biased-for-sampling-human-mobility-ACM-SIGMOBILE-Mob-Comput-Commun-Rev.pdf)).
- Antenna coverage ranges from 0.15 to 15 km², a ~100× difference between urban and rural cells ([PMC3607247](https://pmc.ncbi.nlm.nih.gov/articles/PMC3607247/)).
- **Ping-pong and oscillation handovers** make stationary phones look mobile. Filters exist: look-ahead removal of A–B–A patterns ([1907.12371](https://arxiv.org/pdf/1907.12371)), DECRE ([NTU](https://personal.ntu.edu.sg/xlli/publication/OscillationResolution.pdf)), SOL ([CPS-VO](https://archive.cps-vo.org/node/35822)), and Flowminder's two-pass stay detection ([NetMob'23](https://www.flowminder.org/media/e3fjfh5r/final-netmob_2023_-correcting-measurement-biases-in-the-detection-of-long-and-short-stay-locations.pdf)). Their parameter values were **not retrieved**.
- Subscriber bases are socioeconomically skewed. MRP correction cut naive mean r_g by ~17% **[UNVERIFIED — secondary summary]** ([Living Library](https://thelivinglib.org/correcting-socioeconomic-bias-in-mobile-phone-mobility-estimates-using-multilevel-regression-and-poststratification/)).

Mitigations *(inference)*:

| Pitfall | Mitigation |
|---|---|
| Event-driven sampling against dense simulation | Observation model: resample simulated ground truth with real per-user event rates (fitted per activity decile) and the real circadian profile |
| Spatial quantization | Snap simulated positions to the real antenna Voronoi cells, or matched hexes; map web traffic to eTLD+1 and IPs to /24 or ASN |
| Ping-pong / oscillation | Run the *same* filter on both sides, or inject calibrated oscillation. Filtering only one side biases r_g, entropy and unicity |
| Sparsity bias in the metrics | Compare at matched per-user point counts; stratify by activity |
| Window and weekday mix | Real one-day slice of the same day type, aligned by hour |
| Representativeness | Reweight or poststratify both sides to a common activity or demographic profile |
| Scale (N) | Subsample real data to N = 100 with many bootstrap draws |
| Geography mismatch (the simulated city may differ from the real one) | Use scale-free metrics (ranks, normalized distances, shapes); report absolute spatial metrics (locfreq, OD, STVD) only if geographies match |
| ID churn / pseudonyms | Model it in the observation layer if the real data has it. Daily pseudonym rotation changes identifiability sharply |
| Uninterpretable distances | Three references: real-vs-real floor, sim-vs-sim spread, naive baselines |

There is also a useful diagnostic. If the sim-vs-sim spread is much smaller than the real-vs-real spread, the simulation is under-dispersed, which is the typical LLM-agent signature.

---

## 9. Recommended evaluation protocol

The steps below are *(inference)*, synthesized from the sources above. Do steps 0–1 before the real data is opened, to avoid tuning to it.

**Step 0 — Pre-register the evaluation.** Freeze the metric list, families and pass rule in a config file:

- the metric list and families;
- spatial units;
- time bins (288 × 5-min and 24 × hourly);
- the sessionization threshold;
- the domain normalization (eTLD+1);
- the IP aggregation (/24 and ASN);
- the purpose-category mapping;
- B (e.g., 500 bootstrap draws);
- the pass rule: "sim-vs-real median inside the real-vs-real 95% band".

**Step 1 — Generate the simulation ensemble.** Run **≥5 seeds** of the 100-agent day with identical config, plus at least one sensitivity variant (temperature, prompt or backbone). If budget allows, run 2–7 consecutive days to unlock day-to-day stability, I-rank, ACF at 24 h and predictability. Keep the full ground-truth logs.

**Step 2 — Triage the real data's schema and sampling.** Establish:

- the fields present (positions or antennas, trip purpose or POI, domains, IPs, chat or CDR edges);
- the sampling regime: event-driven CDR/xDR, periodic, or GPS;
- the window and time zone;
- N;
- the antenna coordinates;
- whether IDs are stable;
- which day types are available.

Map both datasets to one common schema: `user, t, antenna, lat/lon, purpose, domain, ip_prefix, asn, peer`.

**Step 3 — Select the real comparison slice.** Take the same day type and a 24 h window, applying the minimum-activity filter you will also apply to the simulation. Record per-user event-rate deciles and the circadian event profile; these are the inputs to Step 4.

**Step 4 — Degrade the simulation through an observation model.** Treat this as a separate, parameterized module:

- (a) resample events using the real per-decile inter-event process and circadian profile;
- (b) snap positions to real antenna Voronoi cells, or to a matched-size tessellation if the geographies differ;
- (c) apply the same ping-pong and stay-detection filters to both sides;
- (d) apply real-like missingness and ID churn.

Keep three versions: the **raw simulation**, the **degraded simulation**, and the real data. The raw-vs-degraded gap itself shows how sensitive each metric is to measurement.

**Step 5 — Fix bins on the real data.** Derive all histogram bins from the pooled real slice: log-spaced for distance, r_g, dwell and bytes; quantile bins otherwise. Reuse them for every comparison, and record the bin counts in the scorecard.

**Step 6 — Establish noise floors and references.**

- **Real-vs-real:** B random disjoint pairs of real 100-user subsets, giving the distribution of every metric. Sample activity-matched users, and use ego or snowball samples for graph metrics.
- **Sim-vs-real:** the simulation against B real 100-user subsets.
- **Sim-vs-sim:** all seed pairs.
- Use user-level bootstrap for CIs, user-level label permutation for p-values, and Benjamini–Hochberg across metrics.
- Also report how the floor shrinks at N = 200 and 400, if the real data allows, to show the resolution of the evaluation.

**Step 7 — Run naive baselines through the identical pipeline.**

- EPR/d-EPR mobility (scikit-mobility);
- a Markov chain fitted on real transitions (a "docking" competitor);
- events shuffled within each user, which destroys temporal structure;
- independent column marginals, which destroys correlations;
- a Poisson process with per-user rates;
- an Erdős–Rényi or configuration-model chat graph at the same N and density;
- uniform-random domains drawn from the real vocabulary.

The LLM simulation has to beat these to justify its cost.

**Step 8 — Compute the metric families.**

- **Mobility (§1):** JSD + W1 on Distance, r_g, r_g^(2)/r_g, Duration, DailyLoc, G-rank (top antennas), SI; locfreq and OD (only with the same geography); DARD (288 × purpose); daily-motif JSD; itdType.
- **Temporal (§2):** 288- and 24-bin activity curves per modality with JSD + W1; departure-time KS; per-user B.
- **Web/network (§3):** Zipf exponent, Jaccard@k and RBO; per-user entropy and distinct counts; session and gap distributions; revisitation; format validity; diversity ratios.
- **Graph (§4):** degree, strength, reciprocity and clustering z-scores, all as percentiles in the real-subgraph distribution; DGCD-129/GCD-11; the overlap–weight trend; co-location versus chat Jaccard; per-edge B.
- **Multivariate (§5):** energy distance or MMDAgg on standardized per-user vectors; C2ST (linear + GBDT) with SHAP and the leave-top-k-out curve; density, coverage, α-precision and β-recall.
- **LLM failure modes (§7):** variance ratios of per-agent statistics against the real floor; zero-trip and degenerate agents; message length, distinct-n and Vendi score.

**Step 9 — Measure ER utility (§6).**

- ε_p curves for p = 1…10 across a resolution grid at N = 100, with β(p) fits.
- Top-N location anonymity sets.
- Within/between separation: AUC, d′, EER, NNDR, MRR. Use time splits and **cross-modal splits** (antenna trace ↔ web/IP log ↔ chat), since one day limits time splits.
- A linker panel (frequency, kNN, deep) on real and simulated data, with Spearman/Kendall rank preservation.
- TSTR for learned linkers.
- The linear-versus-non-linear separability gap.
- An Anonymeter sanity check that no real trace leaked into personas.

**Step 10 — Build the scorecard.**

- Columns per metric: value, 95% CI, real-vs-real floor (median and 95% band), sim-vs-sim spread, naive value, **normalized score s = (d_sim − d_floor)/(d_naive − d_floor)** (0 = as good as real, 1 = as bad as naive), and a pass flag.
- Group rows into families: mobility, temporal, web/network, graph, multivariate/C2ST, fidelity/diversity, ER utility.
- Aggregate within a family by the median of s. **Never collapse everything into one global number.**
- Show raw and degraded simulation side by side.

**Step 11 — Diagnose, iterate and report sensitivity.** Use SHAP-ranked C2ST features and the worst-s metrics to choose simulator fixes. Compare simulator versions with a paired bootstrap on the same real subsets. Report the seed and prompt/backbone sensitivity, as Larooij & Törnberg require.

---

## 10. Project checklist

- [ ] Metric config, bins, thresholds and pass rule frozen *before* opening the real data.
- [ ] ≥5 simulation seeds of the 100-agent day; ideally ≥2 consecutive days.
- [ ] Real schema triaged: sampling regime, window, time zone, N, antenna table, ID stability, presence of chat or CDR edges.
- [ ] Common schema and units: antenna Voronoi cells, eTLD+1, IP /24 and ASN, purpose mapping, 5-min clock in UTC.
- [ ] Geography check: same city? If not, drop absolute-location metrics (locfreq, OD, STVD, G-rank on IDs) and use scale-free ones.
- [ ] Observation model applied to the simulation: event-rate resampling per activity decile, spatial snapping, same ping-pong and stay filters on both sides, missingness and ID churn.
- [ ] Same sessionization threshold on both sides.
- [ ] Bins fixed on pooled real data; bin counts reported; JSD base and sqrt convention documented.
- [ ] Real-vs-real floor from B disjoint 100-user pairs; activity-matched; ego samples for graphs.
- [ ] Sim-vs-sim spread across seeds; under-dispersion flag if sim-vs-sim ≪ real-vs-real.
- [ ] Naive baselines (EPR, Markov, shuffled, Poisson, null graph, uniform domains) run through the identical code path.
- [ ] Mobility suite incl. DailyLoc, r_g, dwell, daily motifs, DARD-288.
- [ ] Temporal curves per modality with JSD *and* W1.
- [ ] Web/IP: Zipf, entropy, distinct counts, revisitation, validity, diversity.
- [ ] Graph: percentile within real 100-node subgraphs, DGCD/GCD, overlap–weight trend, co-location↔chat overlap.
- [ ] C2ST (linear + GBDT) with permutation p-value, SHAP and the leave-top-k-out curve; preprocessing harmonized first.
- [ ] Density/coverage and α/β on rank-transformed per-user vectors at n = 100.
- [ ] ER: ε_p curves and β(p) at N = 100; within/between separation; cross-modal linkage; linker panel with rank preservation; TSTR.
- [ ] Anonymeter/real→sim linkage sanity check (≈0 expected).
- [ ] Scorecard by family with normalized s and pass flags; no single global score.
- [ ] Sensitivity runs (temperature, prompt, backbone) and a paired-bootstrap comparison of versions.
- [ ] Every [UNVERIFIED] reference value re-checked before it is quoted in the thesis.

---

## 11. Open gaps and thesis contribution opportunities

The notes repeatedly found no prior work at the following points. Each is a defensible contribution.

1. **Unicity of LLM-agent populations against a real CDR baseline at matched N.** No paper reports this, and no source quantifies how ε_p scales between N ≈ 100 and 100K.
2. **A calibrated observation-model ("measurement layer") module for LLM-ABMs**, with an ablation of how each artifact (sampling, quantization, ping-pong, ID churn) changes ER results. The approach is well motivated but unpublished.
3. **A formalized real-vs-real noise-floor convention** and normalized scorecard for synthetic behavioral data. Current toolkits do not provide one, and no paper quantifies the finite-sample bias of JSD, TV or MMD at n ≈ 100 for mobility metrics.
4. **ER-specific validity criteria for synthetic data**: unicity-curve match, within/between separation, and rank preservation across linkers. No study evaluates synthetic-versus-real TUL or cross-device linking directly.
5. **A cross-modal synthetic ER benchmark** linking mobility, web/IP and chat identities for the same agents. No public real dataset offers all three with ground truth, which makes simulation uniquely useful here *if* it passes the floors above.
6. **Fidelity and diversity as functions of N and backbone for LLM-agent simulations.** Only throughput has been reported so far (no fidelity-versus-scale study).
7. **Combining Anonymeter-style privacy risk with ER utility on trajectory or browsing data.** This requires a sequence-aware featurization not covered in the paper.

## Conclusion

The literature gives plenty of metrics but almost no protocol for the question this project faces. Generator papers report single-run JSDs with unstated bins, toolkits ignore sample-size floors, and LLM-ABM papers mostly validate by plausibility. The defensible position is therefore relative rather than absolute. Claim that the simulation is "indistinguishable from real at n = 100 and one day" metric family by metric family, after observation-model degradation, against a real-vs-real band and naive baselines. That claim is falsifiable and survives reviewers.

For ER research specifically, a stricter standard applies. The question is whether the simulation reproduces *how separable users are*, and how that separability changes with coarsening, rather than whether its histograms match. An under-dispersed LLM population can pass marginal tests while making identification artificially easy, or artificially hard if every agent behaves alike. Unicity curves, within/between separation and linker rank preservation are where substitution actually gets proven or refuted. They are also where the thesis has the clearest room for an original contribution.
