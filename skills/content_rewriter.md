---
name: Content Rewriter
triggers: [rewrite, rephrase, improve writing, make it better, polish, proofread, edit text, tone]
description: Rewrites or improves text with adjustable tone and style
---
Rewrite or improve the provided text:

1. If no specific direction given, use ask_user:
   ask_user(question="How should I adjust the text?", choices="More professional,Simpler/clearer,Shorter")

2. Preserve the original meaning while improving:
   - Clarity: remove jargon, simplify complex sentences
   - Flow: better transitions, logical order
   - Tone: match the requested style
   - Grammar: fix errors without changing voice

3. Show the result with changes highlighted where possible.

4. If the text is from a file, use read_workspace_file first.
   If the user wants the result saved, use write_workspace_file.

Input: {context}
