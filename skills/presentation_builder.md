---
name: Presentation Builder
triggers: [create presentation, make slides, build deck, slide deck, powerpoint, pptx, pitch deck]
description: Creates structured presentations with clear slide content
category: communication
params:
  - name: audience
    description: "Target audience: executive, technical, general, training"
    required: false
    default: general
tools_used: [read_workspace_file, create_pptx]
chain_compatible: true
version: "2.0"
---
Build a presentation tailored to the audience.

**Slide count guidance based on audience ({audience}):**
- **executive**: 5-7 slides — focus on outcomes, decisions, and high-level metrics. Minimal text, maximum impact.
- **technical**: 8-12 slides — include architecture diagrams, code snippets, data, and detailed specs.
- **general**: 7-10 slides — balanced depth, clear explanations, avoid jargon.
- **training**: 10-15 slides — step-by-step progression, examples, exercises, and recap slides.

1. If topic is unclear, use ask_user:
   ask_user(question="What's the presentation about?", choices="Project update,Proposal,Training,Technical deep-dive")

2. Plan the slides:
   - **Title slide**: topic + presenter + date
   - **Agenda/Overview**: what you'll cover
   - **Content slides**: one key point per slide (count based on audience)
   - **Summary/Next Steps**: takeaways and actions
   - **Q&A slide** (optional, skip for training decks)

3. For each slide, write:
   - A clear title (5-7 words max)
   - 3-5 bullet points (concise, not full sentences)
   - Speaker notes if the user asks

4. Use create_pptx to generate the file:
   Separate slides with --- on its own line.
   First line of each slide = title, rest = bullets starting with -

5. If the user provides source material (file or topic), use read_workspace_file to read it first and extract key points.

6. Audience-specific tips:
   - **Executive**: Lead with the "so what?" — business impact first, details in appendix
   - **Technical**: Include diagrams, specs, and data — depth is expected
   - **General**: Define terms, use analogies, keep it accessible
   - **Training**: Build concepts progressively, include practice exercises

Topic: {context}
