import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useAppStore } from '../../state/useAppStore'
import { Composer } from '../Composer'
import { OrchestrationPanel } from '../OrchestrationPanel'
import { SafeModePanel } from '../SafeModePanel'
import { LiveTalkControls } from '../LiveTalkControls'
import { ProjectKnowledgePanel } from '../ProjectKnowledgePanel'
import { AppShell } from '../AppShell'

beforeEach(() => {
  useAppStore.setState(useAppStore.getInitialState(), true)
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── Composer ─────────────────────────────────────────────────────────────

describe('Composer', () => {
  it('renders textarea and send button', () => {
    render(<Composer onSend={() => {}} />)
    expect(screen.getByPlaceholderText('Ask Owlynn...')).toBeTruthy()
    expect(screen.getByText('Send')).toBeTruthy()
  })

  it('calls onSend with trimmed content on submit', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)

    const textarea = screen.getByPlaceholderText('Ask Owlynn...')
    fireEvent.change(textarea, { target: { value: '  Hello world  ' } })
    fireEvent.click(screen.getByText('Send'))

    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('does not call onSend for empty input', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)

    fireEvent.click(screen.getByText('Send'))
    expect(onSend).not.toHaveBeenCalled()
  })

  it('clears input after send', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)

    const textarea = screen.getByPlaceholderText('Ask Owlynn...')
    fireEvent.change(textarea, { target: { value: 'Hello' } })
    fireEvent.click(screen.getByText('Send'))

    expect((textarea as HTMLTextAreaElement).value).toBe('')
  })

  it('submits on Enter key via form submit', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)

    const textarea = screen.getByPlaceholderText('Ask Owlynn...')
    fireEvent.change(textarea, { target: { value: 'Hello' } })
    fireEvent.submit(textarea.closest('form')!)

    expect(onSend).toHaveBeenCalledWith('Hello')
  })
})

// ── OrchestrationPanel ──────────────────────────────────────────────────

describe('OrchestrationPanel', () => {
  it('renders with heading', () => {
    render(<OrchestrationPanel />)
    expect(screen.getByText('Orchestration')).toBeTruthy()
  })

  it('displays model badge when modelInfo is set', () => {
    useAppStore.getState().setModelInfo('local-llm-v1')
    render(<OrchestrationPanel />)
    expect(screen.getByText('local-llm-v1')).toBeTruthy()
  })

  it('displays route badge when routerMetadata has route', () => {
    useAppStore.getState().setRouterMetadata({
      route: 'complex-default',
      confidence: 0.95,
      classification_source: 'llm',
    })
    render(<OrchestrationPanel />)
    expect(screen.getByText(/complex-default/)).toBeTruthy()
  })

  it('displays confidence percentage', () => {
    useAppStore.getState().setRouterMetadata({
      route: 'simple',
      confidence: 0.87,
      classification_source: 'keyword_bypass',
    })
    render(<OrchestrationPanel />)
    expect(screen.getByText(/87%/)).toBeTruthy()
  })

  it('shows model badge with cloud class for cloud models', () => {
    useAppStore.getState().setModelInfo('deepseek-cloud')
    render(<OrchestrationPanel />)
    const badge = screen.getByText('deepseek-cloud')
    expect(badge.className).toContain('model-cloud')
  })

  it('shows model badge with local class for local models', () => {
    useAppStore.getState().setModelInfo('lfm2-8b-local')
    render(<OrchestrationPanel />)
    const badge = screen.getByText('lfm2-8b-local')
    expect(badge.className).toContain('model-local')
  })

  it('shows compression stats when contextCompression is set', () => {
    useAppStore.getState().setContextCompression({
      messagesCompressed: 8,
      tokensFreed: 5000,
    })
    render(<OrchestrationPanel />)
    expect(screen.getByText(/messages/)).toBeTruthy()
    expect(screen.getByText(/5000/)).toBeTruthy()
  })

  it('shows memory indicator when memoryUpdatedAt is set', () => {
    useAppStore.getState().setMemoryUpdatedAt(Date.now())
    render(<OrchestrationPanel />)
    expect(screen.getByText(/saved/)).toBeTruthy()
  })
})

// ── SafeModePanel (with mocked fetch) ──────────────────────────────────

describe('SafeModePanel', () => {
  it('renders safe mode and execution policy sections', () => {
    render(<SafeModePanel />)
    expect(screen.getByText('Safe Mode')).toBeTruthy()
    expect(screen.getByText(/Execution policy/)).toBeTruthy()
    expect(screen.getByText(/Active mode/)).toBeTruthy()
  })

  it('renders the safe mode dropdown with current value', () => {
    render(<SafeModePanel />)
    const selects = screen.getAllByRole('combobox')
    const safeModeSelect = selects[0] as HTMLSelectElement
    expect(safeModeSelect).toBeTruthy()
  })

  it('renders two dropdowns (safe mode + execution policy)', () => {
    render(<SafeModePanel />)
    const selects = screen.getAllByRole('combobox')
    expect(selects.length).toBeGreaterThanOrEqual(2)
  })

  it('sets operator note on tauri bridge failure', async () => {
    // Mock tauriBridge to fail
    vi.mock('../../lib/tauriBridge', () => ({
      tauriBridge: {
        setSafeMode: vi.fn().mockResolvedValue({ ok: false, error: 'Bridge not available' }),
      },
    }))

    // Re-import needed since we mocked
    const { SafeModePanel: FreshPanel } = await import('../SafeModePanel')
    render(<FreshPanel />)

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'safe_readonly' } })

    await waitFor(() => {
      const state = useAppStore.getState()
      expect(state.operatorNote).toContain('Safe Mode error')
    })
  })
})

// ── LiveTalkControls ────────────────────────────────────────────────────

describe('LiveTalkControls', () => {
  it('renders live talk controls heading', () => {
    render(<LiveTalkControls />)
    expect(screen.getByText('Live Talk')).toBeTruthy()
  })

  it('shows current voice state', () => {
    render(<LiveTalkControls />)
    expect(screen.getByText(/idle/)).toBeTruthy()
  })

  it('shows push-to-talk and hard stop buttons', () => {
    render(<LiveTalkControls />)
    expect(screen.getByText(/Push.*Talk/)).toBeTruthy()
    expect(screen.getByText(/Hard Stop/)).toBeTruthy()
  })

  it('cycles voice state on simulate button click', () => {
    render(<LiveTalkControls />)
    const simulateBtn = screen.getByText(/Simulate/i)
    fireEvent.click(simulateBtn)
    expect(screen.getByText(/recording/)).toBeTruthy()
  })

  it('updates voice state on cycle', () => {
    useAppStore.getState().setVoiceState('recording')
    render(<LiveTalkControls />)
    expect(screen.getByText(/recording/)).toBeTruthy()
  })
})

// ── ProjectKnowledgePanel ───────────────────────────────────────────────

describe('ProjectKnowledgePanel', () => {
  it('shows loading indicator during fetch', () => {
    // Mock fetch to never resolve
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      () => new Promise(() => {}) as Promise<Response>
    )
    render(<ProjectKnowledgePanel activeProjectId="proj-1" />)
    // The refresh button shows "..." while loading
    const refreshButton = screen.getByRole('button', { name: '...' })
    expect(refreshButton).toBeTruthy()
    expect((refreshButton as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows empty state when no knowledge files', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ files: [] }),
    } as Response)

    render(<ProjectKnowledgePanel activeProjectId="proj-1" />)

    await waitFor(() => {
      expect(screen.getByText(/No knowledge files/)).toBeTruthy()
    })
  })

  it('renders knowledge file names', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        files: [
          { name: 'notes.md', type: 'knowledge', added_at: 1000 },
          { name: 'api_docs.md', type: 'knowledge', added_at: 2000 },
        ],
      }),
    } as Response)

    render(<ProjectKnowledgePanel activeProjectId="proj-1" />)

    await waitFor(() => {
      expect(screen.getByText('notes.md')).toBeTruthy()
      expect(screen.getByText('api_docs.md')).toBeTruthy()
    })
  })

  it('shows error message on fetch failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
    } as Response)

    render(<ProjectKnowledgePanel activeProjectId="proj-1" />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load/)).toBeTruthy()
    })
  })

  it('calls fetch again on refresh click', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ files: [] }),
    } as Response)

    render(<ProjectKnowledgePanel activeProjectId="proj-1" />)

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled()
    })

    fetchSpy.mockClear()
    fireEvent.click(screen.getByText(/Refresh/))

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled()
    })
  })
})

// ── AppShell ────────────────────────────────────────────────────────────

describe('AppShell', () => {
  const defaultProps = {
    onSend: vi.fn(),
    projects: [
      { id: 'default', name: 'Default' },
      { id: 'proj-1', name: 'Project One' },
    ],
    activeProjectId: 'default',
    currentThreadId: 'thread-1',
    onSwitchProject: vi.fn(),
    onRefreshProjects: vi.fn(),
  }

  it('renders all panel sections', () => {
    render(<AppShell {...defaultProps} />)
    expect(screen.getByText('Safe Mode')).toBeTruthy()
    expect(screen.getByText('Orchestration')).toBeTruthy()
  })

  it('renders composer', () => {
    render(<AppShell {...defaultProps} />)
    expect(screen.getByPlaceholderText('Ask Owlynn...')).toBeTruthy()
  })

  it('passes onSend to Composer', () => {
    render(<AppShell {...defaultProps} />)

    const textarea = screen.getByPlaceholderText('Ask Owlynn...')
    fireEvent.change(textarea, { target: { value: 'Test message' } })
    fireEvent.click(screen.getByText('Send'))

    expect(defaultProps.onSend).toHaveBeenCalledWith('Test message')
  })

  it('renders the project list', () => {
    render(<AppShell {...defaultProps} />)
    expect(screen.getByText('Default')).toBeTruthy()
    expect(screen.getByText('Project One')).toBeTruthy()
  })
})
