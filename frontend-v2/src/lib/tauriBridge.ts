type TauriWindow = {
  __TAURI__?: {
    invoke?: <T = unknown>(command: string, args?: Record<string, unknown>) => Promise<T>
    tauri?: {
      convertFileSrc?: (path: string) => string
    }
  }
}

interface BridgeResult<T = string> {
  ok: boolean
  data?: T
  error?: string
}

function getInvoke() {
  const maybeWindow = window as unknown as TauriWindow
  return maybeWindow.__TAURI__?.invoke
}

async function invokeOrResult<T>(command: string, args?: Record<string, unknown>): Promise<BridgeResult<T>> {
  const invoke = getInvoke()
  if (!invoke) {
    return { ok: false, error: 'Tauri invoke bridge unavailable' }
  }
  try {
    const data = await invoke<T>(command, args)
    return { ok: true, data }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { ok: false, error: message }
  }
}

export const tauriBridge = {
  startPushToTalk: () => invokeOrResult<string>('start_push_to_talk', {}),
  stopPushToTalk: () => invokeOrResult<string>('stop_push_to_talk', {}),
  hardStopVoice: () => invokeOrResult<string>('hard_stop_voice', {}),
  setSafeMode: (mode: string) => invokeOrResult<string>('set_safe_mode', { mode }),
  startScreenPreview: (source: string) =>
    invokeOrResult<string>('start_screen_preview', { source }),
  stopScreenPreview: () => invokeOrResult<string>('stop_screen_preview', {}),
  createActionProposal: (summary: string) =>
    invokeOrResult<{
      id: string
      summary: string
      source: 'screen_assist' | 'voice' | 'system'
      created_at: number
      status: 'pending' | 'approved' | 'rejected'
    }>('create_action_proposal', { summary }),
  approveActionProposal: (id: string) =>
    invokeOrResult<string>('approve_action_proposal', { id }),
  rejectActionProposal: (id: string) =>
    invokeOrResult<string>('reject_action_proposal', { id }),
  convertFileSrc: (path: string) => {
    const maybeWindow = window as unknown as TauriWindow
    const convert = maybeWindow.__TAURI__?.tauri?.convertFileSrc
    if (!convert) return ''
    try {
      return convert(path)
    } catch {
      return ''
    }
  },
}
