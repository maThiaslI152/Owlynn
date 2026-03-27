---
name: Email Drafter
triggers: [draft email, write email, compose email, reply email, email to, send email]
description: Drafts professional emails with proper structure and tone
---
Draft an email based on the user's intent:

1. If the purpose is unclear, use ask_user with choices like:
   ask_user(question="What type of email?", choices="Follow-up,Request,Thank you")

2. Structure the email:
   - Subject line (concise, specific)
   - Greeting (match formality to context)
   - Body (clear purpose in first sentence, details, call to action)
   - Sign-off

3. Match the tone to the situation:
   - Professional: business, clients, management
   - Friendly: colleagues, team members
   - Formal: external partners, official requests

4. If the user wants it saved, use write_workspace_file to save as .txt or create_docx.

Keep emails concise. Most business emails should be under 150 words.

Context: {context}
