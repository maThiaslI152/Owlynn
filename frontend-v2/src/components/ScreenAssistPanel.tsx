import { useAppStore } from '../state/useAppStore'
import { tauriBridge as defaultBridge } from '../lib/tauriBridge'

interface ScreenAssistPanelProps {
  bridge?: {
    startScreenPreview: (source: string) => Promise<{ ok: boolean; error?: string; data?: string }>
    stopScreenPreview: () => Promise<{ ok: boolean; error?: string; data?: string }>
    convertFileSrc: (path: string) => string
  }
}

export function ScreenAssistPanel({ bridge }: ScreenAssistPanelProps) {
  const screenAssist = useAppStore((s) => s.screenAssist)
  const setMode = useAppStore((s) => s.setScreenAssistMode)
  const setSource = useAppStore((s) => s.setScreenAssistSource)
  const setOperatorNote = useAppStore((s) => s.setOperatorNote)
  const activeBridge = bridge ?? defaultBridge
  const previewSrc = screenAssist.previewPath ? activeBridge.convertFileSrc(screenAssist.previewPath) : ''

  const startPreview = async () => {
    const result = await activeBridge.startScreenPreview(screenAssist.source)
    if (!result.ok) {
      setOperatorNote(`Screen Assist error: ${result.error}`)
      return
    }
    setMode('preview')
    setOperatorNote(`Screen Assist: ${result.data ?? 'preview requested'}`)
  }

  const startAnnotating = async () => {
    const result = await activeBridge.startScreenPreview(screenAssist.source)
    if (!result.ok) {
      setOperatorNote(`Screen Assist error: ${result.error}`)
      return
    }
    setMode('annotating')
    setOperatorNote(`Screen Assist: ${result.data ?? 'annotate requested'}`)
  }

  const stopPreview = async () => {
    const result = await activeBridge.stopScreenPreview()
    if (!result.ok) {
      setOperatorNote(`Screen Assist error: ${result.error}`)
      return
    }
    setMode('off')
    setOperatorNote(`Screen Assist: ${result.data ?? 'stop requested'}`)
  }

  return (
    <section className="screen-assist">
      <h3>Screen Assist</h3>
      <label>
        Source
        <select value={screenAssist.source} onChange={(e) => setSource(e.target.value as 'screen' | 'window' | 'region')}>
          <option value="screen">Screen</option>
          <option value="window">Window</option>
          <option value="region">Region</option>
        </select>
      </label>
      <div className="row">
        <button type="button" onClick={startPreview}>
          Start Preview
        </button>
        <button type="button" onClick={startAnnotating}>
          Annotate
        </button>
        <button type="button" onClick={stopPreview}>
          Stop
        </button>
      </div>
      <p className="meta">Mode: {screenAssist.mode}</p>
      {screenAssist.previewPath ? (
        <div className="preview-box">
          <p className="meta">Preview file: {screenAssist.previewPath}</p>
          {previewSrc ? <img src={previewSrc} alt="screen preview" /> : null}
        </div>
      ) : null}
    </section>
  )
}
