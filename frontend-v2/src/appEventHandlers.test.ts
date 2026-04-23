import { describe, expect, it } from 'vitest'
import {
  buildAutoApproveInterruptResponse,
  buildInterruptProposal,
  resolveProjectSwitch,
  toToolExecutionSnapshot,
} from './appEventHandlers'

describe('app event wiring helpers', () => {
  it('maps tool_execution payload into store snapshot', () => {
    const snapshot = toToolExecutionSnapshot(
      {
        type: 'tool_execution',
        status: 'running',
        tool_name: 'read_workspace_file',
        tool_call_id: 'call-1',
        input: '{"path":"README.md"}',
        risk_label: 'destructive_action',
        risk_confidence: 0.91,
        risk_rationale: 'policy check',
        remediation_hint: 'confirm target',
        duration: 12,
      },
      12345
    )

    expect(snapshot).toMatchObject({
      toolName: 'read_workspace_file',
      ts: 12345,
      toolCallId: 'call-1',
      status: 'running',
      riskLabel: 'destructive_action',
      riskConfidence: 0.91,
    })
  })

  it('builds interrupt proposal with backend risk metadata', () => {
    const proposal = buildInterruptProposal(
      [
        {
          tool_name: 'delete_workspace_file',
          tool_args: '{"filename":"danger.txt"}',
          risk_label: 'destructive_action',
          risk_confidence: 0.98,
          risk_rationale: 'delete semantics',
          remediation_hint: 'backup first',
        },
      ],
      null,
      777
    )

    expect(proposal.id).toBe('interrupt-777')
    expect(proposal.summary).toBe('Approve delete_workspace_file execution')
    expect(proposal.riskHint).toBe('destructive_action (98%)')
    expect(proposal.riskRationale).toBe('delete semantics')
    expect(proposal.remediationHint).toBe('backup first')
  })

  it('creates auto-approve interrupt response payload', () => {
    const result = buildAutoApproveInterruptResponse()
    expect(result.clientEvent).toEqual({ type: 'security_approval', approved: true })
    expect(result.operatorNote).toContain('Auto-approved interrupt')
  })

  it('resolves project/thread switching deterministically', () => {
    const resolved = resolveProjectSwitch({
      activeProjectId: 'proj-a',
      currentThreadId: 'thread-a',
      targetProjectId: 'proj-b',
      projectThreads: { 'proj-a': 'thread-a', 'proj-b': 'thread-b' },
      makeThreadId: () => 'thread-new',
    })

    expect(resolved).not.toBeNull()
    expect(resolved?.nextActiveProjectId).toBe('proj-b')
    expect(resolved?.nextCurrentThreadId).toBe('thread-b')
    expect(resolved?.nextProjectThreads['proj-a']).toBe('thread-a')
  })
})
