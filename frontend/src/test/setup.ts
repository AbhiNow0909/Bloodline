import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import { session } from '../lib/session'

// jsdom has <dialog> but not its modal methods. Enough of them for tests: open and close,
// firing "close" like a browser does.
const dialogProto = HTMLDialogElement.prototype as Partial<HTMLDialogElement>
if (typeof dialogProto.showModal !== 'function') {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.open) return
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}

afterEach(() => {
  cleanup()
  session.clear()
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
