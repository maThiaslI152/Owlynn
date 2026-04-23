import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WsClient } from './wsClient'
import type { ServerEvent } from '../types/protocol'

// Minimal Event polyfills for Node (vitest doesn't provide browser event constructors)
class PolyfillEvent {
  readonly type: string
  constructor(type: string) { this.type = type }
}

type EventHandler = (event: { type: string }) => void

interface MockWebSocketLike {
  readyState: number
  url: string
  addEventListener: ReturnType<typeof vi.fn>
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

describe('WsClient protocol-safety regressions', () => {
  let mockSocket: MockWebSocketLike
  let capturedOpenHandler: EventHandler | null
  let capturedCloseHandler: EventHandler | null
  let capturedErrorHandler: EventHandler | null
  let capturedMessageHandler: ((event: { data: string }) => void) | null
  let originalWebSocket: typeof globalThis.WebSocket | undefined

  beforeEach(() => {
    capturedOpenHandler = null
    capturedCloseHandler = null
    capturedErrorHandler = null
    capturedMessageHandler = null

    mockSocket = {
      readyState: 1,
      url: 'ws://localhost/test',
      send: vi.fn(),
      close: vi.fn(),
      addEventListener: vi.fn((type: string, handler: (event: unknown) => void) => {
        if (type === 'open') capturedOpenHandler = handler
        else if (type === 'close') capturedCloseHandler = handler
        else if (type === 'error') capturedErrorHandler = handler
        else if (type === 'message') capturedMessageHandler = handler as (event: { data: string }) => void
      }) as unknown as ReturnType<typeof vi.fn>,
    }

    const MockWebSocketConstructor = function MockWebSocket(url: string | URL) {
      const instance = Object.create(mockSocket)
      instance.readyState = 1
      instance.url = String(url)
      instance.send = mockSocket.send
      instance.close = mockSocket.close
      instance.addEventListener = mockSocket.addEventListener
      return instance
    } as unknown as {
      new(url: string | URL): WebSocket
      OPEN: number
      CONNECTING: number
      CLOSING: number
      CLOSED: number
    }
    MockWebSocketConstructor.OPEN = 1
    MockWebSocketConstructor.CONNECTING = 0
    MockWebSocketConstructor.CLOSING = 2
    MockWebSocketConstructor.CLOSED = 3

    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocketConstructor as unknown as typeof globalThis.WebSocket
  })

  afterEach(() => {
    if (originalWebSocket !== undefined) {
      globalThis.WebSocket = originalWebSocket
    } else {
      delete (globalThis as Record<string, unknown>).WebSocket
    }
    vi.restoreAllMocks()
  })

  function simulateServerMessage(data: string) {
    if (capturedMessageHandler) {
      capturedMessageHandler({ data })
    }
  }

  function simulateOpen() {
    if (capturedOpenHandler) capturedOpenHandler(new PolyfillEvent('open') as unknown as { type: string })
  }

  function simulateClose() {
    if (capturedCloseHandler) capturedCloseHandler(new PolyfillEvent('close') as unknown as { type: string })
  }

  function simulateError() {
    if (capturedErrorHandler) capturedErrorHandler(new PolyfillEvent('error') as unknown as { type: string })
  }

  it('ignores malformed JSON payloads without throwing', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })

    simulateServerMessage('not valid json')
    expect(onEvent).not.toHaveBeenCalled()

    simulateServerMessage('{"type": "assistant.message", "id": "m1", "content": "hello"}')
    expect(onEvent).toHaveBeenCalledTimes(1)
  })

  it('passes through well-formed JSON even if not a known ServerEvent type', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })

    simulateServerMessage('{"type": "unknown_event_type", "data": 42}')
    // WsClient is a thin transport layer; type filtering is the consumer's responsibility.
    expect(onEvent).toHaveBeenCalledWith({ type: 'unknown_event_type', data: 42 })
  })

  it('passes through parsed primitives and null from the wire', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })

    simulateServerMessage('null')
    simulateServerMessage('42')
    simulateServerMessage('"string"')
    expect(onEvent).toHaveBeenCalledTimes(3)
    expect(onEvent).toHaveBeenNthCalledWith(1, null)
    expect(onEvent).toHaveBeenNthCalledWith(2, 42)
    expect(onEvent).toHaveBeenNthCalledWith(3, 'string')
  })

  it('calls onOpen when websocket opens', () => {
    const onOpen = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onOpen })

    simulateOpen()
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when websocket closes', () => {
    const onClose = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onClose })

    simulateClose()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onError when websocket errors', () => {
    const onError = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onError })

    simulateError()
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it('dispatches valid events to onEvent handler', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })

    const payload: ServerEvent = {
      type: 'assistant.message',
      id: 'm1',
      content: 'hello',
    }
    simulateServerMessage(JSON.stringify(payload))

    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenCalledWith(payload)
  })

  it('does not dispatch when no onEvent handler is provided', () => {
    const client = new WsClient('ws://localhost/chat')
    expect(() => {
      client.connect({})
      simulateServerMessage(JSON.stringify({ type: 'assistant.message', id: 'm1', content: 'x' }))
    }).not.toThrow()
  })

  it('send silently drops messages when socket is not open', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })

    // Set readyState to CLOSED on the actual mock instance after connect.
    // The mock constructor creates a fresh object, so we need to reach
    // the actual socket reference directly.
    const socket = (client as unknown as { socket: { readyState: number } }).socket
    socket.readyState = 3 // CLOSED

    expect(() => {
      client.send({ type: 'user.message' as const, id: 'm1', content: 'hi' })
    }).not.toThrow()
    expect(mockSocket.send).not.toHaveBeenCalled()
  })

  it('send passes serialized client event when socket is open', () => {
    const onEvent = vi.fn()
    const client = new WsClient('ws://localhost/chat')
    client.connect({ onEvent })
    simulateOpen()

    client.send({ type: 'user.message', id: 'm1', content: 'hello' })
    expect(mockSocket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'user.message', id: 'm1', content: 'hello' })
    )
  })

  it('disconnect cleanup closes socket and sets to null', () => {
    const client = new WsClient('ws://localhost/chat')
    const disconnect = client.connect({})
    simulateOpen()

    disconnect()
    expect(mockSocket.close).toHaveBeenCalledTimes(1)
  })

  it('triggers all lifecycle handlers in sequence: open, message, close', () => {
    const onOpen = vi.fn()
    const onClose = vi.fn()
    const onEvent = vi.fn()

    const client = new WsClient('ws://localhost/chat')
    client.connect({ onOpen, onClose, onEvent })

    simulateOpen()
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    expect(onEvent).not.toHaveBeenCalled()

    simulateServerMessage(JSON.stringify({ type: 'assistant.message', id: 'm1', content: 'hi' }))
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()

    simulateClose()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('tolerates duplicate disconnect calls gracefully', () => {
    const client = new WsClient('ws://localhost/chat')
    const disconnect = client.connect({})

    disconnect()
    disconnect()
    disconnect()

    // close should only have been called once because socket becomes null
    expect(mockSocket.close).toHaveBeenCalledTimes(1)
  })
})
