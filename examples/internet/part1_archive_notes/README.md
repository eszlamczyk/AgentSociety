# Internet Simulation — AgentSociety

Simulates a population of LLM-driven agents living in a city, each equipped with ICT devices (smartphone, laptop, desktop, tablet). Agents follow realistic daily routines, connect to cell towers and home WiFi as they move, and browse the internet. The simulation logs every device action with browser IDs and IP addresses, enabling deanonymization graph analysis.

---

## Requirements

- Python 3.11+
- Linux or macOS (Windows not tested)
- A ZhipuAI API key (or any other LLM provider supported by agentsociety)
- The map file `agentsociety_data/beijing.pb` in the repo root (provided separately)

---

## Installation

Run the setup script once from the **repo root**:

```bash
bash examples/internet/setup.sh
```

This will:
1. Create a `.venv` virtual environment
2. Install `agentsociety` from local source (not PyPI — important for bug fixes)
3. Pin `numpy` to 2.x (required by `mosstool`)

> **Do not** use `pip install agentsociety` — it installs an older version without the fixes in this repo.

---

## Configuration

Open `examples/internet/internet.py` and set your API key:

```python
LLMConfig(
    provider=LLMProviderType.ZhipuAI,
    api_key="YOUR_API_KEY_HERE",   # <-- replace this
    model="GLM-4-Flash",
    semaphore=200,
)
```

Other parameters you may want to adjust:

| Parameter | Location | Default | Description |
|---|---|---|---|
| `number` | `internet.py` | `100` | Number of agents |
| `start_tick` | `internet.py` | `6 * 60 * 60` | Simulation start time (6:00 AM) |
| `total_tick` | `internet.py` | `18 * 60 * 60` | Simulation duration (18h, ends at midnight) |
| `START_WEEKDAY` | `internetagent.py` | `0` | Weekday for day 0 (0=Monday … 6=Sunday) |

---

## Running

```bash
source .venv/bin/activate
cd examples/internet
python internet.py
```

The simulation prints live progress (`$DEVICE$`, `$ANTENA$` prefixes). Expect it to run for several hours for 100 agents over 18 simulated hours.

---

## Output

All output is written to `examples/internet/internet_logs/`:

### `device_usage_logs.jsonl`
One JSON record per device action. Key fields:

| Field | Description |
|---|---|
| `sim_time` | Simulated time (e.g. `day0 14:32:01`) |
| `agent_id` / `agent_name` | Which agent |
| `device_type` | `smartphone`, `laptop`, `desktop`, `tablet` |
| `browser_id` | Stable per-device per-site UUID (simulates browser cookie) |
| `ip_address` | IP at time of action (home WiFi or cell tower) |
| `action_type` | `browse`, `work`, `shop`, `stream`, `social`, `call` |
| `website` | Domain visited |

### `antenna_device_connections.jsonl`
Logs every time an agent connects to or disconnects from a cell tower or home WiFi, with the assigned IP address.

---

## Analysis

Open the notebooks in `examples/internet/`:

```bash
source .venv/bin/activate
cd examples/internet
jupyter notebook
```

- **`graph_analysis.ipynb`** — interactive deanonymization graph (browser ID ↔ IP) + distribution histograms
- **`analysis.ipynb`** — general log statistics

---

## Project Structure

```
examples/internet/
├── internet.py                  # Entry point — simulation config and main()
├── internetagent.py             # Agent class with ICT device and connectivity logic
├── internet_memory_config.py    # Agent memory schema
├── setup.sh                     # One-command environment setup
├── utils/
│   ├── antennas.py              # Cell tower positions and connectivity
│   ├── home_wifi.py             # Home router / DHCP simulation
│   ├── ict_devices.py           # Device assignment and capabilities
│   ├── websites.py              # Website database by category
│   ├── prompts.py               # LLM plan generation prompts
│   └── device_logger.py         # JSONL log writers
├── internet_logs/               # Simulation output (generated at runtime)
└── profiles_with_aoi.json       # Agent demographic profiles
```
