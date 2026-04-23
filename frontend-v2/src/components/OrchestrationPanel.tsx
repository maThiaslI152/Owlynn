import { useAppStore } from '../state/useAppStore'

export function OrchestrationPanel() {
  const routerMetadata = useAppStore((s) => s.routerMetadata)
  const modelInfo = useAppStore((s) => s.modelInfo)
  const contextCompression = useAppStore((s) => s.contextCompression)
  const memoryUpdatedAt = useAppStore((s) => s.memoryUpdatedAt)

  const route = routerMetadata?.route as string | undefined
  const confidence = routerMetadata?.confidence as number | undefined
  const classificationSource = routerMetadata?.classification_source as string | undefined

  return (
    <section>
      <h3>Orchestration</h3>

      {modelInfo && (
        <div className="orchestration-row">
          <span className="orchestration-label">Model</span>
          <span className="orchestration-value">
            <span className={`model-badge ${modelInfo.includes('cloud') ? 'model-cloud' : 'model-local'}`}>
              {modelInfo}
            </span>
          </span>
        </div>
      )}

      {route && (
        <div className="orchestration-row">
          <span className="orchestration-label">Route</span>
          <span className="orchestration-value">
            <span className={`route-badge route-${route.replace('complex-', '')}`}>
              {route}
            </span>
          </span>
        </div>
      )}

      {confidence !== undefined && (
        <div className="orchestration-row">
          <span className="orchestration-label">Confidence</span>
          <span className="orchestration-value">
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {classificationSource && (
        <div className="orchestration-row">
          <span className="orchestration-label">Source</span>
          <span className="orchestration-value">{classificationSource}</span>
        </div>
      )}

      {contextCompression && (
        <div className="orchestration-compression">
          <span className="orchestration-label">Compressed</span>
          <p className="compression-detail">
            {contextCompression.messagesCompressed} messages, freed ~{contextCompression.tokensFreed} tokens
          </p>
        </div>
      )}

      {memoryUpdatedAt && (
        <div className="orchestration-row">
          <span className="orchestration-label">Memory</span>
          <span className="orchestration-value orchestration-memory-ok">saved</span>
        </div>
      )}

      {!modelInfo && !route && !contextCompression && !memoryUpdatedAt && (
        <p className="orchestration-empty">No routing information yet.</p>
      )}
    </section>
  )
}
