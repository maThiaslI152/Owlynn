import { Composer } from './Composer'
import { LiveTalkControls } from './LiveTalkControls'
import { SafeModePanel } from './SafeModePanel'
import { ScreenAssistPanel } from './ScreenAssistPanel'
import { ActionProposalQueue } from './ActionProposalQueue'
import { ToolExecutionPanel } from './ToolExecutionPanel'
import { ProjectKnowledgePanel } from './ProjectKnowledgePanel'
import { OrchestrationPanel } from './OrchestrationPanel'
import { useAppStore } from '../state/useAppStore'

interface WorkspaceProject {
  id: string
  name: string
}

interface AppShellProps {
  onSend: (content: string) => void
  projects: WorkspaceProject[]
  activeProjectId: string
  currentThreadId: string
  onSwitchProject: (projectId: string) => void
  onRefreshProjects: () => void
  onApproveProposal?: (id: string) => Promise<void>
  onRejectProposal?: (id: string) => Promise<void>
}

export function AppShell({
  onSend,
  projects,
  activeProjectId,
  currentThreadId,
  onSwitchProject,
  onRefreshProjects,
  onApproveProposal,
  onRejectProposal,
}: AppShellProps) {
  const connectionState = useAppStore((s) => s.connectionState)
  const messages = useAppStore((s) => s.messages)
  const operatorNote = useAppStore((s) => s.operatorNote)

  return (
    <div className="app-shell">
      <aside className="panel left-panel">
        <div className="workspace-header">
          <h2>Workspace</h2>
          <button type="button" className="workspace-refresh" onClick={onRefreshProjects}>
            Refresh
          </button>
        </div>
        <p className="workspace-meta">
          Active project: <strong>{activeProjectId}</strong>
        </p>
        <p className="workspace-meta">
          Thread: <code>{currentThreadId}</code>
        </p>
        <div className="workspace-project-list">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={`workspace-project-item${
                project.id === activeProjectId ? ' workspace-project-item-active' : ''
              }`}
              onClick={() => onSwitchProject(project.id)}
            >
              {project.name}
            </button>
          ))}
        </div>
        <ProjectKnowledgePanel activeProjectId={activeProjectId} />
      </aside>

      <main className="panel center-panel">
        <header className="topbar">
          <h1>Owlynn v2</h1>
          <span className={`status status-${connectionState}`}>{connectionState}</span>
        </header>
        {operatorNote ? <p className="operator-note">{operatorNote}</p> : null}
        <section className="messages">
          {messages.length === 0 ? (
            <p className="empty">No messages yet.</p>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`message message-${message.role}`}>
                <strong>{message.role}</strong>
                <p>{message.content}</p>
              </article>
            ))
          )}
        </section>
        <Composer onSend={onSend} />
      </main>

      <aside className="panel right-panel">
        <h2>Inspector</h2>
        <OrchestrationPanel />
        <SafeModePanel />
        <LiveTalkControls />
        <ScreenAssistPanel />
        <ToolExecutionPanel />
        <ActionProposalQueue onApprove={onApproveProposal} onReject={onRejectProposal} />
      </aside>
    </div>
  )
}
