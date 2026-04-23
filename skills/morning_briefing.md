---
name: Morning Briefing
triggers: [briefing, morning, daily summary, daily update, start my day, afternoon briefing, catch me up, daily briefing]
description: Creates a daily briefing with tasks, memories, and relevant news
category: productivity
tools_used: [recall_memories, todo_list, web_search]
chain_compatible: true
version: "2.0"
---
Generate a daily briefing for the user.

**Time-awareness hints:**
- If it's morning (before noon), greet with "Good Morning" and focus on planning the day ahead — prioritize tasks, set goals.
- If it's afternoon or later, greet with "Good Afternoon" and focus on a catch-up — what's happened today, what's remaining, any urgent items.

**Project-specific focus:**
- Use recall_memories to find active project context, recent conversations, and ongoing work threads. Highlight the most relevant project the user has been working on.
- If recall_memories returns project-specific context, include a dedicated section for that project's status and next steps.

1. Use recall_memories to find recent context and ongoing projects
2. Use todo_list to show pending tasks
3. Use web_search for any relevant news in the user's domains of interest
4. Compile into a clean briefing:

## Daily Briefing

### 🎯 Active Project Focus
(from recall_memories — what project are we deep in? What's the current status?)

### ✅ Pending Tasks
(from todo list — prioritized, with suggested order of attack)

### 🧠 Recent Context
(from memories — what were we working on? Any threads to pick up?)

### 📰 Relevant News
(brief headlines with links if web search is enabled)

### 💡 Suggested Focus
(based on task priorities, project context, and time of day)

Keep it concise and actionable. No fluff — just what the user needs to get moving.
