import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useAppStore } from '../../state/useAppStore'
import { ActionProposalQueue } from '../ActionProposalQueue'
import { ScreenAssistPanel } from '../ScreenAssistPanel'

// Note: ToolExecutionPanel is not tested here because it depends heavily on
// browser-only APIs (crypto.subtle, Clipboard API, Blob, URL.createObjectURL)
// that are not available in vitest's node environment and would require
// significant polyfilling beyond the scope of this regression slice.

beforeEach(() => {
  useAppStore.setState(useAppStore.getInitialState(), true)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ActionProposalQueue regression', () => {
  it('renders empty state when no proposals exist', () => {
    render(<ActionProposalQueue />)
    expect(screen.getByText('No pending proposals.')).toBeTruthy()
  })

  it('renders pending proposals with approve/reject buttons', () => {
    useAppStore.getState().upsertActionProposal({
      id: 'p-1',
      summary: 'Approve delete_workspace_file execution',
      source: 'system',
      created_at: 1000,
      status: 'pending',
      riskHint: 'destructive_action (98%)',
      riskRationale: 'delete semantics',
      remediationHint: 'backup first',
    })

    render(<ActionProposalQueue />)

    expect(screen.getByText('Approve delete_workspace_file execution')).toBeTruthy()
    expect(screen.getByText((content) => content.includes('destructive_action'))).toBeTruthy()
    expect(screen.getByText((content) => content.includes('backup first'))).toBeTruthy()
    expect(screen.getByText('Approve')).toBeTruthy()
    expect(screen.getByText('Reject')).toBeTruthy()
  })

  it('shows tool context when available', () => {
    useAppStore.getState().upsertActionProposal({
      id: 'p-2',
      summary: 'Approve custom tool',
      source: 'system',
      created_at: 2000,
      status: 'pending',
      toolContext: {
        toolName: 'read_workspace_file',
        ts: 2000,
        input: '{"path":"README.md"}',
        status: 'running',
      },
    })

    render(<ActionProposalQueue />)
    expect(screen.getByText(/read_workspace_file/)).toBeTruthy()
    expect(screen.getByText(/README/)).toBeTruthy()
  })

  it('hides approve/reject buttons for non-pending proposals', () => {
    useAppStore.getState().upsertActionProposal({
      id: 'p-3',
      summary: 'Approved proposal',
      source: 'system',
      created_at: 3000,
      status: 'approved',
    })

    render(<ActionProposalQueue />)
    expect(screen.getByText('Approved proposal')).toBeTruthy()
    expect(screen.queryByText('Approve')).toBeNull()
    expect(screen.queryByText('Reject')).toBeNull()
  })

  it('calls onApprove when provided instead of bridge', async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined)

    useAppStore.getState().upsertActionProposal({
      id: 'p-4',
      summary: 'Approve with callback',
      source: 'system',
      created_at: 4000,
      status: 'pending',
    })

    render(<ActionProposalQueue onApprove={onApprove} />)

    fireEvent.click(screen.getByText('Approve'))
    expect(onApprove).toHaveBeenCalledWith('p-4')

    // Wait for async and check store updated
    await vi.waitFor(() => {
      const proposal = useAppStore.getState().actionProposals.find((p) => p.id === 'p-4')
      expect(proposal?.status).toBe('approved')
    })
  })

  it('calls onReject when provided instead of bridge', async () => {
    const onReject = vi.fn().mockResolvedValue(undefined)

    useAppStore.getState().upsertActionProposal({
      id: 'p-5',
      summary: 'Reject with callback',
      source: 'system',
      created_at: 5000,
      status: 'pending',
    })

    render(<ActionProposalQueue onReject={onReject} />)

    fireEvent.click(screen.getByText('Reject'))
    expect(onReject).toHaveBeenCalledWith('p-5')

    await vi.waitFor(() => {
      const proposal = useAppStore.getState().actionProposals.find((p) => p.id === 'p-5')
      expect(proposal?.status).toBe('rejected')
    })
  })

  it('uses injected bridge when no onApprove/onReject callbacks', async () => {
    const mockBridge = {
      approveActionProposal: vi.fn().mockResolvedValue({ ok: true }),
      rejectActionProposal: vi.fn().mockResolvedValue({ ok: true }),
    }

    useAppStore.getState().upsertActionProposal({
      id: 'p-6',
      summary: 'Approve via bridge',
      source: 'system',
      created_at: 6000,
      status: 'pending',
    })

    render(<ActionProposalQueue bridge={mockBridge} />)

    fireEvent.click(screen.getByText('Approve'))
    expect(mockBridge.approveActionProposal).toHaveBeenCalledWith('p-6')

    await vi.waitFor(() => {
      expect(useAppStore.getState().operatorNote).toContain('approved')
    })
  })

  it('shows bridge error note on approve failure', async () => {
    const mockBridge = {
      approveActionProposal: vi.fn().mockResolvedValue({ ok: false, error: 'bridge not available' }),
      rejectActionProposal: vi.fn().mockResolvedValue({ ok: true }),
    }

    useAppStore.getState().upsertActionProposal({
      id: 'p-7',
      summary: 'Fail via bridge',
      source: 'system',
      created_at: 7000,
      status: 'pending',
    })

    render(<ActionProposalQueue bridge={mockBridge} />)

    fireEvent.click(screen.getByText('Approve'))

    await vi.waitFor(() => {
      expect(useAppStore.getState().operatorNote).toContain('Proposal error')
    })
  })
})

describe('ScreenAssistPanel regression', () => {
  it('renders default off state', () => {
    render(<ScreenAssistPanel />)
    expect(screen.getByText('Screen Assist')).toBeTruthy()
    expect(screen.getByText((content) => content.includes('Mode:') && content.includes('off'))).toBeTruthy()
    expect(screen.getByText('Start Preview')).toBeTruthy()
    expect(screen.getByText('Annotate')).toBeTruthy()
    expect(screen.getByText('Stop')).toBeTruthy()
  })

  it('updates source select without crashing', () => {
    render(<ScreenAssistPanel />)
    const select = screen.getByLabelText('Source') as HTMLSelectElement
    expect(select.value).toBe('screen')

    fireEvent.change(select, { target: { value: 'window' } })
    expect(useAppStore.getState().screenAssist.source).toBe('window')
    expect(select.value).toBe('window')
  })

  it('shows preview path when set in store', () => {
    useAppStore.getState().setScreenAssistMode('preview')
    useAppStore.getState().setScreenAssistPreviewPath('/tmp/test.png')

    render(<ScreenAssistPanel />)
    expect(screen.getByText(/tmp\/test.png/)).toBeTruthy()
  })

  it('calls startPreview through injected bridge', async () => {
    const mockBridge = {
      startScreenPreview: vi.fn().mockResolvedValue({ ok: true, data: 'preview started' }),
      stopScreenPreview: vi.fn().mockResolvedValue({ ok: true }),
      convertFileSrc: vi.fn((path: string) => `file://${path}`),
    }

    render(<ScreenAssistPanel bridge={mockBridge} />)
    fireEvent.click(screen.getByText('Start Preview'))

    expect(mockBridge.startScreenPreview).toHaveBeenCalledWith('screen')

    await vi.waitFor(() => {
      expect(useAppStore.getState().screenAssist.mode).toBe('preview')
      expect(useAppStore.getState().operatorNote).toContain('preview started')
    })
  })

  it('calls stopPreview through injected bridge', async () => {
    useAppStore.getState().setScreenAssistMode('preview')

    const mockBridge = {
      startScreenPreview: vi.fn().mockResolvedValue({ ok: true }),
      stopScreenPreview: vi.fn().mockResolvedValue({ ok: true, data: 'stopped' }),
      convertFileSrc: vi.fn((path: string) => `file://${path}`),
    }

    render(<ScreenAssistPanel bridge={mockBridge} />)
    fireEvent.click(screen.getByText('Stop'))

    expect(mockBridge.stopScreenPreview).toHaveBeenCalled()

    await vi.waitFor(() => {
      expect(useAppStore.getState().screenAssist.mode).toBe('off')
      expect(useAppStore.getState().operatorNote).toContain('stopped')
    })
  })

  it('shows error note when bridge fails', async () => {
    const mockBridge = {
      startScreenPreview: vi.fn().mockResolvedValue({ ok: false, error: 'Tauri unavailable' }),
      stopScreenPreview: vi.fn().mockResolvedValue({ ok: true }),
      convertFileSrc: vi.fn((path: string) => `file://${path}`),
    }

    render(<ScreenAssistPanel bridge={mockBridge} />)
    fireEvent.click(screen.getByText('Start Preview'))

    await vi.waitFor(() => {
      expect(useAppStore.getState().operatorNote).toContain('Tauri unavailable')
    })

    // State should not have changed on failure
    expect(useAppStore.getState().screenAssist.mode).toBe('off')
  })
})
