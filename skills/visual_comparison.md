---
name: Visual Comparison
triggers: [compare, comparison, versus, vs, side by side, chart, graph, visualize, plot]
description: Creates visual comparisons using charts, tables, and graphs rendered as HTML
---
When the user wants to compare items, services, or options, create a visual response:

1. First gather the data:
   - If comparing known things, use your knowledge
   - If comparing with live data, use web_search + fetch_webpage
   - If comparing from a file, use read_workspace_file

2. Structure the comparison as BOTH:
   a) A markdown table for quick reading
   b) An HTML chart/graph embedded in the response using this pattern:

For bar charts, use inline HTML like:
```html
<div style="font-family:sans-serif;max-width:600px">
  <div style="display:flex;align-items:end;gap:8px;height:200px;padding:8px 0;border-bottom:1px solid #555">
    <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
      <div style="width:100%;background:#c79a3b;border-radius:4px 4px 0 0;height:{percent1}%"></div>
      <span style="font-size:11px">{label1}</span>
    </div>
    <!-- repeat for each item -->
  </div>
</div>
```

For comparison cards, use:
```html
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:600px">
  <div style="padding:12px;border:1px solid #2a3656;border-radius:8px">
    <strong>{Option A}</strong>
    <ul><li>Feature 1</li><li>Feature 2</li></ul>
    <div style="color:#c79a3b;font-weight:600">{Price A}</div>
  </div>
  <div style="padding:12px;border:1px solid #2a3656;border-radius:8px">
    <strong>{Option B}</strong>
    <ul><li>Feature 1</li><li>Feature 2</li></ul>
    <div style="color:#c79a3b;font-weight:600">{Price B}</div>
  </div>
</div>
```

3. If the user needs a saved file, use notebook_run to generate a proper chart with matplotlib and save it to workspace, or create_pdf/create_docx with the comparison data.

4. Always include a brief text summary with your recommendation after the visual.

Topic: {context}
