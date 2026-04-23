import type { ActionProposal, ToolExecutionSnapshot } from './state/useAppStore'
import type { SecurityApprovalClientEvent, ToolExecutionEvent } from './types/protocol'

export function deriveRiskHint(toolName?: string, input?: string | null): string {
  const hay = `${toolName ?? ''} ${input ?? ''}`.toLowerCase()
  if (hay.includes('delete') || hay.includes('rm ') || hay.includes('drop ')) return 'destructive-action risk'
  if (hay.includes('sudo') || hay.includes('chmod') || hay.includes('chown')) return 'privilege escalation risk'
  if (hay.includes('curl') || hay.includes('wget') || hay.includes('http')) return 'network exfiltration risk'
  return 'manual approval required'
}

export function toToolExecutionSnapshot(
  event: ToolExecutionEvent,
  now: number
): ToolExecutionSnapshot {
  return {
    toolName: event.tool_name,
    ts: now,
    input: event.input ?? null,
    toolCallId: event.tool_call_id ?? null,
    status: event.status,
    duration: event.duration,
    riskLabel: event.risk_label,
    riskConfidence: event.risk_confidence,
    riskRationale: event.risk_rationale,
    remediationHint: event.remediation_hint,
  }
}

type InterruptMetadata = {
  backendToolName: string
  backendToolArgs: string | null
  backendRiskLabel: string
  backendRiskConfidence: number | null
  backendRiskRationale: string
  backendRemediationHint: string
  primaryInterrupt: unknown
}

function getInterruptMetadata(interrupts: unknown[] | undefined): InterruptMetadata {
  const primaryInterrupt = interrupts?.[0]
  const backendToolName =
    typeof primaryInterrupt === 'object' && primaryInterrupt !== null && 'tool_name' in primaryInterrupt
      ? String((primaryInterrupt as { tool_name?: string }).tool_name ?? '')
      : ''
  const backendToolArgs =
    typeof primaryInterrupt === 'object' && primaryInterrupt !== null && 'tool_args' in primaryInterrupt
      ? ((primaryInterrupt as { tool_args?: string | null }).tool_args ?? null)
      : null
  const backendRiskLabel =
    typeof primaryInterrupt === 'object' && primaryInterrupt !== null && 'risk_label' in primaryInterrupt
      ? String((primaryInterrupt as { risk_label?: string }).risk_label ?? '')
      : ''
  const backendRiskConfidence =
    typeof primaryInterrupt === 'object' &&
    primaryInterrupt !== null &&
    'risk_confidence' in primaryInterrupt &&
    typeof (primaryInterrupt as { risk_confidence?: number }).risk_confidence === 'number'
      ? ((primaryInterrupt as { risk_confidence?: number }).risk_confidence ?? null)
      : null
  const backendRiskRationale =
    typeof primaryInterrupt === 'object' && primaryInterrupt !== null && 'risk_rationale' in primaryInterrupt
      ? String((primaryInterrupt as { risk_rationale?: string }).risk_rationale ?? '')
      : ''
  const backendRemediationHint =
    typeof primaryInterrupt === 'object' && primaryInterrupt !== null && 'remediation_hint' in primaryInterrupt
      ? String((primaryInterrupt as { remediation_hint?: string }).remediation_hint ?? '')
      : ''

  return {
    backendToolName,
    backendToolArgs,
    backendRiskLabel,
    backendRiskConfidence,
    backendRiskRationale,
    backendRemediationHint,
    primaryInterrupt,
  }
}

export function buildInterruptProposal(
  interrupts: unknown[] | undefined,
  latestToolExecution: ToolExecutionSnapshot | null,
  now: number
): ActionProposal {
  const meta = getInterruptMetadata(interrupts)
  const backendRiskConfidencePct =
    typeof meta.backendRiskConfidence === 'number' ? Math.round(meta.backendRiskConfidence * 100) : null
  const proposalId = `interrupt-${now}`

  return {
    id: proposalId,
    summary: meta.backendToolName
      ? `Approve ${meta.backendToolName} execution`
      : latestToolExecution
        ? `Approve ${latestToolExecution.toolName} execution`
        : 'Security approval required before executing sensitive action',
    source: 'system',
    created_at: now,
    status: 'pending',
    backendInterrupt: meta.primaryInterrupt,
    toolContext: meta.backendToolName
      ? {
          toolName: meta.backendToolName,
          ts: now,
          input: meta.backendToolArgs,
          status: 'running',
        }
      : (latestToolExecution ?? undefined),
    riskHint: meta.backendRiskLabel
      ? `${meta.backendRiskLabel}${backendRiskConfidencePct !== null ? ` (${backendRiskConfidencePct}%)` : ''}`
      : deriveRiskHint(latestToolExecution?.toolName, latestToolExecution?.input),
    riskRationale: meta.backendRiskRationale || undefined,
    remediationHint: meta.backendRemediationHint || undefined,
  }
}

export function buildAutoApproveInterruptResponse(): {
  clientEvent: SecurityApprovalClientEvent
  operatorNote: string
} {
  return {
    clientEvent: { type: 'security_approval', approved: true },
    operatorNote: 'Auto-approved interrupt (no HITL mode).',
  }
}

export function resolveProjectSwitch(params: {
  activeProjectId: string
  currentThreadId: string
  targetProjectId: string
  projectThreads: Record<string, string>
  makeThreadId: () => string
}):
  | null
  | {
      nextActiveProjectId: string
      nextCurrentThreadId: string
      nextProjectThreads: Record<string, string>
      operatorNote: string
    } {
  const { activeProjectId, currentThreadId, targetProjectId, projectThreads, makeThreadId } = params
  if (targetProjectId === activeProjectId) return null

  const nextProjectThreads = { ...projectThreads, [activeProjectId]: currentThreadId }
  const nextThreadId = nextProjectThreads[targetProjectId] ?? makeThreadId()
  nextProjectThreads[targetProjectId] = nextThreadId

  return {
    nextActiveProjectId: targetProjectId,
    nextCurrentThreadId: nextThreadId,
    nextProjectThreads,
    operatorNote: `Switched to project ${targetProjectId}`,
  }
}
