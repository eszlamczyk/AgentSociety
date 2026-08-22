import asyncio
import logging
import random
import datetime
import math

from agentsociety.agent import CitizenAgentBase
from agentsociety.cityagent import SocietyAgent
from utils.antennas import ANTENNAS
from utils.home_wifi import get_or_create_home_router, HOME_AT_DISTANCE
from utils.websites import WEBSITE_DATABASE
from utils.prompts import CUSTOM_DETAILED_PLAN_PROMPT, CUSTOM_BLOCK_DISPATCH_PROMPT
from utils.ict_devices import assign_devices_to_agent, get_device_awareness_text, ICTDevice
from utils.device_logger import log_device_usage, log_internet_browsing, log_position_change
from utils.needs_block_custom import TimeAwareNeedsBlock

logger = logging.getLogger(__name__)

# Day 0 of the simulation corresponds to this weekday (0=Monday … 6=Sunday)
START_WEEKDAY = 0  # Monday

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

class InternetAgent(SocietyAgent):
    def __init__(self, id: int, name: str, toolbox, memory, agent_params=None, blocks=None):
        # Override the plan generation prompt with our custom one that includes device_usage
        if agent_params:
            agent_params.plan_generation_prompt = CUSTOM_DETAILED_PLAN_PROMPT
            agent_params.block_dispatch_prompt = CUSTOM_BLOCK_DISPATCH_PROMPT

        super().__init__(
            id=id,
            name=name,
            toolbox=toolbox,
            memory=memory,
            agent_params=agent_params,
            blocks=blocks
        )

        # Swap in the time-aware satisfaction evaluator (see utils/needs_block_custom.py).
        # SocietyAgent.__init__ already constructed self.needs_block above; replace it
        # in place since NeedsBlock isn't exposed via agent_params like the plan/dispatch
        # prompts are.
        self.needs_block = TimeAwareNeedsBlock(
            toolbox=self._toolbox,
            agent_memory=self.memory,
            agent_context=self.context,
            initial_prompt=self.params.need_initialization_prompt,
        )

        # Debug-only: log which top-level block step_execution() (societyagent.py:692)
        # actually selects for each step. Investigating why MoveBlock (see
        # utils/mobility_block_custom.py) is getting zero calls on Bielik despite
        # plans containing mobility-typed steps — either the top-level dispatcher's
        # forced tool-calling (agent/dispatcher.py's BlockDispatcher.dispatch())
        # isn't reliable on this model, or CUSTOM_BLOCK_DISPATCH_PROMPT's "when in
        # doubt, choose otherblock" line is steering it away from mobilityblock.
        # Wraps rather than duplicates dispatch() so the vendored selection logic
        # stays untouched; only observes input/output. Not wired to any log file —
        # stdout only, same as the other $DEBUG$ prints in this file.
        _original_dispatch = self.dispatcher.dispatch

        async def _instrumented_dispatch(context, _orig=_original_dispatch, _agent_name=name):
            selected = await _orig(context)
            step_type = (context.get("current_step") or {}).get("type")
            intention = context.get("current_intention")
            print(f"$DEBUG$ - top-level dispatch for {_agent_name}: step_type={step_type!r} intention={intention!r} -> {selected.__class__.__name__ if selected else None}")
            return selected

        self.dispatcher.dispatch = _instrumented_dispatch

        self.last_position = None
        self.connected_antenna = None
        self.name = name
        self.current_website = None
        self.website_start_time = None
        self.browsing_duration = 0

        self.interests = self._assign_interests()
        self.known_websites = self._generate_initial_websites()
        self.recently_visited: list[str] = []  # Last N visited sites, used to force variety
        self.last_xy_position = None  # Track last position for comparison
        self.ict_devices: list[ICTDevice] = []  # Will be populated after memory is initialized

        self.home_router = None       # HomeRouter instance for this agent's home
        self.home_xy = None           # Captured on first connection (= starting/home position)
        self.home_leased_ips: dict[str, str] = {}  # device_id -> ip when on home WiFi

        print(f"$ANTENA$ - {self.name} initialized with interests: {self.interests} and {len(self.known_websites)} known websites.")

    async def forward(self):
        # Initialize ICT devices on first run (after memory is available)
        if not self.ict_devices:
            await self._initialize_ict_devices()

        # Get current position before parent forward to check antenna connectivity
        current_position = await self.memory.status.get("position")
        current_xy = current_position.get("xy_position") if current_position else None

        # Check if position changed and update antenna connection BEFORE parent forward
        if current_xy:
            if self.last_xy_position is None:
                # First time setting position
                print(f"$ANTENA$ - {self.name} initial position set to ({current_xy['x']},{current_xy['y']})")
                await self.connect_to_nearest_antenna(current_xy)
                self.last_xy_position = {"x": current_xy["x"], "y": current_xy["y"]}
            elif self.last_xy_position['x'] != current_xy['x'] or self.last_xy_position['y'] != current_xy['y']:
                # Position changed
                old_x, old_y = self.last_xy_position['x'], self.last_xy_position['y']
                new_x, new_y = current_xy['x'], current_xy['y']
                dist = self._distance({"x": old_x, "y": old_y}, {"x": new_x, "y": new_y})
                print(f"$ANTENA$ - {self.name} position changed from ({old_x},{old_y}) to ({new_x},{new_y})")
                await self.connect_to_nearest_antenna(current_xy)
                self.last_xy_position = {"x": new_x, "y": new_y}

                connectivity = (
                    "home_wifi" if self.home_leased_ips
                    else "antenna" if self.connected_antenna
                    else "none"
                )
                sim_day, sim_time = self.environment.get_datetime(format_time=True)

                current_plan = await self.memory.status.get("current_plan")
                plan_target = None
                step_intention = None
                step_type = None
                if current_plan:
                    plan_target = current_plan.get("target")
                    steps = current_plan.get("steps", [])
                    idx = current_plan.get("index", 0)
                    if steps and idx < len(steps):
                        step_intention = steps[idx].get("intention")
                        step_type = steps[idx].get("type")

                emotion = await self.memory.status.get("emotion_types")
                need = await self.memory.status.get("current_need")

                log_position_change(
                    agent_id=self.id,
                    agent_name=self.name,
                    old_x=old_x,
                    old_y=old_y,
                    new_x=new_x,
                    new_y=new_y,
                    distance=dist,
                    connectivity=connectivity,
                    sim_time=f"day{sim_day} {sim_time}",
                    plan_target=plan_target,
                    step_intention=step_intention,
                    step_type=step_type,
                    emotion=emotion,
                    need=need,
                )

        # Update internet connectivity and device awareness in memory
        has_internet = self.connected_antenna is not None or bool(self.home_leased_ips)
        await self.memory.status.update("has_internet", has_internet)

        # Update device awareness text so agent knows what devices they have and can use
        device_awareness = get_device_awareness_text(self.ict_devices, has_internet)
        await self.memory.status.update("ict_devices", device_awareness)

        # Update current simulation day/time for use in the plan prompt
        sim_day, sim_time = self.environment.get_datetime(format_time=True)
        weekday_idx = (START_WEEKDAY + sim_day) % 7
        weekday_name = _WEEKDAY_NAMES[weekday_idx]
        day_type = "weekend" if weekday_idx >= 5 else "weekday"
        await self.memory.status.update(
            "current_day_info", f"{weekday_name} ({day_type}), {sim_time}"
        )

        duration = await super().forward()

        return duration

    async def step_execution(self):
        """Override step execution to handle device usage before executing the step"""
        current_plan = await self.memory.status.get("current_plan")
        if (
            current_plan is None
            or not current_plan
            or len(current_plan.get("steps", [])) == 0
        ):
            return  # No plan, no execution

        step_index = current_plan.get("index", 0)
        current_step = current_plan.get("steps", [])[step_index]

        # Debug: Log current step to see if device_usage is present
        if current_step:
            print(f"$DEBUG$ - {self.name} executing step: {current_step.get('intention', 'Unknown')}")
            if "device_usage" in current_step:
                print(f"$DEBUG$ - Device usage field present: {current_step['device_usage']}")
            else:
                print(f"$DEBUG$ - No device_usage field in step (intention={current_step.get('intention', 'Unknown')!r})")

        # Check if current step includes device usage
        if current_step and "device_usage" in current_step and current_step["device_usage"]:
            device_usage = current_step["device_usage"]

            # Log device usage if internet is available
            if self.connected_antenna or self.home_leased_ips:
                try:
                    action_type = device_usage.get("action_type", "browse")
                    if isinstance(action_type, list):
                        action_type = action_type[0] if action_type else None
                    if not isinstance(action_type, str):
                        action_type = None
                except Exception:
                    action_type = None

                if action_type:
                    await self.log_device_action(
                        task_type=action_type,
                        action_description=device_usage.get("device_action", "Use device for task"),
                        task_target=current_step.get("intention", "Unknown task"),
                        metadata={
                            "step_type": current_step.get("type", "other"),
                            "step_index": step_index,
                            "plan_target": current_plan.get("target", "Unknown")
                        }
                    )
                else:
                    print(f"$DEVICE$ - {self.name} skipping device action: unexpected action_type format: {device_usage.get('action_type')}")
            else:
                print(f"$DEVICE$ - {self.name} planned to use device for '{current_step.get('intention')}' but has no internet")

        # Call parent step execution to actually execute the step
        await super().step_execution()

    async def check_and_update_step(self):
        """Override: don't let one failed step abort every step still queued behind it.

        Vendored check_and_update_step() (societyagent.py) treats a step's
        evaluation["success"]=False as failing the *whole plan* — it sets
        current_plan["failed"]=True, which update_when_plan_completed() picks
        up on the very next check and nulls current_plan immediately,
        abandoning every remaining step. Traced via run.log: agent 20's
        "Contact with friends" plan (social, social, mobility, mobility) died
        right after step 0 ("Use smartphone for social interaction") got
        SocialBlock's silent `success: False, evaluation: "No target found in
        social network"` — the two mobility steps queued behind it were never
        attempted. Mobility steps tend to sit later in a plan (after
        prep/social steps), so they were disproportionately the ones losing
        out to this.

        Flipping success to True before delegating makes the vendored logic
        advance to the next step instead of ending the plan — the step's own
        `evaluation` text (e.g. "Failed to execute ...") is left untouched, so
        evaluate_and_adjust_needs still sees what actually happened when it
        scores the plan afterward.
        """
        current_plan = await self.memory.status.get("current_plan", False)
        if current_plan:
            step_index = current_plan.get("index", 0)
            steps = current_plan.get("steps", [])
            if step_index < len(steps):
                evaluation = steps[step_index].get("evaluation")
                if evaluation and evaluation.get("success") is False:
                    print(f"$DEBUG$ - {self.name}: step {step_index} ({steps[step_index].get('intention')!r}) failed ({evaluation.get('evaluation')!r}) — skipping instead of aborting the plan")
                    evaluation["success"] = True
                    await self.memory.status.update("current_plan", current_plan)
        return await super().check_and_update_step()

    async def plan_generation(self):
        """Override to stash start-of-plan context onto the plan itself.

        We don't log here — logging a plan the moment it's generated meant the
        satisfaction delta shown was actually the *previous* plan's evaluation
        (evaluate_and_adjust_needs runs earlier in the same tick, right before
        a new plan is generated for the newly-selected need), which reads as
        if this new plan already had an effect it hasn't had yet. Instead we
        stash the plan's starting context onto current_plan itself, and
        TimeAwareNeedsBlock.evaluate_and_adjust_needs (utils/needs_block_custom.py)
        logs the plan exactly once, when its own outcome is actually known.

        The satisfaction/need snapshot itself must be fetched fresh right here,
        not cached from the top of the tick: needs_block.forward() (decay +
        update_when_plan_completed + determine_current_need) already ran
        earlier in this same forward() call, and can both finish the *previous*
        plan and select the need for *this* one in the same tick — a tick-start
        snapshot would predate the previous plan's own evaluation and mislabel
        this plan's true starting state (confirmed via run.log: a plan
        generated the instant its predecessor completed was logged with
        need_before/satisfaction_before from before that predecessor's
        evaluate_and_adjust_needs call, not the actual values in effect when
        this plan started).
        """
        cognition = await super().plan_generation()

        # cognition is non-None only when a fresh plan was just generated
        if cognition is not None:
            current_plan = await self.memory.status.get("current_plan")
            if current_plan and current_plan.get("target"):
                sim_day, sim_time = self.environment.get_datetime(format_time=True)
                current_plan["_sim_time_at_start"] = f"day{sim_day} {sim_time}"
                current_plan["_emotion_at_start"] = await self.memory.status.get("emotion_types")
                current_plan["_satisfaction_at_start"] = {
                    "hunger_satisfaction": await self.memory.status.get("hunger_satisfaction"),
                    "energy_satisfaction": await self.memory.status.get("energy_satisfaction"),
                    "safety_satisfaction": await self.memory.status.get("safety_satisfaction"),
                    "social_satisfaction": await self.memory.status.get("social_satisfaction"),
                    "current_need": await self.memory.status.get("current_need"),
                }
                await self.memory.status.update("current_plan", current_plan)

        return cognition

    async def _initialize_ict_devices(self):
        """Initialize ICT devices based on agent demographics"""
        # Get agent demographics from memory
        age = await self.memory.status.get("age", default_value=30)
        occupation = await self.memory.status.get("occupation", default_value="Other")

        # Assign devices based on demographics
        self.ict_devices = assign_devices_to_agent(age, occupation)

        device_names = [d.name for d in self.ict_devices if d.device_type.value != "none"]
        print(f"$ANTENA$ - {self.name} owns ICT devices: {', '.join(device_names) if device_names else 'none'}")

        # Initialize home router based on home AOI
        try:
            home_data = await self.memory.status.get("home")
            if home_data:
                aoi_id = home_data.get("aoi_position", {}).get("aoi_id")
                if aoi_id is not None:
                    self.home_router = get_or_create_home_router(aoi_id)
                    print(f"$ANTENA$ - {self.name} home router: subnet {self.home_router.subnet_prefix}")
        except Exception as e:
            print(f"$ANTENA$ - {self.name} could not initialize home router: {e}")

    def _select_device_for_task(self, task_type: str) -> ICTDevice:
        """
        Select the most appropriate device for a given task type.

        Args:
            task_type: Type of task (browse, shop, work, stream, social, call)

        Returns:
            The selected device, or None device if no suitable device available
        """
        # Filter devices that can perform this task
        capable_devices = [d for d in self.ict_devices if d.can_perform_task(task_type)]

        if not capable_devices:
            return None

        # Task-specific preference order — work tasks prefer stationary devices,
        # portable tasks prefer smartphone, everything else prefers smartphone too.
        task_preferences = {
            "work":   ["desktop", "laptop", "tablet", "smartphone"],
            "stream": ["desktop", "laptop", "tablet", "smartphone"],
            "browse": ["smartphone", "laptop", "tablet", "desktop"],
            "shop":   ["smartphone", "laptop", "tablet", "desktop"],
            "social": ["smartphone", "tablet", "laptop", "desktop"],
            "call":   ["smartphone", "tablet", "laptop", "desktop"],
        }
        preference_order = task_preferences.get(task_type, ["smartphone", "laptop", "tablet", "desktop"])

        for device_type in preference_order:
            for device in capable_devices:
                if device.device_type.value == device_type:
                    return device

        # Fallback to first capable device
        return capable_devices[0]

    async def _select_website_for_task(self, task_type: str, action_description: str = "") -> str:
        """
        Use LLM to select an appropriate website based on task type and action description.

        Args:
            task_type: Type of task (browse, shop, work, stream, social, call)
            action_description: Specific description of what the agent is doing

        Returns:
            Website URL or generic fallback
        """
        # Build context from agent's known websites
        known_websites_context = ""
        if self.known_websites and len(self.known_websites) > 0:
            top_sites = sorted(self.known_websites, key=lambda x: x.get('score', 0), reverse=True)[:5]
            sites_list = [f"{w['website']} (visited {w.get('count', 1)} times)" for w in top_sites]
            known_websites_context = f"\n\nAgent's frequently visited websites:\n" + "\n".join(f"- {s}" for s in sites_list)

        # Build interests context
        interests_context = ""
        if self.interests:
            top_interests = sorted(self.interests.items(), key=lambda x: x[1], reverse=True)[:3]
            interests_context = f"\n\nAgent's main interests: {', '.join(f'{k} ({v}/10)' for k, v in top_interests)}"

        # Pull candidate sites from the database for this action type
        action_type_pools = {
            "work":   WEBSITE_DATABASE.get("work_tools", []),
            "shop":   WEBSITE_DATABASE.get("e-commerce", []),
            "browse": (
                WEBSITE_DATABASE.get("news", []) +
                WEBSITE_DATABASE.get("food", []) +
                WEBSITE_DATABASE.get("travel", []) +
                WEBSITE_DATABASE.get("books", [])
            ),
            "stream": WEBSITE_DATABASE.get("movies", []) + WEBSITE_DATABASE.get("music", []),
            "social": WEBSITE_DATABASE.get("social_media", []),
            "call":   ["zoom.us", "meet.google.com", "teams.microsoft.com",
                       "skype.com", "whatsapp.com", "signal.org"],
        }
        pool = action_type_pools.get(task_type, [])
        # Merge with agent's known sites, exclude recently visited, deduplicate, sample 15
        candidates = list({s for s in pool + [w["website"] for w in self.known_websites]
                           if s not in self.recently_visited})
        if not candidates:  # all candidates were recently visited — reset and allow all
            candidates = list({s for s in pool + [w["website"] for w in self.known_websites]})
        random.shuffle(candidates)
        site_list = ", ".join(candidates[:15]) if candidates else "google.com"

        prompt = f"""You are selecting a realistic website that an agent would visit for a specific action.

Action type: {task_type}
Action description: {action_description}{interests_context}

Choose ONE website from this list that best matches the action description:
{site_list}

Rules:
1. Pick from the list above — do NOT invent a site not in the list
2. Match the action as specifically as possible (recipe search → food site, email check → mail site)
3. Return ONLY the domain (e.g., "kwestiasmaku.com"). No http://, no explanations.

Website:"""

        try:
            # Use LLM to select website
            response = await self._toolbox.llm.atext_request(
                dialog=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.7,  # Some randomness for variety
            )
            
            # Clean up the response
            website = response.strip().lower()
            # Remove common prefixes/suffixes
            website = website.replace('http://', '').replace('https://', '').replace('www.', '')
            # Take only the domain part (remove paths)
            if '/' in website:
                website = website.split('/')[0]
            # Remove any quotes or extra whitespace
            website = website.strip('"\'').strip()
            
            # Basic validation - should have a dot and be reasonable length
            if '.' in website and 3 < len(website) < 50 and ' ' not in website:
                self._record_visit(website)
                return website
            
        except Exception as e:
            print(f"$DEVICE$ - Failed to get LLM website selection: {e}")
        
        # Fallback defaults — respect action_type first, then keywords
        type_fallbacks = {
            "work":   "outlook.com",
            "shop":   "allegro.pl",
            "stream": "youtube.com",
            "social": "facebook.com",
            "call":   "zoom.us",
            "browse": "google.com",
        }
        action_lower = action_description.lower()
        if task_type in type_fallbacks:
            site = type_fallbacks[task_type]
        elif 'email' in action_lower or 'mail' in action_lower:
            site = 'gmail.com'
        elif 'news' in action_lower or 'weather' in action_lower:
            site = 'news.google.com'
        elif 'video' in action_lower or 'movie' in action_lower:
            site = 'youtube.com'
        else:
            site = 'google.com'
        self._record_visit(site)
        return site

    def _record_visit(self, website: str, max_history: int = 10):
        """Track recently visited sites to prevent the same site being picked repeatedly."""
        if website in self.recently_visited:
            self.recently_visited.remove(website)
        self.recently_visited.append(website)
        if len(self.recently_visited) > max_history:
            self.recently_visited.pop(0)

    async def log_device_action(self, task_type: str, action_description: str, task_target: str = None, metadata: dict = None):
        """
        Log that the agent used a device to perform an action.

        Args:
            task_type: Type of task (browse, shop, work, stream, social, call)
            action_description: What the agent did
            task_target: What task was being solved
            metadata: Additional information
        """
        # Check if agent has internet (antenna or home WiFi)
        if not self.connected_antenna and not self.home_leased_ips:
            print(f"$DEVICE$ - {self.name} tried to use device but has no internet connection")
            return

        # Select appropriate device
        device = self._select_device_for_task(task_type)

        if not device or device.device_type.value == "none":
            print(f"$DEVICE$ - {self.name} has no device capable of task: {task_type}")
            return

        device_id = f"{self.id}_{device.device_type.value}"

        # Select an appropriate website for this task using LLM
        website = await self._select_website_for_task(task_type, action_description)

        # Get the stable per-site browser ID for this (device, site) pair
        browser_id = device.get_browser_id_for_site(website) if website else None

        # Resolve current IP and simulated time
        ip_address = self._get_current_ip(device_id)
        sim_day, sim_time = self.environment.get_datetime(format_time=True)

        # Add website to metadata
        enhanced_metadata = metadata.copy() if metadata else {}
        if website:
            enhanced_metadata["website_visited"] = website

        # Log the device usage with website information
        log_device_usage(
            agent_id=self.id,
            agent_name=self.name,
            device_id=device_id,
            device_type=device.device_type.value,
            device_name=device.name,
            browser_id=browser_id,
            action_type=task_type,
            action_description=action_description,
            task_target=task_target,
            success=True,
            metadata=enhanced_metadata,
            website=website,
            ip_address=ip_address,
            sim_time=f"day{sim_day} {sim_time}",
        )

        if website:
            print(f"$DEVICE$ - {self.name} used {device.name} to visit {website}: {action_description}")
        else:
            print(f"$DEVICE$ - {self.name} used {device.name} to: {action_description}")

    def _get_current_ip(self, device_id: str):
        """Return the current IP address for a device, or None if unavailable."""
        if device_id in self.home_leased_ips:
            return self.home_leased_ips[device_id]
        if self.connected_antenna:
            for conn in self.connected_antenna.connected_devices.get(self.id, []):
                if conn.get("device_id") == device_id:
                    return conn.get("ip_address")
        return None

    async def _handle_website_browsing(self, duration: int):
        """Handle website browsing logic"""
        if not self.connected_antenna:
            self.current_website = None
            self.website_start_time = None
            return

        # If not currently browsing, decide whether to start
        if not self.current_website:
            if random.random() < 0.3:  # 30% chance to start browsing
                await self._start_browsing()
        else:
            # Update browsing duration
            self.browsing_duration += duration
            
            # Check if we should stop browsing
            if self.browsing_duration >= self.expected_duration:
                await self._stop_browsing()

    async def _start_browsing(self):
        """
        Start browsing a new website using the antenna's surf_internet method
        """
        if not self.connected_antenna:
            return

        website, duration = self.connected_antenna.surf_internet(
            agent_id=self.id,
            agent_name=self.name,
            interests=self.interests,
            known_websites=self.known_websites
        )

        if website:
            self.current_website = website
            self.website_start_time = datetime.datetime.now()
            self.browsing_duration = 0
            self.expected_duration = duration
            print(f"$ANTENA$ - {self.name} started browsing {website}")

            # Log the device usage for browsing
            self.log_device_action(
                task_type="browse",
                action_description=f"Browse {website}",
                task_target="Access information online",
                metadata={"website": website, "expected_duration": duration}
            )

    async def _stop_browsing(self):
        """
        Stop browsing current website
        """
        if self.current_website:
            print(f"$ANTENA$ - {self.name} stopped browsing {self.current_website} after {self.browsing_duration} ticks")
            self.current_website = None
            self.website_start_time = None
            self.browsing_duration = 0
            self.expected_duration = 0

    def _is_at_home(self, position: dict) -> bool:
        if self.home_xy is None or self.home_router is None:
            return False
        dx = position["x"] - self.home_xy["x"]
        dy = position["y"] - self.home_xy["y"]
        return (dx * dx + dy * dy) ** 0.5 < HOME_AT_DISTANCE

    async def connect_to_nearest_antenna(self, position: dict):
        # Capture home position on first call (agents start at home)
        if self.home_xy is None:
            self.home_xy = {"x": position["x"], "y": position["y"]}

        at_home = self._is_at_home(position)

        if at_home:
            # Disconnect from antenna if was connected
            if self.connected_antenna:
                self.connected_antenna.disconnect_agent(self.id)
                self.connected_antenna = None

            # Connect to home router if not already connected
            if self.home_router and not self.home_leased_ips:
                self.home_leased_ips = self.home_router.connect_devices(
                    agent_id=self.id,
                    agent_name=self.name,
                    devices=self.ict_devices,
                )
                print(f"$ANTENA$ - {self.name} connected to home WiFi ({self.home_router.subnet_prefix})")
        else:
            # Disconnect from home router if was connected
            if self.home_router and self.home_leased_ips:
                self.home_router.disconnect_devices(
                    agent_id=self.id,
                    agent_name=self.name,
                    devices=self.ict_devices,
                    leased_ips=self.home_leased_ips,
                )
                self.home_leased_ips = {}
                print(f"$ANTENA$ - {self.name} disconnected from home WiFi")

            # Disconnect from previous antenna
            if self.connected_antenna:
                self.connected_antenna.disconnect_agent(self.id)
                self.connected_antenna = None

            nearest_antenna = await self.get_nearest_antenna(position, 10000.0)
            if nearest_antenna:
                self.connected_antenna = nearest_antenna
                nearest_antenna.connect_agent(
                    agent_id=self.id,
                    agent_name=self.name,
                    devices=self.ict_devices,
                )
                print(f"$ANTENA$ - {self.name} connected to antenna {nearest_antenna.id} at position {position}")
                logger.info(f"{self.name} connected to antenna {nearest_antenna.id} - {position}")
            else:
                print(f"$ANTENA$ - {self.name} is out of range of any antenna at position {position}")
                logger.warning(f"{self.name} is out of range of any antenna - {position}")

    async def get_nearest_antenna(self, agent_position: dict, range_meters: float):
        nearest = min(ANTENNAS, key=lambda a: self._distance(agent_position, a.position))
        return nearest if nearest.is_within_range(agent_position) else None

    def _distance(self, pos1: dict, pos2: dict) -> float:
        pos = math.sqrt(
            (pos1["x"] - pos2["x"]) ** 2 + (pos1["y"] - pos2["y"]) ** 2
        )
        return pos

    def _assign_interests(self):
        """
        Assigns the agent 3 to 5 main interests with a score from 0 to 10.
        """
        all_interests = list(WEBSITE_DATABASE.keys())
        num_interests = random.randint(3, 5)
        selected_interests = random.sample(all_interests, num_interests)
        
        interests_with_scores = {}
        for interest in selected_interests:
            interests_with_scores[interest] = random.randint(0, 10)
        return interests_with_scores
    
    def _generate_initial_websites(self):
        """
        Generates a base set of websites based on the agent's main interests.
        """
        initial_websites = []
        for interest, score in self.interests.items():
            num_sites_to_add = max(1, min(5, int(score / 2) + 1))

            available_sites = WEBSITE_DATABASE.get(interest, [])
            if available_sites:
                selected_sites = random.sample(
                    available_sites, 
                    min(len(available_sites), num_sites_to_add)
                )

                for site in selected_sites:
                    website_score = random.randint(0, 10) 
                    initial_websites.append({
                        "website": site,
                        "score": website_score,
                        "count": 1,
                        "timestamp": datetime.datetime.now().isoformat()
                    })
        return initial_websites
        return initial_websites
