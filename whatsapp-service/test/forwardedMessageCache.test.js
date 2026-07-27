const test = require('node:test');
const assert = require('node:assert/strict');

const { createForwardedMessageCache } = require('../src/forwardedMessageCache');

test('marks a message forwarded and expires it after the TTL elapses', () => {
  let clock = 1_000;
  const cache = createForwardedMessageCache({ ttlMs: 500, now: () => clock });

  cache.markForwarded('wamid-1');
  assert.equal(cache.isForwarded('wamid-1'), true);

  clock += 499;
  assert.equal(cache.isForwarded('wamid-1'), true);

  clock += 2;
  assert.equal(cache.isForwarded('wamid-1'), false);
});

test('claimInFlight blocks a concurrent duplicate claim until released', () => {
  const cache = createForwardedMessageCache({ ttlMs: 1000 });

  assert.equal(cache.claimInFlight('wamid-2'), true);
  assert.equal(cache.claimInFlight('wamid-2'), false);

  cache.releaseInFlight('wamid-2');
  assert.equal(cache.claimInFlight('wamid-2'), true);
});

test('messages without an id are never deduplicated', () => {
  const cache = createForwardedMessageCache({ ttlMs: 1000 });

  assert.equal(cache.isForwarded(null), false);
  assert.equal(cache.isForwarded(undefined), false);
  assert.equal(cache.claimInFlight(null), true);
  assert.equal(cache.claimInFlight(undefined), true);

  cache.markForwarded(null);
  assert.equal(cache.isForwarded(null), false);
});

test('createForwardedMessageCache requires a positive ttlMs', () => {
  assert.throws(() => createForwardedMessageCache({ ttlMs: 0 }));
  assert.throws(() => createForwardedMessageCache({ ttlMs: -1 }));
  assert.throws(() => createForwardedMessageCache({}));
});
