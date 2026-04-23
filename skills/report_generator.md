---
name: Report Generator
triggers: [create report, write report, generate report, draft report, report on, weekly report, monthly report, status report]
description: Creates structured reports with sections, data, and formatting
category: writing
params:
  - name: report_type
    description: "Report type: status, analysis, proposal, summary"
    required: false
    default: analysis
tools_used: [web_search, fetch_webpage, read_workspace_file, create_docx, create_pdf, notebook_run]
chain_compatible: true
version: "2.0"
---
Generate a professional report.

**Adapt structure based on report type ({report_type}):**

### Status Report
- **Period**: Date range covered
- **Highlights**: Top 3-5 accomplishments
- **In Progress**: Current work with % completion
- **Blockers**: Issues needing attention
- **Next Steps**: Planned work for next period

### Analysis Report (default)
- **Executive Summary**: 2-3 sentences covering the key takeaway
- **Background / Context**: Why this report exists
- **Findings / Analysis**: Main content with data, bullet points, and tables
- **Recommendations**: Actionable next steps
- **Appendix**: Supporting data or references

### Proposal Report
- **Problem Statement**: What needs solving
- **Proposed Solution**: Detailed approach
- **Cost / Effort Estimate**: Resources required
- **Timeline**: Key milestones
- **Risks & Mitigations**: What could go wrong
- **Recommendation**: Clear ask or decision needed

### Summary Report
- **Overview**: Brief context
- **Key Points**: Numbered list of main takeaways
- **Data Highlights**: Important numbers or trends
- **Conclusion**: One-paragraph wrap-up

**General guidance:**

1. If topic or scope is unclear, use ask_user:
   ask_user(question="What should the report cover?", choices="Project status,Analysis,Proposal,Summary")

2. **Data integration**: For data-heavy reports, use notebook_run to compute statistics, generate tables, or create charts. Use read_workspace_file to pull data from workspace files.

3. If the user wants web data, use web_search + fetch_webpage to gather current info.

4. For data comparisons, include tables or reference the visual comparison skill.

5. Save as create_docx or create_pdf when the user wants a file.

If a section has no relevant content, omit it rather than filling with placeholder text.

Topic: {context}
