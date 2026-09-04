const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createReconnectStateStore } = require('../src/reconnectState');

function tempStatePath(name) {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'wa-reconnect-state-')), name);
}

const quietLogger = { warn() {} };

// The whole point of persisting: before this, a LOGOUT could crash the process, systemd restarted
// it, and the counter went back to 0 - so the "pause after N logouts" threshold was unreachable
// precisely when the logouts were what caused the restarts.
test('logout counters survive a simulated process restart', () => {
  const filePath = tempStatePath('state.json');

  const beforeRestart = createReconnectStateStore({ filePath, logger: quietLogger });
  beforeRestart.save({ consecutiveLogoutCount: 4, lastLogoutAt: 1_700_000_000_000, autoReconnectPaused: false });

  const afterRestart = createReconnectStateStore({ filePath, logger: quietLogger }).load();

  assert.equal(afterRestart.consecutiveLogoutCount, 4);
  assert.equal(afterRestart.lastLogoutAt, 1_700_000_000_000);
  assert.equal(afterRestart.autoReconnectPaused, false);
});

test('a paused auto-reconnect stays paused across a restart', () => {
  const filePath = tempStatePath('state.json');

  createReconnectStateStore({ filePath, logger: quietLogger }).save({
    consecutiveLogoutCount: 5,
    lastLogoutAt: 1_700_000_000_000,
    autoReconnectPaused: true,
  });

  assert.equal(createReconnectStateStore({ filePath, logger: quietLogger }).load().autoReconnectPaused, true);
});

test('a missing state file loads clean without warning', () => {
  const filePath = tempStatePath('never-written.json');

  const state = createReconnectStateStore({ filePath, logger: quietLogger }).load();

  assert.deepEqual(state, { consecutiveLogoutCount: 0, lastLogoutAt: 0, autoReconnectPaused: false });
});

// State persistence must never be able to take the client down with it.
test('a corrupt state file degrades to a clean slate instead of throwing', () => {
  const filePath = tempStatePath('corrupt.json');
  fs.writeFileSync(filePath, '{not valid json', 'utf8');

  const state = createReconnectStateStore({ filePath, logger: quietLogger }).load();

  assert.deepEqual(state, { consecutiveLogoutCount: 0, lastLogoutAt: 0, autoReconnectPaused: false });
});

test('unwritable paths fail soft rather than throwing', () => {
  // Use a regular file as a parent directory component: mkdir/write below it fails fast with
  // ENOTDIR. (Do not reach for a /proc path here - mkdirSync({recursive:true}) hangs on those.)
  const blockingFile = tempStatePath('not-a-directory');
  fs.writeFileSync(blockingFile, 'x', 'utf8');

  const store = createReconnectStateStore({
    filePath: path.join(blockingFile, 'state.json'),
    logger: quietLogger,
  });

  assert.equal(store.save({ consecutiveLogoutCount: 1, lastLogoutAt: 0, autoReconnectPaused: false }), false);
  assert.deepEqual(store.load(), { consecutiveLogoutCount: 0, lastLogoutAt: 0, autoReconnectPaused: false });
});

test('an empty configured path disables persistence entirely', () => {
  const store = createReconnectStateStore({ filePath: '', logger: quietLogger });

  assert.equal(store.save({ consecutiveLogoutCount: 3, lastLogoutAt: 1, autoReconnectPaused: true }), false);
  assert.deepEqual(store.load(), { consecutiveLogoutCount: 0, lastLogoutAt: 0, autoReconnectPaused: false });
});

test('clear resets persisted counters', () => {
  const filePath = tempStatePath('state.json');
  const store = createReconnectStateStore({ filePath, logger: quietLogger });

  store.save({ consecutiveLogoutCount: 5, lastLogoutAt: 123, autoReconnectPaused: true });
  store.clear();

  assert.deepEqual(store.load(), { consecutiveLogoutCount: 0, lastLogoutAt: 0, autoReconnectPaused: false });
});
