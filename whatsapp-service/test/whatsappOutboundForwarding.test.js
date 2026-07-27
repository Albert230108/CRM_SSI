const test = require('node:test');
const assert = require('node:assert/strict');

function loadWhatsappClientWithWebhookConfigured() {
  const modulePath = require.resolve('../src/whatsappClient');
  const configPath = require.resolve('../src/config');
  delete require.cache[modulePath];
  delete require.cache[configPath];

  process.env.CRM_WEBHOOK_URL = 'http://crm.test/webhooks/whatsapp';
  delete process.env.CRM_WEBHOOK_SECRET;
  delete process.env.CRM_WEBHOOK_ROUTE_TOKEN;

  return require('../src/whatsappClient');
}

test('the same provider message id from sendMessage and message_create is forwarded to the CRM only once', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;

  try {
    const { forwardCrmMessage } = loadWhatsappClientWithWebhookConfigured();

    let fetchCalls = 0;
    global.fetch = async () => {
      fetchCalls += 1;
      // Simulate real network latency so both concurrent callers are mid-flight together.
      await new Promise((resolve) => setTimeout(resolve, 20));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    const payload = { whatsapp_message_id: 'wamid.dup-1', whatsapp_chat_id: 'chat-1' };
    const [fromSendMessage, fromMessageCreate] = await Promise.all([
      forwardCrmMessage(payload, 'sendMessage'),
      forwardCrmMessage(payload, 'message_create'),
    ]);

    assert.equal(fetchCalls, 1);
    assert.equal([fromSendMessage, fromMessageCreate].filter(Boolean).length, 1);

    // A later, non-concurrent attempt for the same id is also suppressed (TTL dedup).
    const laterAttempt = await forwardCrmMessage(payload, 'message_create');
    assert.equal(laterAttempt, false);
    assert.equal(fetchCalls, 1);
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});

test('messages lacking a provider message id are never deduplicated and are always forwarded', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;

  try {
    const { forwardCrmMessage } = loadWhatsappClientWithWebhookConfigured();

    let fetchCalls = 0;
    global.fetch = async () => {
      fetchCalls += 1;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    const payload = { whatsapp_chat_id: 'chat-2' };
    const first = await forwardCrmMessage(payload, 'sendMessage');
    const second = await forwardCrmMessage(payload, 'message_create');

    assert.equal(first, true);
    assert.equal(second, true);
    assert.equal(fetchCalls, 2);
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});
