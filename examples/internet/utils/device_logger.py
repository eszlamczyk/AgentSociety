"""
Device usage logging utilities for tracking when agents use ICT devices to solve tasks.
"""

import datetime
import json
import threading
from typing import Optional

# Import the log path and lock from antennas
from .antennas import FULL_DEVICE_USAGE_LOG_PATH, device_usage_lock, FULL_POSITION_LOG_PATH, position_log_lock


def log_device_usage(
    agent_id: int,
    agent_name: str,
    device_id: str,
    device_type: str,
    device_name: str,
    browser_id: Optional[str] = None,
    action_type: str = "browse",
    action_description: str = "",
    task_target: Optional[str] = None,
    success: bool = True,
    metadata: Optional[dict] = None,
    website: Optional[str] = None,
    ip_address: Optional[str] = None,
    sim_time: Optional[str] = None,
):
    """
    Log when an agent uses a device to solve a task or perform an action.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        device_id: Unique device identifier (e.g., "123_smartphone")
        device_type: Type of device used (smartphone, laptop, desktop, tablet)
        device_name: Human-readable device name
        action_type: Type of action performed (e.g., "browse", "shop", "work", "social", "search")
        action_description: Description of what the agent did
        task_target: Optional - what task was being solved (e.g., "Find restaurant information")
        success: Whether the action was successful
        metadata: Optional additional metadata (e.g., website visited, time spent, etc.)
        website: Optional - specific website visited during this action
    """
    timestamp = datetime.datetime.now().isoformat()

    log_entry = {
        "timestamp": timestamp,
        "sim_time": sim_time,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "device_id": device_id,
        "device_type": device_type,
        "device_name": device_name,
        "browser_id": browser_id,
        "ip_address": ip_address,
        "action_type": action_type,
        "action_description": action_description,
        "task_target": task_target,
        "success": success,
    }

    if website:
        log_entry["website"] = website

    # Add metadata last
    if metadata:
        log_entry["metadata"] = metadata
    else:
        log_entry["metadata"] = {}

    with device_usage_lock:
        with open(FULL_DEVICE_USAGE_LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')


def log_position_change(
    agent_id: int,
    agent_name: str,
    old_x: float,
    old_y: float,
    new_x: float,
    new_y: float,
    distance: float,
    connectivity: str,
    sim_time: Optional[str] = None,
    plan_target: Optional[str] = None,
    step_intention: Optional[str] = None,
    step_type: Optional[str] = None,
    emotion: Optional[str] = None,
    need: Optional[str] = None,
):
    """
    Log an agent's position change.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        old_x, old_y: Previous coordinates
        new_x, new_y: New coordinates
        distance: Distance moved in map units
        connectivity: Current connectivity status ("home_wifi", "antenna", "none")
        sim_time: Simulated time string
        plan_target: High-level goal the agent is pursuing (e.g. "Work", "Shopping")
        step_intention: Current step being executed (e.g. "Commute to work")
        step_type: Plan step type (mobility/economy/social/other)
        emotion: Agent's current emotion type string (e.g. "Anxious")
        need: Agent's current need (hungry/tired/safe/social/whatever)
    """
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "sim_time": sim_time,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "from": {"x": old_x, "y": old_y},
        "to": {"x": new_x, "y": new_y},
        "distance": round(distance, 2),
        "connectivity": connectivity,
        "plan_target": plan_target,
        "step_intention": step_intention,
        "step_type": step_type,
        "emotion": emotion,
        "need": need,
    }

    with position_log_lock:
        with open(FULL_POSITION_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")


def log_internet_browsing(
    agent_id: int,
    agent_name: str,
    device_id: str,
    device_type: str,
    device_name: str,
    website: str,
    purpose: Optional[str] = None,
    duration_seconds: Optional[int] = None
):
    """
    Convenience function for logging internet browsing actions.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        device_id: Unique device identifier
        device_type: Type of device used
        device_name: Human-readable device name
        website: Website URL being visited
        purpose: Optional - why the agent is browsing (e.g., "Check news", "Shop for groceries")
        duration_seconds: Optional - how long they browsed
    """
    metadata = {"website": website}
    if duration_seconds:
        metadata["duration_seconds"] = duration_seconds

    log_device_usage(
        agent_id=agent_id,
        agent_name=agent_name,
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        action_type="browse",
        action_description=f"Browse {website}" + (f" - {purpose}" if purpose else ""),
        task_target=purpose,
        success=True,
        metadata=metadata
    )


def log_online_shopping(
    agent_id: int,
    agent_name: str,
    device_id: str,
    device_type: str,
    device_name: str,
    items: list[str],
    store: Optional[str] = None,
    completed: bool = True
):
    """
    Convenience function for logging online shopping actions.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        device_id: Unique device identifier
        device_type: Type of device used
        device_name: Human-readable device name
        items: List of items being shopped for
        store: Optional - which online store
        completed: Whether the purchase was completed
    """
    metadata = {"items": items}
    if store:
        metadata["store"] = store

    log_device_usage(
        agent_id=agent_id,
        agent_name=agent_name,
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        action_type="shop",
        action_description=f"Shop online for {', '.join(items)}" + (f" at {store}" if store else ""),
        task_target=f"Purchase {', '.join(items)}",
        success=completed,
        metadata=metadata
    )


def log_remote_work(
    agent_id: int,
    agent_name: str,
    device_id: str,
    device_type: str,
    device_name: str,
    work_description: str,
    duration_seconds: Optional[int] = None
):
    """
    Convenience function for logging remote work actions.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        device_id: Unique device identifier
        device_type: Type of device used
        device_name: Human-readable device name
        work_description: Description of the work being done
        duration_seconds: Optional - how long they worked
    """
    metadata = {}
    if duration_seconds:
        metadata["duration_seconds"] = duration_seconds

    log_device_usage(
        agent_id=agent_id,
        agent_name=agent_name,
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        action_type="work",
        action_description=work_description,
        task_target="Complete remote work task",
        success=True,
        metadata=metadata
    )


def log_social_media(
    agent_id: int,
    agent_name: str,
    device_id: str,
    device_type: str,
    device_name: str,
    platform: str,
    activity: str
):
    """
    Convenience function for logging social media usage.

    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        device_id: Unique device identifier
        device_type: Type of device used
        device_name: Human-readable device name
        platform: Social media platform (e.g., "facebook.com", "instagram.com")
        activity: What they did (e.g., "Check updates", "Post message", "Chat with friend")
    """
    log_device_usage(
        agent_id=agent_id,
        agent_name=agent_name,
        device_id=device_id,
        device_type=device_type,
        device_name=device_name,
        action_type="social",
        action_description=f"{activity} on {platform}",
        task_target=activity,
        success=True,
        metadata={"platform": platform}
    )
