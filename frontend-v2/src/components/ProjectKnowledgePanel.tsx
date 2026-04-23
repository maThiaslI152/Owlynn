import { useState, useEffect, useCallback } from 'react'

interface KnowledgeFile {
  name: string
  type: string
  added_at: number
}

interface ProjectKnowledgePanelProps {
  activeProjectId: string
}

export function ProjectKnowledgePanel({ activeProjectId }: ProjectKnowledgePanelProps) {
  const [files, setFiles] = useState<KnowledgeFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadKnowledgeFiles = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(activeProjectId)}`)
      if (!response.ok) {
        setError('Failed to load project details')
        setFiles([])
        return
      }
      const project = await response.json()
      const knowledgeFiles: KnowledgeFile[] = (project.files ?? []).filter(
        (f: KnowledgeFile) => f.type === 'knowledge'
      )
      setFiles(knowledgeFiles)
    } catch {
      setError('Failed to load knowledge files')
      setFiles([])
    } finally {
      setLoading(false)
    }
  }, [activeProjectId])

  useEffect(() => {
    if (activeProjectId) {
      loadKnowledgeFiles()
    }
  }, [activeProjectId, loadKnowledgeFiles])

  return (
    <section className="knowledge-panel">
      <div className="knowledge-panel-header">
        <h3>Knowledge</h3>
        <button
          type="button"
          className="knowledge-refresh"
          onClick={loadKnowledgeFiles}
          disabled={loading}
        >
          {loading ? '...' : 'Refresh'}
        </button>
      </div>
      {error && <p className="knowledge-error">{error}</p>}
      {!loading && !error && files.length === 0 && (
        <p className="knowledge-empty">No knowledge files indexed for this project.</p>
      )}
      {files.length > 0 && (
        <ul className="knowledge-list">
          {files.map((file) => (
            <li key={file.name} className="knowledge-item">
              <span className="knowledge-filename" title={file.name}>
                {file.name}
              </span>
              <span className="knowledge-meta">
                {new Date(file.added_at * 1000).toLocaleDateString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
