---
name: Brainstorm
triggers: [brainstorm, ideas, suggest, what if, how might we, creative, options]
description: Generates structured ideas and options for any topic
---
Run a structured brainstorm:

1. Generate 5-8 ideas organized by category or approach.

2. For each idea:
   - **Name**: catchy 3-5 word title
   - **Description**: 1-2 sentences explaining the idea
   - **Pros**: why it could work
   - **Effort**: Low / Medium / High

3. Format as a clean list, then rank the top 3 with brief reasoning.

4. If the topic is broad, use ask_user first:
   ask_user(question="What aspect should I focus on?", choices="Quick wins,Big bets,Cost saving")

5. If the user wants to save the brainstorm, use write_workspace_file or create_docx.

Topic: {context}
