# LM Studio Setup

## Models to Download

Owlynn uses a Small model (always loaded) plus one Medium-tier model at a time (swappable):

### Small Model (Always Loaded)
- `liquid/lfm2.5-1.2b` — routing, simple answers, chat titles (~730 MB VRAM)

### Medium-Tier Models (One at a Time)
Download all three; the system auto-swaps based on task type:

| Variant | Model Key | Role |
|---------|-----------|------|
| Default | `qwen/qwen3.5-9b` | General complex reasoning, tool calling |
| Vision | `zai-org/glm-4.6v-flash` | Image/multimodal processing |
| Long Context | `LFM2 8B A1B GGUF Q8_0` | Extended context tasks |

### Swap Behavior

- Only **one M-tier model** is loaded at a time alongside the Small model.
- The system automatically swaps models based on the task (e.g., image input triggers a swap to the Vision model).
- Swaps use the LM Studio native API (`POST /api/v1/models/load` / `POST /api/v1/models/unload`).
- The router prefers the currently-loaded variant when the task is borderline, avoiding unnecessary swap latency.
- Swap timeout: 120 seconds. Poll interval: 2 seconds.

## Jinja Template Issues — `No user query found in messages`

LM Studio applies the model's **Jinja chat template** to the `/v1/chat/completions` payload. Some **Qwen 3.x** templates expect a normal **user** role in the message list. Owlynn mitigates this in two ways:

1. **Router** uses a `HumanMessage` (not system-only) for routing.
2. **`lm_studio_fold_system`** (default **on** in profile defaults): system instructions are **prepended into the first user message** so the API sees a clear user turn. Disable in `data/user_profile.json` if your backend requires a separate system role:

   ```json
   "lm_studio_fold_system": false
   ```

## If errors persist

- Update **LM Studio** to the latest build.
- Prefer **`lmstudio-community`** GGUF variants when available.
- In **My Models → model settings → Prompt Template**, try a fixed template or one from community presets.
