import { useAppStore, type ExecutionPolicy, type SafeModeLevel } from '../state/useAppStore'
import { tauriBridge } from '../lib/tauriBridge'

const SAFE_MODES: SafeModeLevel[] = ['normal', 'safe_readonly', 'safe_confirmed_exec', 'safe_isolated']

export function SafeModePanel() {
  const safeMode = useAppStore((s) => s.safeMode)
  const executionPolicy = useAppStore((s) => s.executionPolicy)
  const setSafeMode = useAppStore((s) => s.setSafeMode)
  const setExecutionPolicy = useAppStore((s) => s.setExecutionPolicy)
  const setOperatorNote = useAppStore((s) => s.setOperatorNote)

  const onModeChange = async (mode: SafeModeLevel) => {
    const result = await tauriBridge.setSafeMode(mode)
    if (!result.ok) {
      setOperatorNote(`Safe Mode error: ${result.error}`)
      return
    }
    setSafeMode(mode)
    setOperatorNote(`Safe Mode: ${result.data ?? `mode set to ${mode}`}`)
  }

  const onPolicyChange = (policy: ExecutionPolicy) => {
    void (async () => {
      try {
        const response = await fetch('/api/advanced-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ execution_policy: policy }),
        })
        if (!response.ok) {
          setOperatorNote(`Execution policy error: request failed (${response.status})`)
          return
        }
        const payload = (await response.json()) as { status?: string; message?: string }
        if (payload.status === 'error') {
          setOperatorNote(`Execution policy error: ${payload.message ?? 'unknown error'}`)
          return
        }
        setExecutionPolicy(policy)
        setOperatorNote(
          policy === 'auto_approve'
            ? 'Execution policy: auto-approve (no HITL)'
            : 'Execution policy: manual HITL approval'
        )
      } catch (error) {
        setOperatorNote(`Execution policy error: ${(error as Error).message}`)
      }
    })()
  }

  return (
    <section className="safe-mode">
      <h3>Safe Mode</h3>
      <label>
        Active mode
        <select value={safeMode} onChange={(e) => onModeChange(e.target.value as SafeModeLevel)}>
          {SAFE_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>
      <label>
        Execution policy
        <select
          value={executionPolicy}
          onChange={(e) => onPolicyChange(e.target.value as ExecutionPolicy)}
        >
          <option value="auto_approve">auto_approve (no HITL)</option>
          <option value="hitl">hitl (manual approval)</option>
        </select>
      </label>
    </section>
  )
}
