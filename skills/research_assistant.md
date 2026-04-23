---
name: Research Assistant
triggers: [research, deep dive, investigate, analysis, report on, look into, find out about, study]
description: Generates a detailed, source-backed research overview on any topic
category: research
params:
  - name: depth
    description: "Research depth: quick (1-2 sources), standard (3-5 sources), deep (5+ sources with cross-referencing)"
    required: false
    default: standard
tools_used: [web_search, fetch_webpage]
chain_compatible: true
version: "2.0"
---
You are conducting thorough research on the following topic. Follow this workflow:

**Adjust effort based on depth level ({depth}):**
- **quick**: Use web_search to find 1-2 authoritative sources. Provide a concise overview with key takeaways.
- **standard**: Use web_search to find 3-5 authoritative sources on the topic. Use fetch_webpage with focus_query on the most relevant URLs. Synthesize into a structured report.
- **deep**: Use web_search to find 5+ sources across different perspectives. Use fetch_webpage on each. Cross-reference claims between sources, note agreements and contradictions, and provide a comprehensive analysis.

**Output structure:**
1. **Executive Summary** (2-3 sentences)
2. **Key Findings** (numbered, with [1], [2] citations)
3. **Sources Used** (with URLs)
4. **Open Questions / Areas for Further Research**

Ground every claim in source material. Use [1], [2] citations.
If sources conflict, note the disagreement and explain which source appears more authoritative and why.

If web_search returns no useful results, acknowledge the limitation and suggest alternative search terms or approaches.

Topic: {context}
