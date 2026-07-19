"""
Shared utilities for readable log scripts:
  - SQLite profile loading (find_db, resolve_exp_id, list_experiments, load_profiles)
  - sim_time sorting
  - agent profile line formatting
"""

import json
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def find_db(start: Path) -> Path | None:
    """Search for sqlite.db in common locations relative to start."""
    candidates = [
        start / "agentsociety_data" / "sqlite.db",
        start.parent / "agentsociety_data" / "sqlite.db",
        start.parent.parent / "agentsociety_data" / "sqlite.db",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def resolve_exp_id(conn: sqlite3.Connection, exp: str | None) -> str | None:
    """
    Resolve an experiment id from:
      - None / 'latest'  -> most recent by created_at
      - UUID prefix      -> most recent match (dashes ignored)
      - name substring   -> most recent case-insensitive match
    """
    if exp is None or exp == "latest":
        row = conn.execute(
            "SELECT id FROM as_experiment ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    clean = exp.replace("-", "")
    row = conn.execute(
        "SELECT id FROM as_experiment WHERE REPLACE(id,'-','') LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f"{clean}%",),
    ).fetchone()
    if row:
        return row[0]

    row = conn.execute(
        "SELECT id FROM as_experiment WHERE LOWER(name) LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f"%{exp.lower()}%",),
    ).fetchone()
    return row[0] if row else None


def list_experiments(db_path: Path) -> None:
    """Print all experiments in the database."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, name, created_at FROM as_experiment ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    print("\nAvailable experiments:")
    for eid, name, created in rows:
        print(f"  {created}  {eid}  {name!r}")
    print()


def load_profiles(db_path: Path, exp: str | None) -> dict[int, dict]:
    """
    Return {agent_id: profile_dict} from the agent_profile table.
    exp can be None/'latest', a UUID prefix, or a name substring.
    """
    conn = sqlite3.connect(db_path)
    try:
        exp_id = resolve_exp_id(conn, exp)
        if not exp_id:
            return {}

        uid = exp_id.replace("-", "")
        uuid_form = (
            f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:]}"
            if len(uid) == 32
            else uid
        )
        table = f"as_{uuid_form.replace('-', '_')}_agent_profile"

        try:
            rows = conn.execute(f"SELECT id, profile FROM {table}").fetchall()
        except sqlite3.OperationalError:
            print(f"[log_utils] profile table not found for exp {exp_id}")
            return {}

        profiles: dict[int, dict] = {}
        for agent_id, profile_json in rows:
            try:
                p = (
                    json.loads(json.loads(profile_json))
                    if isinstance(profile_json, str)
                    else profile_json
                )
                profiles[agent_id] = p
            except Exception:
                profiles[agent_id] = {}
        return profiles
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def sim_sort_key(sim_time: str) -> tuple:
    """'day1 14:35:01' -> (1, 14, 35, 1) for chronological sorting."""
    try:
        day_part, time_part = sim_time.split(" ")
        day = int(day_part.replace("day", ""))
        h, m, s = map(int, time_part.split(":"))
        return (day, h, m, s)
    except Exception:
        return (0, 0, 0, 0)


def profile_line(profile: dict) -> str:
    """Single-line summary of an agent's profile fields."""
    if not profile:
        return "(no profile data)"
    parts = []
    for key in ("gender", "age", "occupation", "education", "marriage_status"):
        val = profile.get(key)
        if val is not None:
            parts.append(f"{key}={val}")
    bg = profile.get("background_story")
    if bg and bg != "No background story":
        parts.append(f'story="{bg}"')
    return "  ".join(parts)
