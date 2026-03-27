---
name: Document Summarizer
triggers: [summarize, summary, tldr, key points, overview]
description: Creates a structured summary of a document or text
---
Create a comprehensive summary of the provided content:

1. Use read_workspace_file to load the document if a filename is mentioned
2. Generate:
   - One-paragraph executive summary
   - Key points (5-10 bullet points)
   - Important details or data points
   - Action items (if applicable)

Keep the summary concise but complete. Preserve important numbers, dates, and names.

Input: {context}
