---
name: Morning Briefing
triggers: [briefing, morning, daily summary, daily update, start my day]
description: Creates a daily briefing with tasks, memories, and relevant news
---
Generate a morning briefing for the user:

1. Use recall_memories to find recent context and ongoing projects
2. Use todo_list to show pending tasks
3. Use web_search for any relevant news in the user's domains of interest
4. Compile into a clean briefing:

## Good Morning Briefing

### Pending Tasks
(from todo list)

### Recent Context
(from memories — what were we working on?)

### Relevant News
(brief headlines with links if web search is enabled)

### Suggested Focus
(based on task priorities and recent context)

Keep it concise and actionable.
