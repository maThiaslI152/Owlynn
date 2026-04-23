import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useAppStore } from '../../state/useAppStore'
import { ToolExecutionPanel } from '../ToolExecutionPanel'

beforeEach(() => {
  useAppStore.setState(useAppStore.getInitialState(), true)
})

afterEach(() => {
})

describe('ToolExecutionPanel rendering regression', () => {
  it('renders empty state when no tool activity exists', () => {
    render(<ToolExecutionPanel />)
    expect(screen.getByText('Tool Execution')).toBeTruthy()
    expect(screen.getByText('No tool activity yet.')).toBeTruthy()
  })

  it('shows latest tool execution details when a tool is active', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'read_workspace_file',
      ts: Date.now(),
      toolCallId: 'call-1',
      status: 'running',
      input: '{"path":"README.md"}',
      riskLabel: 'read_operation',
      riskConfidence: 0.15,
      riskRationale: 'standard file read',
      remediationHint: 'verify path',
    })

    render(<ToolExecutionPanel />)
    // Tool name appears in both header and history – check it exists at least once
    expect(screen.getAllByText(/read_workspace_file/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText((c) => c.includes('README'))).toBeTruthy()
    expect(screen.getAllByText((c) => c.includes('read_operation')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText((c) => c.includes('15%'))).toBeTruthy()
  })

  it('shows status badge and tool name for errored tools', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'delete_workspace',
      ts: Date.now(),
      toolCallId: 'call-err',
      status: 'error',
    })

    render(<ToolExecutionPanel />)
    expect(screen.getAllByText(/delete_workspace/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders filter buttons', () => {
    render(<ToolExecutionPanel />)
    expect(screen.getByText('all')).toBeTruthy()
    expect(screen.getByText('risky')).toBeTruthy()
    expect(screen.getByText('error')).toBeTruthy()
  })

  it('renders multiple history entries when available', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'read_file',
      ts: 1000,
      toolCallId: 'call-1',
      status: 'success',
      riskLabel: 'read',
    })
    useAppStore.getState().pushToolExecution({
      toolName: 'delete_file',
      ts: 2000,
      toolCallId: 'call-2',
      status: 'running',
      riskLabel: 'destructive',
    })

    render(<ToolExecutionPanel />)
    expect(screen.getAllByText(/delete_file/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders signing key and secret input fields', () => {
    render(<ToolExecutionPanel />)
    expect(screen.getByPlaceholderText('operator-key-1')).toBeTruthy()
    const secretInputs = screen.getAllByPlaceholderText('hmac secret')
    expect(secretInputs.length).toBeGreaterThanOrEqual(2)
  })

  it('renders verify file inputs and action buttons', () => {
    render(<ToolExecutionPanel />)
    expect(screen.getByText('verify-bundle')).toBeTruthy()
    expect(screen.getByText('export-verify-report')).toBeTruthy()
    expect(screen.getByText('copy-verify-js')).toBeTruthy()
    expect(screen.getByText('export-jsonl')).toBeTruthy()
  })

  it('starts with no verify result shown', () => {
    render(<ToolExecutionPanel />)
    expect(screen.queryByText(/Last verify/)).toBeNull()
  })

  it('shows operator note on empty export attempt', () => {
    render(<ToolExecutionPanel />)
    fireEvent.click(screen.getByText('export-jsonl'))
    expect(useAppStore.getState().operatorNote).toContain('skipped')
  })
})

describe('ToolExecutionPanel history filter regression', () => {
  it('applies risky filter via button click', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'safe_read',
      ts: 1000,
      toolCallId: 'safe-1',
      status: 'success',
    })
    useAppStore.getState().pushToolExecution({
      toolName: 'delete_workspace',
      ts: 2000,
      toolCallId: 'risky-1',
      status: 'running',
      riskLabel: 'destructive',
    })

    render(<ToolExecutionPanel />)

    fireEvent.click(screen.getByText('risky'))
    expect(screen.getAllByText(/delete_workspace/).length).toBeGreaterThanOrEqual(1)
  })

  it('applies error filter via button click', () => {
    useAppStore.getState().pushToolExecution({
      toolName: 'good_tool',
      ts: 1000,
      toolCallId: 'good-1',
      status: 'success',
    })
    useAppStore.getState().pushToolExecution({
      toolName: 'failed_tool',
      ts: 2000,
      toolCallId: 'fail-1',
      status: 'error',
    })

    render(<ToolExecutionPanel />)

    const buttons = screen.getAllByRole('button')
    const errorButton = buttons.find((b) => b.textContent === 'error')
    expect(errorButton).toBeTruthy()
    fireEvent.click(errorButton!)
    expect(screen.getAllByText(/failed_tool/).length).toBeGreaterThanOrEqual(1)
  })

  it('copes with empty history under any filter', () => {
    render(<ToolExecutionPanel />)

    fireEvent.click(screen.getByText('risky'))
    fireEvent.click(screen.getByText('all'))

    expect(screen.getByText('No tool activity yet.')).toBeTruthy()
  })
})

describe('ToolExecutionPanel input field regression', () => {
  it('updates signing key input value', () => {
    render(<ToolExecutionPanel />)
    const input = screen.getByPlaceholderText('operator-key-1') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'my-key-1' } })
    expect(input.value).toBe('my-key-1')
  })

  it('updates signing secret input value', () => {
    render(<ToolExecutionPanel />)
    const secretInputs = screen.getAllByPlaceholderText('hmac secret') as HTMLInputElement[]
    fireEvent.change(secretInputs[0], { target: { value: 'supersecret' } })
    expect(secretInputs[0].value).toBe('supersecret')
  })

  it('updates verify secret input value', () => {
    render(<ToolExecutionPanel />)
    const secretInputs = screen.getAllByPlaceholderText('hmac secret') as HTMLInputElement[]
    fireEvent.change(secretInputs[1], { target: { value: 'verifysecret' } })
    expect(secretInputs[1].value).toBe('verifysecret')
  })
})
