---
name: Presentation Builder
triggers: [create presentation, make slides, build deck, slide deck, powerpoint, pptx]
description: Creates structured presentations with clear slide content
---
Build a presentation:

1. If topic is unclear, use ask_user:
   ask_user(question="What's the presentation about?", choices="Project update,Proposal,Training")

2. Plan the slides (typically 5-10):
   - Title slide: topic + presenter + date
   - Agenda/Overview: what you'll cover
   - 3-6 content slides: one key point per slide
   - Summary/Next Steps: takeaways and actions
   - Q&A slide (optional)

3. For each slide, write:
   - A clear title (5-7 words max)
   - 3-5 bullet points (concise, not full sentences)
   - Speaker notes if the user asks

4. Use create_pptx to generate the file:
   Separate slides with --- on its own line.
   First line of each slide = title, rest = bullets starting with -

5. If the user provides source material (file or topic), read it first and extract key points.

Topic: {context}
