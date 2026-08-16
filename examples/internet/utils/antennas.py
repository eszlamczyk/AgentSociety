import math
import datetime
import json
import os
import threading
import random
from typing import Optional, Tuple
from .websites import WEBSITE_DATABASE
from .ip_strategies import (
    AntennaIPStrategy,
    SharedAntennaIPStrategy,
)

MIN_X = -30000.0  # Minimum X coordinate of the map
MAX_X = 30000.0   # Maximum X coordinate of the map
MIN_Y = -30000.0  # Minimum Y coordinate of the map
MAX_Y = 30000.0   # Maximum Y coordinate of the map

ANTENNA_RANGE = 5000.0

# --- Global path to internet log file ---
GLOBAL_INTERNET_LOG_FILE = "all_internet_activity_logs.jsonl"
GLOBAL_DEVICE_CONNECTION_LOG_FILE = "antenna_device_connections.jsonl"
GLOBAL_DEVICE_USAGE_LOG_FILE = "device_usage_logs.jsonl"
GLOBAL_LOG_DIR = os.environ.get("INTERNET_LOG_DIR", "internet_logs")
POSITION_LOG_DIR = os.environ.get("POSITION_LOG_DIR", "position_logs")

# Ensure the log directories exist
os.makedirs(GLOBAL_LOG_DIR, exist_ok=True)
os.makedirs(POSITION_LOG_DIR, exist_ok=True)

# Full paths to log files
FULL_GLOBAL_LOG_PATH = os.path.join(GLOBAL_LOG_DIR, GLOBAL_INTERNET_LOG_FILE)
FULL_DEVICE_CONNECTION_LOG_PATH = os.path.join(GLOBAL_LOG_DIR, GLOBAL_DEVICE_CONNECTION_LOG_FILE)
FULL_DEVICE_USAGE_LOG_PATH = os.path.join(GLOBAL_LOG_DIR, GLOBAL_DEVICE_USAGE_LOG_FILE)
FULL_POSITION_LOG_PATH = os.path.join(POSITION_LOG_DIR, "position_logs.jsonl")

# These logs are opened in append mode and otherwise persist across runs
# (see current_changelog.md). Set CLEAR_LOGS_ON_START=1 to truncate them
# once here at import time, before any run writes to them.
if os.environ.get("CLEAR_LOGS_ON_START", "0") == "1":
    for _log_path in (
        FULL_GLOBAL_LOG_PATH,
        FULL_DEVICE_CONNECTION_LOG_PATH,
        FULL_DEVICE_USAGE_LOG_PATH,
        FULL_POSITION_LOG_PATH,
    ):
        open(_log_path, "w").close()
    print(f"$DEBUG$ - CLEAR_LOGS_ON_START=1: truncated internet/device/position logs in {GLOBAL_LOG_DIR}/, {POSITION_LOG_DIR}/")

# Create locks for thread-safe file writing
log_file_lock = threading.Lock()
device_connection_lock = threading.Lock()
device_usage_lock = threading.Lock()
position_log_lock = threading.Lock()

class Antenna:
    def __init__(
        self,
        id: int,
        position: dict,
        antenna_range: float,
        ip_strategy: Optional[AntennaIPStrategy] = None,
    ):
        """
        Initialize an Antenna object.

        Args:
            id (int): Unique antenna identifier.
            position (dict): Dictionary with 'x' and 'y' keys representing the antenna's position.
            antenna_range (float): Operating range of the antenna in meters.
        """
        self.id = id
        self.category = "antenna"
        self.position = position
        self.range = antenna_range
        self.active_connections = set()  # Set of agent IDs currently connected
        self.connected_devices = {}  # Dict mapping agent_id to device info
        self.ip_strategy = ip_strategy or SharedAntennaIPStrategy()

    def is_within_range(self, agent_position: dict) -> bool:
        """
        Check if the given agent position is within the antenna's range.
        """
        distance = math.sqrt(
            (self.position['x'] - agent_position['x'])**2 +
            (self.position['y'] - agent_position['y'])**2
        )
        return distance <= self.range

    def surf_internet(self, agent_id: int, agent_name: str, interests: dict, known_websites: list) -> Tuple[Optional[str], int]:
        """
        The only method for agents to access the internet. Selects a website based on interests
        and known websites, logs the activity, and returns the selected website with browsing time.

        Args:
            agent_id (int): Agent ID
            agent_name (str): Agent name
            interests (dict): Dictionary of agent's interests
            known_websites (list): List of agent's known websites

        Returns:
            Tuple[Optional[str], int]: (selected website, browsing time in ticks)
        """
        if agent_id not in self.active_connections:
            return None, 0

        # Select website based on interests and known websites
        website = self._select_website(interests, known_websites)
        if not website:
            return None, 0

        # Determine browsing time (5-15 minutes)
        duration = random.randint(300, 900)

        # Log the activity
        self._log_activity(agent_id, agent_name, website, duration)

        return website, duration

    def _select_website(self, interests: dict, known_websites: list) -> Optional[str]:
        """
        Select a website based on interests and known websites.
        """
        # First try to select from known websites with high ratings
        high_score_sites = [site for site in known_websites if site["score"] >= 7]
        if high_score_sites:
            return random.choice(high_score_sites)["website"]

        # If no high-rated websites, select based on interests
        interest_weights = {k: v/10 for k, v in interests.items()}
        selected_interest = random.choices(
            list(interest_weights.keys()),
            weights=list(interest_weights.values()),
            k=1
        )[0]

        # Get available websites for the selected interest
        available_sites = WEBSITE_DATABASE.get(selected_interest, [])
        if available_sites:
            return random.choice(available_sites)

        return None

    def _log_activity(self, agent_id: int, agent_name: str, website_url: str, duration_ticks: int):
        """
        Log internet activity to a file.
        """
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "antenna_id": self.id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "website_url": website_url,
            "duration_ticks": duration_ticks
        }
        
        with log_file_lock:
            with open(FULL_GLOBAL_LOG_PATH, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

    def connect_agent(self, agent_id: int, agent_name: str = None, devices: list = None):
        """
        Add agent to the list of active connections and log device information.

        Args:
            agent_id: Agent ID
            agent_name: Agent name
            devices: List of agent's ICT devices
        """
        self.active_connections.add(agent_id)

        # Store device information and log each device separately
        if devices:
            device_connections = []

            for device in devices:
                if device.device_type.value != "none":
                    device_id = f"{agent_id}_{device.device_type.value}"
                    ip_address = self.ip_strategy.get_ip(
                        antenna_id=self.id,
                        agent_id=agent_id,
                        device_type=device.device_type.value,
                        device_id=device_id,
                    )

                    device_connection = {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "device_name": device.name,
                        "device_type": device.device_type.value,
                        "device_id": device_id,
                        "ip_address": ip_address
                    }
                    device_connections.append(device_connection)

                    # Log each device connection separately
                    self._log_device_connection(agent_id, "connect", device_connection)

            # Store all device connections for this agent
            self.connected_devices[agent_id] = device_connections

    def disconnect_agent(self, agent_id: int):
        """Remove agent from the list of active connections and log disconnection"""
        self.active_connections.discard(agent_id)

        # Log disconnection for each device separately
        if agent_id in self.connected_devices:
            device_connections = self.connected_devices[agent_id]
            for device_connection in device_connections:
                self._log_device_connection(agent_id, "disconnect", device_connection)
            del self.connected_devices[agent_id]

    def _log_device_connection(self, agent_id: int, action: str, device_info: dict):
        """
        Log single device connection/disconnection to the antenna.

        Args:
            agent_id: Agent ID
            action: "connect" or "disconnect"
            device_info: Information about a single device (not a list)
        """
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            "network_type": "antenna",
            "antenna_id": self.id,
            "antenna_position": {
                "x": self.position["x"],
                "y": self.position["y"]
            },
            "agent_id": agent_id,
            "agent_name": device_info.get("agent_name"),
            "device_name": device_info.get("device_name"),
            "device_type": device_info.get("device_type"),
            "device_id": device_info.get("device_id"),
            "ip_address": device_info.get("ip_address")
        }

        with device_connection_lock:
            with open(FULL_DEVICE_CONNECTION_LOG_PATH, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

    def to_dict(self):
        """Return the antenna representation as a dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "position": self.position,
            "range": self.range
        }

def _generate_antennas_grid(
    min_x,
    max_x,
    min_y,
    max_y,
    antenna_range,
    ip_strategy: Optional[AntennaIPStrategy] = None,
):
    """
    Generate a list of Antenna objects evenly distributed in a grid
    to cover the entire specified area.
    """
    antennas = []
    antenna_id_counter = 1

    step_x = antenna_range * 1.5
    step_y = antenna_range * 1.5

    start_x = min_x - (antenna_range / 2)
    start_y = min_y - (antenna_range / 2)

    current_x = start_x
    while current_x <= max_x + (antenna_range / 2):
        current_y = start_y
        while current_y <= max_y + (antenna_range / 2):
            antennas.append(
                Antenna(
                    id=antenna_id_counter,
                    position={"x": current_x, "y": current_y},
                    antenna_range=antenna_range,
                    ip_strategy=ip_strategy,
                )
            )
            antenna_id_counter += 1
            current_y += step_y
        current_x += step_x
    
    return antennas

# Global list of antennas containing Antenna objects
DEFAULT_ANTENNA_IP_STRATEGY = SharedAntennaIPStrategy(host_octet=1)
ANTENNAS = _generate_antennas_grid(
    MIN_X,
    MAX_X,
    MIN_Y,
    MAX_Y,
    ANTENNA_RANGE,
    ip_strategy=DEFAULT_ANTENNA_IP_STRATEGY,
)

print(f"[{__name__}] Generated {len(ANTENNAS)} Antenna objects covering the map.")

print(ANTENNAS[0].to_dict())  # Example display of the first antenna