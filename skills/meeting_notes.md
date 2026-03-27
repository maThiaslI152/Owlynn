---
name: Meeting Notes to Actions
triggers: [meeting notes, action items, meeting summary, minutes, follow up, takeaways]
description: Turns meeting notes or transcripts into structured action items
---
Process the meeting notes and produce:

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
