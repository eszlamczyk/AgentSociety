"""
Analyze website usage from device_usage_logs.jsonl
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

def analyze_website_logs(log_file_path):
    """Analyze website usage patterns from device logs"""
    
    if not Path(log_file_path).exists():
        print(f"❌ Log file not found: {log_file_path}")
        return
    
    # Load all logs
    logs = []
    with open(log_file_path, 'r') as f:
        for line in f:
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    if not logs:
        print("❌ No logs found")
        return
    
    print(f"📊 Analyzing {len(logs)} device usage events\n")
    print("=" * 80)
    
    # 1. Overall website statistics
    websites = [log.get('website') for log in logs if log.get('website')]
    total_with_website = len(websites)
    total_without_website = len(logs) - total_with_website
    
    print(f"\n🌐 WEBSITE TRACKING STATISTICS")
    print(f"   Total events: {len(logs)}")
    print(f"   Events with website: {total_with_website} ({100*total_with_website/len(logs):.1f}%)")
    print(f"   Events without website: {total_without_website} ({100*total_without_website/len(logs):.1f}%)")
    
    if not websites:
        print("\n⚠️  No website data found in logs")
        return
    
    # 2. Top websites overall
    print(f"\n📈 TOP 10 WEBSITES (All Tasks)")
    website_counts = Counter(websites)
    for i, (website, count) in enumerate(website_counts.most_common(10), 1):
        percentage = 100 * count / total_with_website
        print(f"   {i:2d}. {website:30s} - {count:3d} visits ({percentage:5.1f}%)")
    
    # 3. Websites by task type
    print(f"\n🎯 WEBSITES BY TASK TYPE")
    task_websites = defaultdict(list)
    for log in logs:
        task_type = log.get('action_type')
        website = log.get('website')
        if task_type and website:
            task_websites[task_type].append(website)
    
    for task_type in sorted(task_websites.keys()):
        sites = task_websites[task_type]
        print(f"\n   {task_type.upper()} ({len(sites)} visits):")
        top_sites = Counter(sites).most_common(5)
        for website, count in top_sites:
            percentage = 100 * count / len(sites)
            print(f"      • {website:30s} - {count:3d} visits ({percentage:5.1f}%)")
    
    # 4. Website categories
    print(f"\n📂 WEBSITE CATEGORIES")
    categories = [log.get('metadata', {}).get('website_category') 
                  for log in logs 
                  if log.get('metadata', {}).get('website_category')]
    
    if categories:
        category_counts = Counter(categories)
        for category, count in category_counts.most_common():
            percentage = 100 * count / len(categories)
            print(f"   • {category:20s} - {count:3d} visits ({percentage:5.1f}%)")
    
    # 5. Agent-specific patterns (top 5 agents)
    print(f"\n👤 TOP 5 MOST ACTIVE AGENTS")
    agent_events = defaultdict(list)
    for log in logs:
        if log.get('website'):
            agent_id = log.get('agent_id')
            agent_name = log.get('agent_name')
            website = log.get('website')
            agent_events[agent_id].append({
                'name': agent_name,
                'website': website
            })
    
    # Sort by number of events
    top_agents = sorted(agent_events.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    
    for agent_id, events in top_agents:
        agent_name = events[0]['name']
        websites_visited = [e['website'] for e in events]
        unique_websites = len(set(websites_visited))
        
        print(f"\n   {agent_name} (ID: {agent_id})")
        print(f"      Total visits: {len(websites_visited)}, Unique websites: {unique_websites}")
        print(f"      Top websites:")
        
        for website, count in Counter(websites_visited).most_common(3):
            percentage = 100 * count / len(websites_visited)
            print(f"         • {website:30s} - {count:2d} visits ({percentage:5.1f}%)")
    
    # 6. Task completion with websites
    print(f"\n✅ TASK COMPLETION PATTERNS")
    task_targets = defaultdict(list)
    for log in logs:
        task_target = log.get('task_target')
        website = log.get('website')
        if task_target and website:
            task_targets[task_target].append(website)
    
    print(f"   Unique task targets: {len(task_targets)}")
    print(f"   Example task-website pairings:")
    
    for task_target, websites in list(task_targets.items())[:5]:
        most_common_site = Counter(websites).most_common(1)[0]
        print(f"      • '{task_target[:50]}{'...' if len(task_target) > 50 else ''}'")
        print(f"        → Most used: {most_common_site[0]} ({most_common_site[1]} times)")
    
    print("\n" + "=" * 80)
    print("✅ Analysis complete!\n")


if __name__ == "__main__":
    log_file = "../internet_logs/device_usage_logs.jsonl"
    analyze_website_logs(log_file)
