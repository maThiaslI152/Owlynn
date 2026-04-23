import { tauriBridge as defaultBridge } from '../lib/tauriBridge'
import { useAppStore } from '../state/useAppStore'

interface ActionProposalQueueProps {
  onApprove?: (id: string) => Promise<void>
  onReject?: (id: string) => Promise<void>
  bridge?: {
    approveActionProposal: (id: string) => Promise<{ ok: boolean; error?: string }>
    rejectActionProposal: (id: string) => Promise<{ ok: boolean; error?: string }>
  }
}

export function ActionProposalQueue({ onApprove, onReject, bridge }: ActionProposalQueueProps) {
  const proposals = useAppStore((s) => s.actionProposals)
  const updateStatus = useAppStore((s) => s.updateActionProposalStatus)
  const setOperatorNote = useAppStore((s) => s.setOperatorNote)
  const activeBridge = bridge ?? defaultBridge

  const approve = async (id: string) => {
    if (onApprove) {
      await onApprove(id)
      updateStatus(id, 'approved')
      return
    }
    const result = await activeBridge.approveActionProposal(id)
    if (!result.ok) {
      setOperatorNote(`Proposal error: ${result.error}`)
      return
    }
    updateStatus(id, 'approved')
    setOperatorNote(`Proposal ${id} approved`)
  }

  const reject = async (id: string) => {
    if (onReject) {
      await onReject(id)
      updateStatus(id, 'rejected')
      return
    }
    const result = await activeBridge.rejectActionProposal(id)
    if (!result.ok) {
      setOperatorNote(`Proposal error: ${result.error}`)
      return
    }
    updateStatus(id, 'rejected')
    setOperatorNote(`Proposal ${id} rejected`)
  }

  return (
    <section className="proposal-queue">
      <h3>Action Proposals</h3>
      {proposals.length === 0 ? (
        <p className="meta">No pending proposals.</p>
      ) : (
        <div className="proposal-list">
          {proposals.map((proposal) => (
            <article key={proposal.id} className="proposal-item">
              <p>
                <strong>{proposal.summary}</strong>
              </p>
              <p className="meta">
                {proposal.source} · {proposal.status}
              </p>
              {proposal.toolContext ? (
                <>
                  <p className="meta">Tool: {proposal.toolContext.toolName}</p>
                  {proposal.toolContext.input ? (
                    <p className="meta">Input: {proposal.toolContext.input.slice(0, 160)}</p>
                  ) : null}
                </>
              ) : null}
              {proposal.riskHint ? <p className="meta">Risk: {proposal.riskHint}</p> : null}
              {proposal.riskRationale ? (
                <p className="meta">Rationale: {proposal.riskRationale}</p>
              ) : null}
              {proposal.remediationHint ? (
                <p className="meta">Mitigation: {proposal.remediationHint}</p>
              ) : null}
              {proposal.status === 'pending' ? (
                <div className="row">
                  <button type="button" onClick={() => approve(proposal.id)}>
                    Approve
                  </button>
                  <button type="button" onClick={() => reject(proposal.id)}>
                    Reject
                  </button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
