import type { ClientEvent, ServerEvent } from '../types/protocol'

interface ConnectHandlers {
  onOpen?: () => void
  onClose?: () => void
  onError?: () => void
  onEvent?: (event: ServerEvent) => void
}

export class WsClient {
  private socket: WebSocket | null = null
  private readonly url: string

  constructor(url: string) {
    this.url = url
  }

  connect(handlers: ConnectHandlers): () => void {
    this.socket = new WebSocket(this.url)

    this.socket.addEventListener('open', () => handlers.onOpen?.())
    this.socket.addEventListener('close', () => handlers.onClose?.())
    this.socket.addEventListener('error', () => handlers.onError?.())
    this.socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data) as ServerEvent
        handlers.onEvent?.(payload)
      } catch {
        // Ignore malformed payloads from incompatible protocol emitters.
      }
    })

    return () => {
      this.socket?.close()
      this.socket = null
    }
  }

  send(event: ClientEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return
    this.socket.send(JSON.stringify(event))
  }
}
