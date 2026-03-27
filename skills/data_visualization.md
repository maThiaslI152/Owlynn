---
name: Data Visualization
triggers: [chart, graph, plot, visualize data, bar chart, pie chart, histogram, trend]
description: Generates charts and graphs using notebook_run with matplotlib
---
When the user wants data visualized as a chart or graph:

1. Gather the data from the user's message, workspace files, or web search.

2. Use notebook_run to generate the chart with matplotlib:

```python
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

# Example: bar chart
labels = ['A', 'B', 'C']
values = [10, 25, 15]

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(labels, values, color='#c79a3b')
ax.set_title('Title Here')
ax.set_ylabel('Value')

# Dark theme to match Owlynn UI
fig.patch.set_facecolor('#121b30')
ax.set_facecolor('#121b30')
ax.tick_params(colors='#e7edf8')
ax.xaxis.label.set_color('#e7edf8')
ax.yaxis.label.set_color('#e7edf8')
ax.title.set_color('#e7edf8')
for spine in ax.spines.values():
    spine.set_color('#2a3656')

plt.tight_layout()
plt.savefig('/path/to/workspace/chart.png', dpi=150, facecolor=fig.get_facecolor())
plt.close()
print('Chart saved to chart.png')
```

3. After saving, tell the user the file is in their workspace.

4. For simple comparisons that don't need a saved file, use inline HTML bars in the chat response instead (faster, no file needed).

Chart types to consider:
- Bar chart: comparing quantities
- Line chart: trends over time
- Pie chart: proportions/percentages
- Horizontal bar: ranking items
- Grouped bar: comparing multiple metrics

Topic: {context}
