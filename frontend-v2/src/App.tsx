import { useEffect, useRef, useState } from 'react'
import { AppShell } from './components/AppShell'
import { WsClient } from './lib/wsClient'
import { useAppStore } from './state/useAppStore'
import {
  buildAutoApproveInterruptResponse,
  buildInterruptProposal,
  resolveProjectSwitch,
  toToolExecutionSnapshot,
} from './appEventHandlers'
import type { ChatMessage, ServerEvent } from './types/protocol'

interface ProjectSummary {
  id: string
  name: string
}

type TauriEventWindow = {
  __TAURI__?: {
    event?: {
      listen?: (
        event: string,
        handler: (payload: { payload: ServerEvent }) => void
      ) => Promise<() => void>
    }
  }
}

function App() {
  const wsBaseUrl = import.meta.env.VITE_WS_BASE_URL ?? 'ws://127.0.0.1:8000/ws/chat'
  const setConnection = useAppStore((s) => s.setConnectionState)
  const addMessage = useAppStore((s) => s.addMessage)
  const setVoiceState = useAppStore((s) => s.setVoiceState)
  const setSafeMode = useAppStore((s) => s.setSafeMode)
  const setExecutionPolicy = useAppStore((s) => s.setExecutionPolicy)
  const setScreenAssistMode = useAppStore((s) => s.setScreenAssistMode)
  const setScreenAssistSource = useAppStore((s) => s.setScreenAssistSource)
  const setScreenAssistPreviewPath = useAppStore((s) => s.setScreenAssistPreviewPath)
  const upsertActionProposal = useAppStore((s) => s.upsertActionProposal)
  const updateActionProposalStatus = useAppStore((s) => s.updateActionProposalStatus)
  const executionPolicy = useAppStore((s) => s.executionPolicy)
  const latestToolExecution = useAppStore((s) => s.latestToolExecution)
  const setLatestToolExecution = useAppStore((s) => s.setLatestToolExecution)
  const pushToolExecution = useAppStore((s) => s.pushToolExecution)
  const setOperatorNote = useAppStore((s) => s.setOperatorNote)
  const setRouterMetadata = useAppStore((s) => s.setRouterMetadata)
  const setModelInfo = useAppStore((s) => s.setModelInfo)
  const setContextCompression = useAppStore((s) => s.setContextCompression)
  const setMemoryUpdatedAt = useAppStore((s) => s.setMemoryUpdatedAt)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [activeProjectId, setActiveProjectId] = useState('default')
  const [currentThreadId, setCurrentThreadId] = useState('default')
  const projectThreadsRef = useRef<Record<string, string>>({ default: 'default' })
  const wsClientRef = useRef<WsClient | null>(null)

  const makeThreadId = () => `thread-${crypto.randomUUID()}`

  const loadProjects = async () => {
    try {
      const response = await fetch('/api/projects')
      if (!response.ok) return
      const payload = (await response.json()) as Array<{ id: string; name?: string }>
      const mapped = payload.map((project) => ({
        id: project.id,
        name: project.name ?? project.id,
      }))
      if (mapped.length === 0) {
        setProjects([{ id: 'default', name: 'General Workspace' }])
        return
      }
      setProjects(mapped)
      const activeExists = mapped.some((project) => project.id === activeProjectId)
      if (!activeExists) {
        const first = mapped[0]
        const existingThread = projectThreadsRef.current[first.id] ?? makeThreadId()
        projectThreadsRef.current[first.id] = existingThread
        setActiveProjectId(first.id)
        setCurrentThreadId(existingThread)
      }
    } catch {
      setProjects([{ id: 'default', name: 'General Workspace' }])
    }
  }

  const handleInterrupt = (interrupts: unknown[] | undefined) => {
    if (executionPolicy === 'auto_approve') {
      const autoApprove = buildAutoApproveInterruptResponse()
      wsClientRef.current?.send(autoApprove.clientEvent)
      setOperatorNote(autoApprove.operatorNote)
      return
    }

    const proposal = buildInterruptProposal(interrupts, latestToolExecution, Date.now())
    upsertActionProposal(proposal)
    setOperatorNote('Approval required: sensitive action waiting for decision.')
  }

  useEffect(() => {
    let disposed = false
    const loadExecutionPolicy = async () => {
      try {
        const response = await fetch('/api/unified-settings')
        if (!response.ok) return
        const payload = (await response.json()) as { execution_policy?: string }
        if (disposed) return
        if (payload.execution_policy === 'hitl' || payload.execution_policy === 'auto_approve') {
          setExecutionPolicy(payload.execution_policy)
        }
      } catch {
        // Keep local default if settings are unavailable.
      }
    }
    void loadExecutionPolicy()
    return () => {
      disposed = true
    }
  }, [setExecutionPolicy])

  useEffect(() => {
    void loadProjects()
  }, [])

  useEffect(() => {
    const wsUrl = `${wsBaseUrl}/${encodeURIComponent(currentThreadId)}`
    const wsClient = new WsClient(wsUrl)
    wsClientRef.current = wsClient
    const disconnect = wsClient.connect({
      onOpen: () => setConnection('connected'),
      onClose: () => setConnection('disconnected'),
      onError: () => setConnection('error'),
      onEvent: (event: ServerEvent) => {
        if (event.type === 'assistant.message') {
          addMessage({
            id: event.id,
            role: 'assistant',
            content: event.content,
            ts: Date.now(),
          })
        } else if (event.type === 'voice.state') {
          setVoiceState(event.state)
        } else if (event.type === 'safe_mode.changed') {
          setSafeMode(event.mode)
        } else if (event.type === 'screen_assist.state') {
          setScreenAssistMode(event.mode)
          setScreenAssistSource(event.source)
          setScreenAssistPreviewPath(event.preview_path ?? null)
        } else if (event.type === 'action.proposal') {
          upsertActionProposal(event.proposal)
        } else if (event.type === 'action.proposal.result') {
          updateActionProposalStatus(event.id, event.status)
        } else if (event.type === 'tool_execution') {
          const snapshot = toToolExecutionSnapshot(event, Date.now())
          setLatestToolExecution(snapshot)
          pushToolExecution(snapshot)
        } else if (event.type === 'interrupt') {
          handleInterrupt(event.interrupts)
        } else if (event.type === 'router_info') {
          setRouterMetadata(event.metadata as Record<string, unknown>)
        } else if (event.type === 'model_info') {
          setModelInfo(event.model as string)
        } else if (event.type === 'context_summarized') {
          setContextCompression({
            summary: event.summary,
            takeaways: event.takeaways,
            messagesCompressed: event.messages_compressed,
            tokensFreed: event.tokens_freed,
          })
        } else if (event.type === 'memory_updated') {
          setMemoryUpdatedAt(Date.now())
        }
      },
    })

    setConnection('connecting')
    return () => {
      disconnect()
      wsClientRef.current = null
    }
  }, [addMessage, currentThreadId, executionPolicy, latestToolExecution, pushToolExecution, setConnection, setLatestToolExecution, setMemoryUpdatedAt, setModelInfo, setContextCompression, setOperatorNote, setRouterMetadata, setSafeMode, setScreenAssistMode, setScreenAssistPreviewPath, setScreenAssistSource, setVoiceState, upsertActionProposal, updateActionProposalStatus, wsBaseUrl])

  useEffect(() => {
    let unlisten: (() => void) | undefined
    const maybeWindow = window as unknown as TauriEventWindow
    const listen = maybeWindow.__TAURI__?.event?.listen
    if (!listen) return

    listen('owlynn://runtime-event', (event) => {
      const payload = event.payload
      if (payload.type === 'voice.state') {
        setVoiceState(payload.state)
      } else if (payload.type === 'safe_mode.changed') {
        setSafeMode(payload.mode)
      } else if (payload.type === 'screen_assist.state') {
        setScreenAssistMode(payload.mode)
        setScreenAssistSource(payload.source)
        setScreenAssistPreviewPath(payload.preview_path ?? null)
      } else if (payload.type === 'action.proposal') {
        upsertActionProposal(payload.proposal)
      } else if (payload.type === 'action.proposal.result') {
        updateActionProposalStatus(payload.id, payload.status)
      } else if (payload.type === 'tool_execution') {
        const snapshot = toToolExecutionSnapshot(payload, Date.now())
        setLatestToolExecution(snapshot)
        pushToolExecution(snapshot)
      } else if (payload.type === 'interrupt') {
        handleInterrupt(payload.interrupts)
      }
    }).then((fn) => {
      unlisten = fn
    })

    return () => {
      if (unlisten) unlisten()
    }
  }, [executionPolicy, latestToolExecution, pushToolExecution, setLatestToolExecution, setOperatorNote, setSafeMode, setScreenAssistMode, setScreenAssistPreviewPath, setScreenAssistSource, setVoiceState, upsertActionProposal, updateActionProposalStatus])

  const handleSend = (content: string) => {
    const message: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      ts: Date.now(),
    }
    addMessage(message)
    wsClientRef.current?.send({
      type: 'user.message',
      id: message.id,
      content: message.content,
      message: message.content,
      project_id: activeProjectId,
    })
  }

  const handleApproveProposal = async (id: string) => {
    wsClientRef.current?.send({
      type: 'security_approval',
      approved: true,
    })
    updateActionProposalStatus(id, 'approved')
    setOperatorNote(`Proposal ${id} approved and sent to backend`)
  }

  const handleRejectProposal = async (id: string) => {
    wsClientRef.current?.send({
      type: 'security_approval',
      approved: false,
    })
    updateActionProposalStatus(id, 'rejected')
    setOperatorNote(`Proposal ${id} rejected and sent to backend`)
  }

  const handleSwitchProject = (projectId: string) => {
    const next = resolveProjectSwitch({
      activeProjectId,
      currentThreadId,
      targetProjectId: projectId,
      projectThreads: projectThreadsRef.current,
      makeThreadId,
    })
    if (!next) return
    projectThreadsRef.current = next.nextProjectThreads
    setActiveProjectId(next.nextActiveProjectId)
    setCurrentThreadId(next.nextCurrentThreadId)
    setOperatorNote(next.operatorNote)
  }

  return (
    <AppShell
      onSend={handleSend}
      projects={projects}
      activeProjectId={activeProjectId}
      currentThreadId={currentThreadId}
      onSwitchProject={handleSwitchProject}
      onRefreshProjects={() => void loadProjects()}
      onApproveProposal={handleApproveProposal}
      onRejectProposal={handleRejectProposal}
    />
  )
}

export default App
