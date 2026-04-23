---
name: Email Drafter
triggers: [draft email, write email, compose email, reply email, email to, send email, respond to email]
description: Drafts professional emails with proper structure and tone
category: writing
params:
  - name: tone
    description: "Email tone: professional, friendly, formal, casual"
    required: false
    default: professional
tools_used: [write_workspace_file, create_docx]
chain_compatible: true
version: "2.0"
---
Draft an email based on the user's intent.

**Reply vs. New Email Detection:**
- If the context mentions "reply", "respond", "follow up on", "RE:", or quotes a previous message, format as a **reply**: acknowledge the original message, then address the points raised.
- Otherwise, format as a **new email** with a fresh subject line.

**Tone ({tone}):**
- **professional**: Business-appropriate, clear and direct, moderate formality
- **friendly**: Warm and personable, conversational but still polished
- **formal**: High formality, suitable for executives, external partners, official requests
- **casual**: Relaxed and brief, suitable for close colleagues or quick notes

1. If the purpose is unclear, use ask_user with choices like:
   ask_user(question="What type of email?", choices="Follow-up,Request,Thank you,Introduction,Apology")

2. Structure the email:
   - **Subject line** (concise, specific — skip for replies)
   - **Greeting** (match formality to tone setting)
   - **Body** (clear purpose in first sentence, supporting details, call to action)
   - **Sign-off** (match tone: "Best regards" for formal, "Thanks!" for casual)

3. Length guidance:
   - Most business emails should be under 150 words
   - Formal proposals or detailed requests can be longer but should use bullet points for scannability

4. If the user wants it saved, use write_workspace_file to save as .txt or create_docx.

If the email fails to capture the right tone, suggest alternatives and let the user pick.

Context: {context}
