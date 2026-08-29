// Lightweight, dependency-free sound-effect feedback for the CRM.
//
// Sounds are synthesized on the fly with the Web Audio API rather than shipped as
// audio files: no binary assets in git, no licensing concerns, offline-capable, and
// each tone is precisely tunable here. Playback is gated by a module-level flag kept
// in sync with the per-user "Play sound effects" preference (see displayPreferences),
// so call sites can fire sounds unconditionally without knowing the current setting.

export type SoundKind = 'success' | 'error' | 'info' | 'complete'

// Disabled until synced from the stored preference (default off — see the plan).
let soundsEnabled = false

/** Keep the playback gate in sync with the user's preference. Called from the app root. */
export function setSoundsEnabled(enabled: boolean): void {
  soundsEnabled = enabled
}

// A single shared AudioContext is reused across sounds. Browsers start it "suspended"
// until a user gesture occurs; every sound here follows a click (toast, import, toggle),
// so resuming on demand is reliable.
let audioContext: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return null
  if (!audioContext) audioContext = new Ctor()
  return audioContext
}

// Each note: MIDI-ish frequency in Hz, when to start (seconds after now), and length.
type Note = { freq: number; at: number; duration: number }

// Frequencies (equal temperament). Ascending = positive/good, low/descending = bad.
const A3 = 220
const E3 = 164.81
const C6 = 1046.5
const E6 = 1318.51
const G6 = 1567.98

const SOUND_NOTES: Record<SoundKind, Note[]> = {
  // Soft two-note ascending confirm ding.
  success: [
    { freq: C6, at: 0, duration: 0.12 },
    { freq: E6, at: 0.09, duration: 0.14 },
  ],
  // Gentle two-note low descending "nope".
  error: [
    { freq: A3, at: 0, duration: 0.14 },
    { freq: E3, at: 0.11, duration: 0.18 },
  ],
  // Single soft high ping for passive/incoming events.
  info: [{ freq: E6, at: 0, duration: 0.13 }],
  // Fuller three-note ascending arpeggio for finishing a long job.
  complete: [
    { freq: C6, at: 0, duration: 0.12 },
    { freq: E6, at: 0.1, duration: 0.12 },
    { freq: G6, at: 0.2, duration: 0.2 },
  ],
}

// Kept low so the feedback stays gentle rather than startling.
const PEAK_GAIN = 0.12

/** Play the sound for `kind`. No-op when sounds are disabled or audio is unavailable. */
export function playSound(kind: SoundKind): void {
  if (!soundsEnabled) return
  try {
    const ctx = getAudioContext()
    if (!ctx) return
    if (ctx.state === 'suspended') void ctx.resume()

    const now = ctx.currentTime
    for (const note of SOUND_NOTES[kind]) {
      const oscillator = ctx.createOscillator()
      const gain = ctx.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = note.freq

      const start = now + note.at
      const end = start + note.duration
      // Short attack then exponential decay for a soft, bell-like envelope.
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(PEAK_GAIN, start + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, end)

      oscillator.connect(gain)
      gain.connect(ctx.destination)
      oscillator.start(start)
      oscillator.stop(end + 0.02)
    }
  } catch {
    // Audio must never break the UI; a failed sound is silently ignored.
  }
}
