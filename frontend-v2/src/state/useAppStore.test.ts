import { beforeEach, describe, expect, it } from 'vitest'
import { useAppStore } from './useAppStore'

describe('useAppStore regressions', () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true)
  })

  it('upserts action proposals and updates status deterministically', () => {
    const proposal = {
      id: 'proposal-1',
      summary: 'Approve tool call',
      source: 'system' as const,
      created_at: Date.now(),
      status: 'pending' as const,
    }

    useAppStore.getState().upsertActionProposal(proposal)
    expect(useAppStore.getState().actionProposals).toHaveLength(1)
    expect(useAppStore.getState().actionProposals[0].status).toBe('pending')

    useAppStore.getState().updateActionProposalStatus('proposal-1', 'approved')
    expect(useAppStore.getState().actionProposals[0].status).toBe('approved')
  })

  it('deduplicates tool execution history by toolCallId and keeps latest snapshot', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'read_workspace_file',
      ts: 1,
      toolCallId: 'call-1',
      status: 'running',
    })
    useAppStore.getState().pushToolExecution({
      toolName: 'read_workspace_file',
      ts: 2,
      toolCallId: 'call-1',
      status: 'success',
      duration: 25,
    })

    const { toolExecutionHistory, latestToolExecution } = useAppStore.getState()
    expect(toolExecutionHistory).toHaveLength(1)
    expect(toolExecutionHistory[0].status).toBe('success')
    expect(latestToolExecution?.toolCallId).toBe('call-1')
    expect(latestToolExecution?.status).toBe('success')
  })

  it('caps tool execution history at 25 entries', () => {
    for (let idx = 0; idx < 30; idx += 1) {
      useAppStore.getState().pushToolExecution({
        toolName: `tool-${idx}`,
        ts: idx,
        toolCallId: `call-${idx}`,
        status: 'running',
      })
    }

    const { toolExecutionHistory } = useAppStore.getState()
    expect(toolExecutionHistory).toHaveLength(25)
    expect(toolExecutionHistory[0].toolCallId).toBe('call-29')
    expect(toolExecutionHistory[24].toolCallId).toBe('call-5')
  })

  it('updates screen assist fields without clobbering sibling state', () => {
    useAppStore.getState().setScreenAssistMode('preview')
    useAppStore.getState().setScreenAssistSource('window')
    useAppStore.getState().setScreenAssistPreviewPath('/tmp/preview.png')

    const { screenAssist } = useAppStore.getState()
    expect(screenAssist.mode).toBe('preview')
    expect(screenAssist.source).toBe('window')
    expect(screenAssist.previewPath).toBe('/tmp/preview.png')
  })
})
