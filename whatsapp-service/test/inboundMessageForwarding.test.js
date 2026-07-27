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

// Regression test: forwardInboundMessage (the live "message" event handler) previously
// hardcoded source:"history" on its payload, a leftover from an unrelated history-sync fix.
// The CRM backend treats source in {"history","backfill"} as replay traffic and skips
// registering an AI auto-draft trigger for it, so every live inbound message silently
// never triggered auto-drafting.
test('a genuinely live inbound message is forwarded without a history/backfill source tag', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;

  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();

    let capturedBody = null;
    global.fetch = async (_url, options) => {
      capturedBody = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    const message = {
      fromMe: false,
      isStatus: false,
      body: 'hi there',
      from: '31612345678@c.us',
      timestamp: 1000,
      id: { _serialized: 'wamid.live-1' },
    };

    const result = await forwardInboundMessage(message);

    assert.equal(result, true);
    assert.ok(capturedBody, 'expected the message to be forwarded to the CRM webhook');
    assert.notEqual(capturedBody.source, 'history');
    assert.notEqual(capturedBody.source, 'backfill');
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});
