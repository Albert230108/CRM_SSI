const test = require('node:test');
const assert = require('node:assert/strict');

const { createTeardownWindow, isTransientPageError } = require('../src/transientErrors');

// The exact string journalctl captured on crm-whatsapp / crm-whatsapp-2 (2026-09-04) when a LOGOUT
// crashed the process. Before the fix this fell through the ignore list to process.exit(1), which
// killed Chrome mid-write, corrupted the LocalAuth session and forced a fresh QR scan.
test('the production onQRChangedEvent binding collision is treated as transient, not fatal', () => {
  const error = new Error(
    "Failed to add page binding with name onQRChangedEvent: window['onQRChangedEvent'] already exists!",
  );

  assert.equal(isTransientPageError(error), true);
});

test('classifies the known Puppeteer/WhatsApp Web teardown errors as transient', () => {
  const transientMessages = [
    'Execution context was destroyed, most likely because of a navigation.',
    'Execution context is not available in detached frame',
    'Attempted to use detached Frame',
    'Protocol error (Runtime.callFunctionOn): Target closed.',
    'Session closed. Most likely the page has been closed.',
  ];

  for (const message of transientMessages) {
    assert.equal(isTransientPageError(new Error(message)), true, `expected transient: ${message}`);
  }
});

// Puppeteer raises TargetCloseError whose message does not always repeat the class name, so the
// classifier has to consider error.name too.
test('matches Puppeteer error classes by name when the message alone does not', () => {
  const error = new Error('Target closed');
  error.name = 'TargetCloseError';

  assert.equal(isTransientPageError(error), true);
});

test('leaves genuine application errors fatal', () => {
  assert.equal(isTransientPageError(new TypeError("Cannot read properties of undefined (reading 'id')")), false);
  assert.equal(isTransientPageError(new Error('CRM webhook responded 500')), false);
  assert.equal(isTransientPageError(new Error('connect ECONNREFUSED 127.0.0.1:8000')), false);
});

test('handles non-Error rejection values without throwing', () => {
  assert.equal(isTransientPageError('Target closed'), true);
  assert.equal(isTransientPageError(undefined), false);
  assert.equal(isTransientPageError(null), false);
});

test('teardown window is open only for the grace period', () => {
  let clock = 1_000;
  const window = createTeardownWindow({ now: () => clock });

  assert.equal(window.isOpen(), false, 'closed before any teardown');

  window.open(500);
  assert.equal(window.isOpen(), true);

  clock += 499;
  assert.equal(window.isOpen(), true);

  clock += 2;
  assert.equal(window.isOpen(), false, 'closes once the grace period elapses');
});

// A disconnect landing mid-restart must not let the shorter window retract the longer one, or the
// tail of the first teardown becomes fatal again.
test('overlapping teardowns extend the window and never shorten it', () => {
  let clock = 1_000;
  const window = createTeardownWindow({ now: () => clock });

  window.open(10_000);
  window.open(100);

  clock += 5_000;
  assert.equal(window.isOpen(), true, 'the longer window still governs');

  clock += 5_001;
  assert.equal(window.isOpen(), false);
});
