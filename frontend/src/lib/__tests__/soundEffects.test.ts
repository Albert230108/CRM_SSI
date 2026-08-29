import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { playSound, setSoundsEnabled } from '../soundEffects'

// Minimal Web Audio stubs so playSound can run under jsdom (which has no AudioContext).
function installMockAudioContext() {
  const oscillator = {
    type: 'sine',
    frequency: { value: 0 },
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
  }
  const gain = {
    gain: {
      setValueAtTime: vi.fn(),
      exponentialRampToValueAtTime: vi.fn(),
    },
    connect: vi.fn(),
  }
  const createOscillator = vi.fn(() => oscillator)
  const createGain = vi.fn(() => gain)
  class MockAudioContext {
    currentTime = 0
    state = 'running'
    destination = {}
    resume = vi.fn()
    createOscillator = createOscillator
    createGain = createGain
  }
  ;(window as unknown as { AudioContext: unknown }).AudioContext = MockAudioContext
  return { createOscillator }
}

describe('playSound', () => {
  let createOscillator: ReturnType<typeof installMockAudioContext>['createOscillator']

  beforeEach(() => {
    createOscillator = installMockAudioContext().createOscillator
  })

  afterEach(() => {
    setSoundsEnabled(false)
    vi.restoreAllMocks()
  })

  it('is a no-op when sounds are disabled', () => {
    setSoundsEnabled(false)
    playSound('success')
    expect(createOscillator).not.toHaveBeenCalled()
  })

  it('synthesizes notes when sounds are enabled', () => {
    setSoundsEnabled(true)
    playSound('complete')
    // The "complete" chime is three notes.
    expect(createOscillator).toHaveBeenCalledTimes(3)
  })

  it('never throws even if audio is unavailable', () => {
    setSoundsEnabled(true)
    ;(window as unknown as { AudioContext: undefined }).AudioContext = undefined
    ;(window as unknown as { webkitAudioContext: undefined }).webkitAudioContext = undefined
    expect(() => playSound('error')).not.toThrow()
  })
})
