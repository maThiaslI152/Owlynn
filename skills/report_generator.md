---
name: Report Generator
triggers: [create report, write report, generate report, draft report, report on, weekly report, monthly report]
description: Creates structured reports with sections, data, and formatting
---
Generate a professional report:

1. If topic or scope is unclear, use ask_user:
   ask_user(question="What should the report cover?", choices="Project status,Analysis,Proposal")

2. Structure:
   # {Report Title}
   **Date:** {current date}
   **Prepared by:** {user name from memory}

   ## Executive Summary
   2-3 sentences covering the key takeaway.

   ## Background / Context
   Why this report exists.

   ## Findings / Analysis
   Main content with data, bullet points, and tables where helpful.

   ## Recommendations
   Actionable next steps.

   ## Appendix (if needed)
   Supporting data or references.

3. If the user wants web data, use web_search + fetch_webpage to gather current info.
4. For data comparisons, include tables or use the visual comparison skill.
5. Save as create_docx or create_pdf when the user wants a file.

Topic: {context}
