# Internet Simulation - Runs & Plots

## Modele

| Model | Obsługa function calling | Uwagi |
|---|---|---|
| speakleash/Bielik-11B-v3.0-Instruct | tak | baseline, polskie dane treningowe |
| Qwen/Qwen3-Coder-30B-A3B-Instruct | tak | model coder - wyspecjalizowany, gorsza symulacja codziennego życia |
| modele bez `--tool-call-parser` na PLGrid | nie | crashuje przy block dispatch |

### Wnioski z porównania modeli

- **Specjalizacja modelu ma większy wpływ niż rozmiar** - Qwen3-30B (model coder, ~3x więcej parametrów) wypada gorzej niż Bielik-11B w symulacji codziennego życia
- Qwen3-30B generuje 67% aktywności typu social/call, top strony to wyłącznie social media - model nie ma wytrenowanego "modelu człowieka" w codziennym życiu
- Bielik-11B trenowany na polskich danych generuje realistyczniejsze polskie zachowania (biedronka.pl, kwestiasmaku.com)
- Qwen3-30B: 12% agentów się ruszyło vs 28% dla Bielik - model "siedzi w domu na Facebooku"
- Do porównania rozmiaru modeli właściwsze byłoby użycie ogólnego Qwen3-30B (bez -Coder)

---

## Runy

### Stress testy skalowania (throughput, 1h)
Cel: zbadać jak czas/tokeny rosną wraz z liczbą agentów.

| Run | Agenci | Czas sim | Katalog metryk |
|---|---|---|---|
| 1agent | 1 | 1h | `metrics/output/1agent/` |
| 10agent1Hour | 10 | 1h | `metrics/output/10agent1Hour/` |
| 10agent10Hours | 10 | 10h | `metrics/output/10agent10Hours/` |
| 100agent1Hour | 100 | 1h | `metrics/output/100agent1Hour/` |
| 1000agent_ratelimit_test | 1000 | 1h | `metrics/output/1000agent_ratelimit_test/` |
| 2000agent_throughput_test | 2000 | 1h | `metrics/output/2000agent_throughput_test/` |

### Runy jakościowe (full day)
Cel: badanie zachowania agentów przez całą dobę.

| Run | Agenci | Czas sim | Model | Logi | Metryki |
|---|---|---|---|---|---|
| 100agent_fullday | 100 | 24h | Bielik-11B | `run_logs/100agent_fullday/` | `metrics/output/100agent_fullday/` |
| 100agent_fullday_better_model | 100 | 24h | Qwen3-Coder-30B | `run_logs/100agent_fullday_better_model/` | `metrics/output/100agent_fullday_model_better/` |

---

## Ploty

### Porównawcze (cross-run)
`metrics/output/comparison_plots/`

| Plik | Co pokazuje |
|---|---|
| `01_wall_time_total.png` | Całkowity czas wykonania vs liczba agentów |
| `02_wall_time_per_agent.png` | Czas per agent vs skala (sublinear O(N^0.58)) |
| `03_tokens_per_agent.png` | Tokeny per agent - spójność zachowania niezależnie od skali |
| `04_tokens_per_second.png` | Realny throughput PLGrid (~6k tok/s sufit) |

### Per run - metryki LLM
`metrics/output/<run>/plots/`

| Plik | Co pokazuje |
|---|---|
| `01_wall_time_per_step.png` | Czas ściany per krok |
| `02_cumulative_wall_time.png` | Skumulowany czas |
| `03_tokens_per_step.png` | Tokeny per krok |
| `04_cumulative_tokens.png` | Skumulowane tokeny |
| `05_tokens_overview.png` | Przegląd tokenów |
| `06_tokens_per_second.png` | Throughput PLGrid w czasie |
| `07_tokens_per_agent_per_step.png` | Tokeny per agent w czasie |
| `08_agent_input_vs_output.png` | Podział input/output per agent |

### Per run - aktywność agentów
`run_logs/<run>/plots/`

| Plik | Skrypt | Co pokazuje |
|---|---|---|
| `activity_by_hour.png` | `activity_analysis.py` | Rozkład typów aktywności internetowej per godzina (browse/work/shop/social/stream/call) |
| `movement_by_hour.png` | `activity_analysis.py` | Agenci poruszający się vs aktywni online per godzina |
| `ip_per_agent.png` | `traffic_analysis.py` | Unikalne adresy IP per agent (home WiFi vs antenna) |
| `top_websites_per_type.png` | `traffic_analysis.py` | Top 10 stron dla każdego typu ruchu internetowego |
| `traffic_per_agent.png` | `traffic_analysis.py` | Rozkład typów ruchu internetowego per agent |
| `action_description_keywords.png` | `traffic_analysis.py` | Najczęstsze słowa w opisach akcji agentów per typ ruchu |
| `mobility_trajectories.png` | `mobility_analysis.py` | Ścieżki agentów na mapie 2D, kolor = cel podróży |
| `mobility_distance_dist.png` | `mobility_analysis.py` | Rozkład długości podróży |
| `mobility_by_hour.png` | `mobility_analysis.py` | Liczba podróży per godzina vs IRL rush hours |
| `mobility_per_agent.png` | `mobility_analysis.py` | Ile podróży per agent + % moving vs stationary |
| `mobility_plan_targets.png` | `mobility_analysis.py` | Co motywuje ruch (Work/Leisure/etc.) per godzina |

---

## Komendy

### Nowy full-day run
```bash
RUN=<nazwa> && \
mkdir -p run_logs/$RUN/internet run_logs/$RUN/positions && \
INTERNET_LOG_DIR=run_logs/$RUN/internet \
POSITION_LOG_DIR=run_logs/$RUN/positions \
../../.venv/bin/python internet.py
```

### Generowanie wszystkich plotów po runie
```bash
RUN=<nazwa>
../../.venv/bin/python metrics/activity_analysis.py run_logs/$RUN
../../.venv/bin/python metrics/traffic_analysis.py run_logs/$RUN
../../.venv/bin/python metrics/mobility_analysis.py run_logs/$RUN --agents 100
../../.venv/bin/python metrics/render.py metrics/output/$RUN
```
