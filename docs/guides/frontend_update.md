# Frontend Updates: Cowork-like Interface & Settings

## Overview

The Owlynn frontend has been upgraded to match Cowork's professional interface and now includes comprehensive settings for system prompts, memory management, and advanced inference parameters.

## New Features

### 1. **Tabbed Settings Interface** 🎛️

The Settings modal now uses a tab-based organization with 4 main sections:

#### **Profile Tab**
- Display Name
- Preferred Language (English, Thai, Japanese, Chinese)
- Response Style (Detailed, Concise, Step-by-step)
- LLM Base URL configuration
- LLM Model Name selection

#### **System Tab** (NEW)
- **Agent Persona**: Name and tone customization
- **System Prompt**: Full custom system prompt editor with preset default
- **Reset Button**: Quickly return to default system prompt
- **Custom Instructions**: Additional guidelines for agent behavior
- Smart prompt composition for fine-grained control

#### **Memory Tab** (NEW)
- **Short-term Memory Toggle**: Enable/disable current conversation context
- **Long-term Memory Toggle**: Enable/disable cross-session memory
- **Memory Facts Manager**: 
  - Add new facts about user preferences
  - View all stored memories
  - Remove individual memories
  - Visual fact cards with delete buttons

#### **Advanced Tab** (NEW)
- **Inference Parameters**:
  - Temperature slider (0-2.0) - Controls creativity vs focus
  - Top-p (Nucleus Sampling) - Probability cutoff (0-1.0)
  - Max Tokens - Response length limit (256-8192)
  - Top-k - Token selection diversity (0-100)
  - Real-time value display as you adjust sliders

- **Behavior Options**:
  - Streaming Responses - Show generation in real-time
  - Show Thinking - Display agent reasoning process
  - Show Tool Execution - Visualize tool usage

### 2. **Visual Improvements**

#### Tab Navigation
```
Profile | System | Memory | Advanced
```
- Clean icon + label combination
- Active tab highlights with anthropic color
- Smooth transition between tabs
- Hover effects for discoverability

#### Slider Controls
- Custom styled range sliders with anthropic brand color
- Real-time value display
- Tooltips explaining each parameter
- Responsive layout (1-2 columns on mobile/desktop)

#### Memory Management
- Card-based memory display with individual delete buttons
- Add memory form with validation
- Empty state messaging
- Smooth animations

### 3. **API Endpoints** (Backend)

Four new API endpoints handle the new settings:

```
GET/POST /api/system-settings
GET/POST /api/memory-settings
GET/POST /api/advanced-settings
```

Each endpoint:
- Stores settings in user profile data
- Returns current state on GET
- Validates and saves on POST
- Provides graceful error handling

## Settings Usage

### System Prompt Customization

The system prompt defines how the agent behaves:

```
You are Owlynn, a helpful AI assistant built on LangGraph. You have access to tools for:
- Executing code in a sandboxed environment
- Reading and writing files in the workspace
- Searching the web
- Managing long-term memory
- Processing various file formats

Be clear, concise, and helpful. When using tools, explain what you're doing.
```

**Customize it to:**
- Change agent personality
- Add domain-specific expertise
- Define constraints or rules
- Specify output format preferences
- Set communication style

### Memory Management

**Short-term Memory:**
- Your current conversation context
- Token-based storage in Redis
- Useful for iterative refinement
- Better context retention within a session

**Long-term Memory:**
- Persistent facts across sessions
- Semantic search via ChromaDB
- Store preferences, skills, experiences
- Survives browser refresh

**Adding Facts:**
```
"I prefer Python over JavaScript"
"I work in backend systems"
"I like detailed explanations"
```

Agent will reference these in future conversations.

### Inference Parameters

**Temperature (0.0 - 2.0)**
- 0.0 = Deterministic, repetitive
- 0.7 = Balanced (default)
- 1.5+ = Highly creative, less focused

**Top-p (0.0 - 1.0)**
- Nucleus sampling cutoff
- 0.9 = Keep top 90% of probability mass
- Lower = More focused responses

**Max Tokens**
- Controls maximum response length
- 256 = Short responses
- 2048 = Medium responses (default)
- 8192 = Long-form outputs

**Top-k**
- Consider only top k tokens
- 40 = Default (balanced)
- Higher = More diverse
- Lower = More focused

## Implementation Details

### Frontend Changes

**index.html**
- Added 4 new settings tabs with icons
- Tab content for each section
- Range sliders with custom styling
- Memory management UI components
- Toggle switches for boolean settings

**script.js**
- Tab switching logic with active state management
- Event listeners for all sliders and toggles
- Real-time value display updates
- API fetch calls for persistence
- Loading default values from backend
- New `loadSettingsData()` with system/advanced loading

### CSS Enhancements

```css
.settings-tab { /* Tab styling */ }
.settings-tab.active { /* Active tab highlight */ }
.settings-tab-content { /* Tab content display */ }
input[type="range"] { /* Custom slider */ }
```

### Backend Changes

**server.py**
- 3 new GET endpoints to retrieve settings
- 3 new POST endpoints to persist settings
- Integration with user profile storage
- Graceful error handling

## User Experience Flow

### First-time User
1. Open Settings modal
2. Fill Profile tab (name, language, model)
3. Explore System tab to understand agent behavior
4. Try Memory tab to add personal facts
5. (Optional) Fine-tune Advanced parameters
6. Click "Save [Section] Settings"
7. Settings persist between sessions

### Power User Workflow
1. Quickly switch between Memory and Advanced tabs
2. Adjust temperature for creative tasks
3. Add facts as they discover preferences
4. Customize system prompt for specific domains
5. Use keyboard or mouse - all accessible

### Sharing Configurations
1. Copy text from System Prompt tab
2. Share with team
3. Recipients paste into their System Prompt
4. Enables team-wide behavior consistency

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Uses standard HTML/CSS/JS with graceful degradation.

## Performance Considerations

- Settings loaded once on modal open
- Async API calls don't block UI
- Range sliders use efficient input events
- Tab switching uses CSS display toggle
- No performance impact on chat functionality

## Security Notes

- All settings saved server-side in profile JSON
- No sensitive data in frontend localStorage
- System prompt sanitized before storage
- XSS protection via DOMPurify
- CORS configured for safety

## Future Enhancements

Potential additions to settings:

1. **Save/Load Presets**
   - Save current settings as named presets
   - Quick switch between configurations
   - Share presets with others

2. **History of Edits**
   - See previous system prompts
   - Revert to earlier settings
   - Compare versions

3. **Settings Export**
   - Download all settings as JSON
   - Backup before changes
   - Migrate between machines

4. **Advanced Memory Controls**
   - Set memory retention period
   - Enable/disable specific memory categories
   - Manual memory pruning

5. **Custom Sliders**
   - Add more inference parameters
   - Frequency penalty, presence penalty
   - Model-specific options

6. **Settings Sync**
   - Cloud sync of settings
   - Multi-device consistency
   - Team collaboration

## Troubleshooting

### Settings Not Saving
- Check browser console for errors (F12)
- Verify backend API is running (`/api/system-settings`)
- Check network tab for failed requests
- Ensure profile/persona endpoints working

### Sliders Not Responsive
- Refresh page to reload slider values
- Check browser supports HTML5 range input
- Verify JavaScript enabled

### Memory Not Showing
- Click "Add" button after entering fact
- Check memories list scrolls (max-height: 60)
- Verify /api/memories endpoint accessible

### System Prompt Too Long
- Editor supports large prompts (no limit)
- But model has token limit (consider max_tokens)
- Split into Base Prompt + Instructions

## Code Examples

### Add Custom System Prompt
```javascript
// In Index.html System tab:
systemPromptInput.value = `You are my personal coding assistant...`
// Click Save System Settings
```

### Add Memory Fact
```javascript
// In Index.html Memory tab:
// Type: "I'm a systems engineer"
// Click Add
```

### Adjust Temperature
```javascript
// In Index.html Advanced tab:
// Drag Temperature slider to 1.5
// Click Save Advanced Settings
```

## API Documentation

### System Settings
```
GET /api/system-settings
Response:
{
  "system_prompt": "You are...",
  "custom_instructions": "...",
  "name": "Owlynn",
  "tone": "friendly"
}

POST /api/system-settings
Body:
{
  "system_prompt": "New prompt",
  "custom_instructions": "...",
  "name": "NewName",
  "tone": "professional"
}
Response: {"status": "ok", "message": "..."}
```

### Memory Settings
```
GET /api/memory-settings
Response:
{
  "short_term_enabled": true,
  "long_term_enabled": true
}

POST /api/memory-settings
Body:
{
  "short_term_enabled": false,
  "long_term_enabled": true
}
Response: {"status": "ok", "message": "..."}
```

### Advanced Settings
```
GET /api/advanced-settings
Response:
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 2048,
  "top_k": 40,
  "streaming_enabled": true,
  "show_thinking": false,
  "show_tool_execution": true
}

POST /api/advanced-settings
Body:
{
  "temperature": 0.9,
  "top_p": 0.85,
  "max_tokens": 4096,
  ...
}
Response: {"status": "ok", "message": "..."}
```

## Testing Checklist

- [ ] Settings modal opens from sidebar
- [ ] Tab switching works smoothly
- [ ] Sliders move and show values
- [ ] Toggles switch on/off
- [ ] Add memory fact works
- [ ] Delete memory works
- [ ] System prompt saves
- [ ] Settings load on reopen modal
- [ ] No console errors
- [ ] Mobile responsive layout
- [ ] Keyboard accessible
- [ ] Escape key closes modal

## Files Modified

1. **frontend/index.html**
   - Added settings tabs structure
   - Added new form fields and controls
   - Added CSS for tabs and sliders

2. **frontend/script.js**
   - Tab switching logic
   - Event listeners for controls
   - Load/save settings functions
   - Update display values

3. **src/api/server.py**
   - New /api/system-settings endpoints
   - New /api/memory-settings endpoints
   - New /api/advanced-settings endpoints

## Deployment Notes

1. Update frontend files (index.html, script.js)
2. Update backend API (server.py)
3. Restart Flask/FastAPI server
4. Clear browser cache if needed
5. Verify endpoints accessible
6. Test settings persistence

---

**Version**: 1.0  
**Last Updated**: 2026-03-20  
**Compatibility**: Works with existing profiles and settings
