const test = require('node:test');
const assert = require('node:assert/strict');

// Regression coverage for the SSI "constant logout" incident (2026-09): the CRM fired /admin/backfill
// on every chat link/relink, and a burst of those each launched its own full-chat scan + history
// fetch against WhatsApp Web. That volume of automation is what got the linked device flagged and
// force-unlinked. runHistoryBackfill now (1) coalesces identical concurrent requests and (2)
// serializes distinct ones so two scans never hit WhatsApp Web at once.

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function makeChat(id, messageCount = 3) {
  const messages = Array.from({ length: messageCount }, (_, index) => ({
    timestamp: 1710000000 + index,
    body: `Message ${index + 1}`,
    fromMe: false,
    from: id,
    to: '15550000000@c.us',
    id: { _serialized: `${id}-msg-${index + 1}` },
  }));
  return {
    id: { _serialized: id },
    isGroup: false,
    syncHistory: async () => {},
    fetchMessages: async ({ limit }) => (Number.isFinite(limit) ? messages.slice(-limit) : messages),
  };
}

// Reloads whatsappClient with a configured CRM webhook + a stubbed global.fetch, mirroring
// fullHistoryResync.test.js. config.js reads process.env once at require time, so the module must be
// reloaded after the env is set, and the module-level throttle state (backfillChain / dedupe map)
// starts fresh for each test.
async function withRunHistoryBackfill(run) {
  const originalEnv = {
    CRM_API_BASE_URL: process.env.CRM_API_BASE_URL,
    CRM_WEBHOOK_URL: process.env.CRM_WEBHOOK_URL,
    CRM_WEBHOOK_SECRET: process.env.CRM_WEBHOOK_SECRET,
  };
  const originalFetch = global.fetch;
  const modulePath = require.resolve('../src/whatsappClient');
  const configPath = require.resolve('../src/config');

  process.env.CRM_API_BASE_URL = 'http://crm.test';
  process.env.CRM_WEBHOOK_URL = 'http://crm.test/webhooks/whatsapp';
  process.env.CRM_WEBHOOK_SECRET = 'test-webhook-secret';

  global.fetch = async () => ({
    ok: true,
    status: 200,
    headers: { 'content-type': 'application/json' },
    json: async () => ({ ok: true, processed: 0, failed: 0 }),
    text: async () => '',
  });

  delete require.cache[modulePath];
  delete require.cache[configPath];
  const { runHistoryBackfill } = require('../src/whatsappClient');

  try {
    await run(runHistoryBackfill);
  } finally {
    global.fetch = originalFetch;
    for (const [key, value] of Object.entries(originalEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    delete require.cache[modulePath];
    delete require.cache[configPath];
  }
}

// A getChats stub that tracks how many times it ran and the peak number of overlapping runs.
function makeTrackingClient(chats) {
  const state = { calls: 0, active: 0, maxActive: 0 };
  const clientOverride = {
    getChats: async () => {
      state.calls += 1;
      state.active += 1;
      state.maxActive = Math.max(state.maxActive, state.active);
      // Yield so a concurrent, un-serialized call would overlap here and push maxActive to 2.
      await tick();
      await tick();
      state.active -= 1;
      return chats;
    },
  };
  return { clientOverride, state };
}

test('identical concurrent backfill requests coalesce into a single scan', async () => {
  await withRunHistoryBackfill(async (runHistoryBackfill) => {
    const { clientOverride, state } = makeTrackingClient([makeChat('326472368@lid')]);
    const eligibleIdentityIndex = { chatIds: new Set(['326472368@lid']), phoneNumbers: new Set() };
    const options = {
      all: false,
      clientOverride,
      readyOverride: true,
      limit: 100,
      postSyncDelayMs: 0,
      eligibleIdentityIndex,
    };

    const [r1, r2, r3] = await Promise.all([
      runHistoryBackfill({ ...options }),
      runHistoryBackfill({ ...options }),
      runHistoryBackfill({ ...options }),
    ]);

    assert.equal(state.calls, 1, 'three identical concurrent backfills should trigger exactly one scan');
    assert.equal(r1, r2, 'coalesced callers should receive the same result promise');
    assert.equal(r2, r3);
  });
});

test('distinct backfill requests run serially, never concurrently', async () => {
  await withRunHistoryBackfill(async (runHistoryBackfill) => {
    const { clientOverride, state } = makeTrackingClient([makeChat('31699999999@c.us')]);
    const eligibleIdentityIndex = { chatIds: new Set(), phoneNumbers: new Set() };
    const base = {
      all: true,
      clientOverride,
      readyOverride: true,
      postSyncDelayMs: 0,
      eligibleIdentityIndex,
    };

    // Different `limit` => different dedupe keys => no coalescing, so both must actually run.
    await Promise.all([
      runHistoryBackfill({ ...base, limit: 100 }),
      runHistoryBackfill({ ...base, limit: 50 }),
    ]);

    assert.equal(state.calls, 2, 'distinct backfills should each run');
    assert.equal(state.maxActive, 1, 'two backfill scans must never hit WhatsApp Web at the same time');
  });
});
