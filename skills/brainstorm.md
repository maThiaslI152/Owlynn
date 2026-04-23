---
name: Brainstorm
triggers: [brainstorm, ideas, suggest, what if, how might we, creative, options, ideate, think of ways]
description: Generates structured ideas and options for any topic
category: communication
params:
  - name: method
    description: "Brainstorming method: freeform, scamper, six_hats, mind_map"
    required: false
    default: freeform
tools_used: [write_workspace_file, create_docx]
chain_compatible: true
version: "2.0"
---
Run a structured brainstorm using the selected method.

**Method guidance ({method}):**

### Freeform (default)
Generate 5-8 ideas organized by category or approach. For each idea:
- **Name**: catchy 3-5 word title
- **Description**: 1-2 sentences explaining the idea
- **Pros**: why it could work
- **Effort**: Low / Medium / High
Then rank the top 3 with brief reasoning.

### SCAMPER
Apply each SCAMPER lens to the topic:
- **S**ubstitute: What can be replaced?
- **C**ombine: What can be merged or blended?
- **A**dapt: What can be borrowed from elsewhere?
- **M**odify: What can be enlarged, shrunk, or reshaped?
- **P**ut to other use: What else could this be used for?
- **E**liminate: What can be removed or simplified?
- **R**everse: What if we did the opposite?
Generate 1-2 ideas per lens, then highlight the strongest.

### Six Thinking Hats
Explore the topic from six perspectives:
- 🎩 **White Hat** (Facts): What data do we have?
- 🎩 **Red Hat** (Feelings): What's the gut reaction?
- 🎩 **Black Hat** (Caution): What could go wrong?
- 🎩 **Yellow Hat** (Optimism): What's the best case?
- 🎩 **Green Hat** (Creativity): What new ideas emerge?
- 🎩 **Blue Hat** (Process): What's the next step?
Summarize insights from each hat, then propose a balanced recommendation.

### Mind Map
Build a visual text-based mind map:
- **Central Topic** at the center
- **3-5 main branches** (major themes or categories)
- **2-3 sub-branches** per main branch (specific ideas)
- **Connections** between branches where ideas relate
Format as an indented tree structure for clarity.

---

If the topic is broad, use ask_user first:
   ask_user(question="What aspect should I focus on?", choices="Quick wins,Big bets,Cost saving,Innovation")

If the user wants to save the brainstorm, use write_workspace_file or create_docx.

Topic: {context}
