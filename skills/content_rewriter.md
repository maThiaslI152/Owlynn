---
name: Content Rewriter
triggers: [rewrite, rephrase, improve writing, make it better, polish, proofread, edit text, tone, paraphrase]
description: Rewrites or improves text with adjustable tone and style
category: writing
params:
  - name: style
    description: "Writing style preset: academic, casual, technical, marketing"
    required: false
    default: ""
tools_used: [read_workspace_file, write_workspace_file]
chain_compatible: true
version: "2.0"
---
Rewrite or improve the provided text.

**Style presets ({style}):**
- **academic**: Formal tone, precise language, passive voice acceptable, cite-ready structure. Avoid contractions and colloquialisms.
- **casual**: Conversational, friendly, uses contractions and simple words. Reads like a blog post or chat message.
- **technical**: Clear and precise, uses domain-specific terminology correctly, structured with headings and lists. Prioritize accuracy over flair.
- **marketing**: Persuasive, benefit-focused, uses power words and calls to action. Short punchy sentences, emotional hooks.
- **(empty/unset)**: Ask the user how to adjust the text.

1. If no style is set and no specific direction given, use ask_user:
   ask_user(question="How should I adjust the text?", choices="More professional,Simpler/clearer,Shorter,More engaging")

2. Preserve the original meaning while improving:
   - **Clarity**: remove jargon (unless technical style), simplify complex sentences
   - **Flow**: better transitions, logical order
   - **Tone**: match the requested style preset
   - **Grammar**: fix errors without changing voice

3. Show the result with changes highlighted where possible.

4. If the text is from a file, use read_workspace_file first.
   If the user wants the result saved, use write_workspace_file.

Input: {context}
