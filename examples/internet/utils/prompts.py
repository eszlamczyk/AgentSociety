CUSTOM_BLOCK_DISPATCH_PROMPT = """
Select the most appropriate block to handle the task below.

Task intention: ${context.current_intention}

Block selection rules (pick exactly one):
- mobilityblock: moving, traveling, commuting, going somewhere, walking, driving
- economyblock: shopping, buying, working, earning, spending money, business tasks
- socialblock: talking to people, meeting friends/family, social interaction, chatting
- otherblock: EVERYTHING else — including sleep, rest, relaxing, eating, cooking,
              personal hygiene, hobbies, entertainment, setting alarms, preparing for bed,
              transitioning to sleep, waking up, exercising, reading, any activity
              that is not movement, economic, or social

When in doubt, choose otherblock.
"""

INTERNET_AWARENESS_PROMPT = """
IMPORTANT: You are living in a modern digital society where the internet and ICT devices play a crucial role in daily life.

Your ICT Device Status:
${profile.ict_devices}

Internet Connectivity:
${profile.has_internet}

Key Points to Remember:
1. If you have internet-connected devices, you can accomplish many tasks remotely:
   - Information gathering: Search websites, read news, research topics
   - Shopping: Browse e-commerce sites, compare prices, make purchases online
   - Entertainment: Stream movies/music, browse social media, read articles
   - Social connection: Video calls, messaging, social media interaction
   - Work: Remote work tasks, email, online collaboration

2. Your devices have different capabilities - check what your specific devices can do

3. Internet connectivity is required for online activities - if you're out of antenna range, you cannot use internet features

4. Use the internet as a COMPLEMENT to physical life — use it to prepare for activities (check prices before shopping, look up directions before commuting) or for tasks that genuinely don't require leaving home (remote work, streaming, messaging). Do NOT replace physical activities like going to the grocery store, commuting to work, or visiting friends just because you have internet.

5. Match your activities to your interests: you have specific interests that can guide what websites you visit
"""

CUSTOM_DETAILED_PLAN_PROMPT = """As an intelligent agent's plan system, please help me generate specific execution steps based on the selected guidance plan. 
The Environment will influence the choice of steps.

Current weather: ${context.weather}
Current temperature: ${context.temperature}
Other information: 
-------------------------
${context.other_information}
-------------------------

Plan target: ${context.plan_target}
Current location: ${context.current_position} 
Current time: ${context.current_time}
My income/consumption level: ${profile.consumption}
My occupation: ${profile.occupation}
My age: ${profile.age}
My emotion: ${profile.emotion_types}
My thought: ${context.current_thought}

# Internet and ICT Device Information:
My ICT devices and capabilities: ${profile.ict_devices}
Internet connectivity status: ${profile.has_internet}
My interests (ranked 0-10): {{agent.interests}}
My known websites (website, score, count): {{agent.known_websites}}
Am I currently browsing the internet? {{agent.is_browsing_internet}}

# Daily Routine — Time of Day:
Use the current time AND your occupation/age to decide what makes sense to do right now.
People's schedules differ — do NOT follow a generic template. Instead, apply the rules below:

## Weekday vs Weekend
Current simulation day and time: ${profile.current_day_info}
- On WEEKDAYS: work obligations dominate the day for employed adults and students.
- On WEEKENDS: no work or school. Sleep in if you want. Focus on leisure, social activities, errands, sports, family.

## Occupation-based rhythm (weekdays)
- **Office worker / professional**: commute ~08:00, work 09:00–17:00 at workplace, commute back, errands on the way home.
- **Student**: morning classes (often ~08:00–13:00), afternoon free time, evenings studying or socializing.
- **Teacher**: early start ~07:30, school until ~15:00, afternoon preparation or leisure.
- **Retired / elderly**: flexible schedule, wake early (~06:00), morning walk or errands, afternoon rest or social visits, early evening.
- **Self-employed / freelancer**: flexible hours, may work from home but also meets clients, runs errands during off-peak hours.
- **Healthcare / shift worker**: schedule varies, may work evenings or nights — adapt accordingly.
- **Unemployed**: free schedule, but still leaves home for errands, social activities, job-seeking.

## Age adjustments
- Young adults (18–30): stay up later (00:00+), active social life, bars, gyms, events in evenings.
- Middle-aged (30–55): earlier bedtime (~23:00), family obligations, grocery runs after work.
- Elderly (65+): early to bed (~21:00), early morning walks, daytime errands, avoid late nights.

## General rhythm (applies to everyone)
- Early morning (06:00–08:00): wake up, hygiene, breakfast — mostly at home.
- Late night (23:30–06:00): sleep — no activities, no device usage. If the plan target is sleep, generate exactly ONE step with intention "Sleep" and type "other". Do not generate sub-steps like "prepare for sleep", "set alarm", or "verify sleep intention".
- Respect your circadian rhythm: real sleep belongs at night. During normal daytime hours, prefer a short rest/break over a full "sleep" plan unless there's a clear reason (illness, night-shift work, jet lag).
- Work (see occupation-based rhythm above) anchors the middle of the day for employed adults and students.
- Mealtimes loosely around breakfast, lunch, and dinner often anchor movement — going out to eat, cooking, grocery shopping — the exact time can vary.
- People leave home multiple times per day for different reasons — do not cluster everything at home.

**IMPORTANT:** Physical presence matters. Go to the workplace, grocery store, gym, park, friends' homes. Use the internet to prepare or complement these activities, not replace them.

Notes:
1. type can only be one of these four: mobility, social, economy, other
    1.1 mobility: Decisions or behaviors related to large-scale spatial movement, such as location selection, going to a place, etc.
    1.2 social: Decisions or behaviors related to social interaction, such as finding contacts, chatting with friends, etc.
    1.3 economy: Decisions or behaviors related to shopping, work, etc.
    1.4 other: Other types of decisions or behaviors, such as small-scale activities, learning, resting, entertainment, etc.
2. steps should only include steps necessary to fulfill the target (limited to ${context.max_plan_steps} steps)
3. intention in each step should be concise and clear
4. **IMPORTANT - ICT Device Usage:**
   - If you have ICT devices and internet connectivity, you can use them to accomplish many tasks without physical movement
   - For each step, you can OPTIONALLY specify device_usage if using a device helps accomplish the task
   - device_usage should include:
     * device_action: what you're doing with the device (e.g., "search for recipe", "check grocery prices", "look up directions", "browse news")
     * action_type: one of [browse, shop, work, social, stream, call]
   - Examples of when to use devices:
     * Before cooking: search for recipes online
     * Before shopping: check online prices and create shopping list
     * Before traveling: look up directions and information about destination
     * For entertainment: stream videos or music
     * For work: use laptop for remote tasks
     * For social: make video calls or send messages
   - If you lack internet connectivity, you CANNOT use devices (device_usage should be null)
   - Your devices enable you to solve problems remotely without traveling

Please response in json format (Do not return any other text), example:
{{
    "plan": {{
        "target": "Eat at home",
        "steps": [
            {{
                "intention": "Return home from current location",
                "type": "mobility",
                "device_usage": null
            }},
            {{
                "intention": "Cook food",
                "type": "other",
                "device_usage": {{
                    "device_action": "Search for recipe online",
                    "action_type": "browse"
                }}
            }},
            {{
                "intention": "Have meal",
                "type": "other",
                "device_usage": null
            }}
        ]
    }}
}}
"""

# Passed via OtherBlockParams(sleep_time_estimation_prompt=...) in internet.py.
# Adds current sim time so a "Sleep" step's duration reflects a real night's
# sleep at night vs. a short rest during the day, instead of a random guess.
TIME_AWARE_SLEEP_PROMPT = """As an intelligent agent's time estimation system, please estimate the time needed to complete the current action based on the overall plan and current intention.

Overall plan:
${context.plan_context["plan"]}

Current action: ${context.current_step["intention"]}
Current simulated day/time: ${status.current_day_info}
Current emotion: ${status.emotion_types}

Respect circadian rhythm: if it's night time, this is a full night's sleep
(typically 360-540 minutes / 6-9 hours). If it's daytime, this is a short
rest/nap, not a full sleep cycle (typically 15-90 minutes) unless context
clearly justifies otherwise (illness, night-shift work).

Please return the result in JSON format (Do not return any other text), the time unit is [minute], example:
{{
    "time": 480
}}
"""