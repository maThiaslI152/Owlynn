---
name: Meeting Notes to Actions
triggers: [meeting notes, action items, meeting summary, minutes, follow up, takeaways, standup, retrospective, retro, planning meeting]
description: Turns meeting notes or transcripts into structured action items
category: productivity
tools_used: [read_workspace_file, todo_add, create_docx]
chain_compatible: true
version: "2.0"
---
Process the meeting notes and produce structured output.

**Detect the meeting type and adapt the template:**

### Standup / Daily Sync
If the notes mention standup, daily sync, or brief status updates, use this format:
- **Yesterday**: What was completed
- **Today**: What's planned
- **Blockers**: Any impediments
- **Action Items**: Quick table of follow-ups

### Retrospective
If the notes mention retro, retrospective, or lessons learned, use this format:
- **What Went Well**: Positive outcomes and wins
- **What Didn't Go Well**: Pain points and issues
- **What to Improve**: Concrete changes for next iteration
- **Action Items**: Assigned improvements with owners

### Planning Meeting
If the notes mention planning, sprint planning, or goal-setting, use this format:
- **Goals**: What the team aims to achieve
- **Assignments**: Who owns what
- **Timeline**: Key dates and milestones
- **Dependencies**: Cross-team or external blockers
- **Action Items**: Tasks with owners and deadlines

### General Meeting (default)
For all other meetings, use the standard format:

## Meeting Summary
- Date and participants (if mentioned)
- 2-3 sentence overview of what was discussed

## Key Decisions
- List each decision made with context

## Action Items
| # | Task | Owner | Deadline | Priority |
|---|------|-------|----------|----------|
| 1 | ... | ... | ... | High/Med/Low |

## Open Questions
- Items that need follow-up or weren't resolved

If the user provides a file, use read_workspace_file first.
If they want the output saved, use create_docx to generate a Word document.
Add each action item to the todo list using todo_add.

Input: {context}
