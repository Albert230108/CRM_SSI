const test = require('node:test');
const assert = require('node:assert/strict');

function makeChat(id, messageCount, { withEligibleIdentity = true } = {}) {
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
    __withEligibleIdentity: withEligibleIdentity,
  };
}

async function withMockedForward(t, run) {
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

  global.fetch = async (url, options = {}) => {
    if (options.body) {
      try {
        const parsedBody = JSON.parse(options.body);
        if (Array.isArray(parsedBody.messages)) {
          return {
            ok: true,
            status: 200,
            headers: { 'content-type': 'application/json' },
            json: async () => ({ ok: true, processed: parsedBody.messages.length, failed: 0 }),
            text: async () => '',
          };
        }
      } catch (error) {
        // fall through to the generic response below
      }
    }

    return {
      ok: true,
      status: 200,
      headers: { 'content-type': 'application/json' },
      json: async () => ({ ok: true }),
      text: async () => '',
    };
  };

  // config.js reads process.env once at require time, so whatsappClient must be
  // reloaded after the env vars above are set (see historyBackfill.test.js for the
  // same pattern) or forwardCrmMessage will always see an unconfigured webhook URL.
  delete require.cache[modulePath];
  delete require.cache[configPath];
  const { backfillAllChats } = require('../src/whatsappClient');

  try {
    await run(backfillAllChats);
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

test('backfillAllChats pulls full history (not capped) for CRM-eligible chats by default', async (t) => {
  await withMockedForward(t, async (backfillAllChats) => {
    // 150 messages in the chat; the old default cap (limit=100) would have silently dropped
    // the oldest 50. A manually linked chat is CRM-eligible via its identity index below.
    const chat = makeChat('326472368@lid', 150);

    const result = await backfillAllChats({
      all: false,
      clientOverride: { getChats: async () => [chat] },
      readyOverride: true,
      limit: 100,
      postSyncDelayMs: 0,
      eligibleIdentityIndex: { chatIds: new Set(['326472368@lid']), phoneNumbers: new Set() },
    });

    assert.equal(result.scope, 'crm_scoped');
    assert.equal(result.total_synced_chats, 1);
    assert.equal(result.fetched, 150, 'expected every message in the chat to be fetched, not just the last 100');
    assert.equal(result.imported, 150);
  });
});

test('backfillAllChats keeps the capped limit for the broad all=true sweep', async (t) => {
  await withMockedForward(t, async (backfillAllChats) => {
    const chat = makeChat('31699999999@c.us', 150);

    const result = await backfillAllChats({
      all: true,
      clientOverride: { getChats: async () => [chat] },
      readyOverride: true,
      limit: 100,
      postSyncDelayMs: 0,
    });

    assert.equal(result.scope, 'all');
    assert.equal(result.fetched, 100, 'the indiscriminate all=true sweep should still respect the cap');
  });
});

test('backfillAllChats with chatId targets exactly one chat and forces full history', async (t) => {
  await withMockedForward(t, async (backfillAllChats) => {
    const target = makeChat('326472368@lid', 250);
    const other = makeChat('31699999999@c.us', 250);

    const result = await backfillAllChats({
      all: false,
      chatId: '326472368@lid',
      clientOverride: { getChats: async () => [target, other] },
      readyOverride: true,
      limit: 100,
      postSyncDelayMs: 0,
    });

    assert.equal(result.total_chats_in_whatsapp, 1, 'only the targeted chat should be considered');
    assert.equal(result.fetched, 250);
    assert.equal(result.imported, 250);
  });
});

test('media messages (images, voice notes, etc.) are imported with a placeholder instead of being silently dropped', async (t) => {
  await withMockedForward(t, async (backfillAllChats) => {
    const chatId = '326472368@lid';
    const messages = [
      { timestamp: 1710000000, body: 'Text message', fromMe: false, from: chatId, id: { _serialized: 'm-1' } },
      { timestamp: 1710000001, type: 'image', fromMe: false, from: chatId, id: { _serialized: 'm-2' } },
      { timestamp: 1710000002, type: 'ptt', fromMe: true, to: chatId, id: { _serialized: 'm-3' } },
      { timestamp: 1710000003, type: 'document', filename: 'invoice.pdf', fromMe: false, from: chatId, id: { _serialized: 'm-4' } },
      // Genuinely contentless: call log, no body/caption/text and no recognized media type.
      { timestamp: 1710000004, type: 'call_log', fromMe: false, from: chatId, id: { _serialized: 'm-5' } },
    ];
    const chat = {
      id: { _serialized: chatId },
      isGroup: false,
      syncHistory: async () => {},
      fetchMessages: async () => messages,
    };

    const result = await backfillAllChats({
      all: false,
      clientOverride: { getChats: async () => [chat] },
      readyOverride: true,
      postSyncDelayMs: 0,
      eligibleIdentityIndex: { chatIds: new Set([chatId]), phoneNumbers: new Set() },
    });

    assert.equal(result.fetched, 5);
    assert.equal(result.imported, 4, 'the 4 real-content messages (text + 3 media types) should import');
    assert.equal(result.skippedNoContent, 1, 'only the call_log entry has genuinely nothing to show');
  });
});
