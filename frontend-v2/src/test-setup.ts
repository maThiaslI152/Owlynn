// Polyfill browser APIs needed by ToolExecutionPanel for vitest node environment.
// Only used during test runs — excluded from production build via tsconfig.
/* eslint-disable @typescript-eslint/no-unused-vars */

import { createHash, randomUUID } from 'node:crypto'

declare const globalThis: {
  crypto: Crypto & {
    subtle: SubtleCrypto
    randomUUID: () => string
    getRandomValues: (arr: ArrayBufferView) => ArrayBufferView
  }
  URL: {
    new(url: string | URL, base?: string | URL): URL
    createObjectURL?: (blob: Blob) => string
    revokeObjectURL?: (url: string) => void
    prototype: URL
  }
  navigator: {
    clipboard?: { writeText: (text: string) => Promise<void>; readText: () => Promise<string> }
  }
}

// -- crypto.subtle polyfill using Node's crypto --
if (!globalThis.crypto?.subtle) {
  const subtle = {
    digest: async (_algorithm: string, data: BufferSource): Promise<ArrayBuffer> => {
      const hash = createHash('sha256')
      hash.update(Buffer.from(data as ArrayBuffer))
      return hash.digest().buffer as ArrayBuffer
    },
    importKey: async (
      _format: string,
      _keyData: BufferSource,
      _algorithm: { name: string; hash: string },
      _extractable: boolean,
      _keyUsages: string[]
    ): Promise<CryptoKey> => {
      return { type: 'secret', extractable: false, algorithm: { name: 'HMAC' }, usages: ['sign'] } as unknown as CryptoKey
    },
    sign: async (
      _algorithm: string | { name: string },
      _key: CryptoKey,
      data: BufferSource
    ): Promise<ArrayBuffer> => {
      const hash = createHash('sha256')
      hash.update(Buffer.from(data as ArrayBuffer))
      return hash.digest().buffer as ArrayBuffer
    },
  } as SubtleCrypto

  const cryptoObj = {
    subtle,
    randomUUID: () => randomUUID(),
    getRandomValues: (arr: ArrayBufferView) => {
      const buf = Buffer.alloc(arr.byteLength)
      for (let i = 0; i < arr.byteLength; i++) {
        buf[i] = Math.floor(Math.random() * 256)
      }
      const view = arr as Uint8Array
      view.set(buf)
      return arr
    },
  } as Crypto

  globalThis.crypto = cryptoObj
}

// -- URL.createObjectURL / revokeObjectURL polyfill --
if (!('createObjectURL' in URL)) {
  const objectUrlMap = new Map<string, Blob>()
  let counter = 0

  ;(URL as unknown as { createObjectURL: (blob: Blob) => string }).createObjectURL = (_blob: Blob) => {
    return `blob:nodedata:${++counter}`
  }

  ;(URL as unknown as { revokeObjectURL: (url: string) => void }).revokeObjectURL = (url: string) => {
    objectUrlMap.delete(url)
  }
}

// -- navigator.clipboard polyfill --
if (!globalThis.navigator?.clipboard) {
  Object.defineProperty(globalThis.navigator, 'clipboard', {
    value: {
      writeText: async (_text: string) => {},
      readText: async () => '',
    },
    writable: true,
    configurable: true,
  })
}
