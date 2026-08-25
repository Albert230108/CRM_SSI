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

test('live WhatsApp forwarding tags source=history while within the reconnect grace window', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;

  try {
    const whatsappClient = loadWhatsappClientWithWebhookConfigured();
    const { forwardInboundMessage, forwardOutboundMessage, __setLastReadyAtForTests } = whatsappClient;

    const capturedBodies = [];
    global.fetch = async (_url, options) => {
      capturedBodies.push(JSON.parse(options.body));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    __setLastReadyAtForTests(Date.now());

    const inboundResult = await forwardInboundMessage({
      fromMe: false,
      isStatus: false,
      body: 'hello from inbound',
      from: '31612345678@c.us',
      timestamp: 1000,
      id: { _serialized: 'wamid.reconnect-inbound' },
    });
    const outboundResult = await forwardOutboundMessage({
      body: 'hello from outbound',
      fromMe: true,
      to: '31612345678@c.us',
      timestamp: 1001,
      id: { _serialized: 'wamid.reconnect-outbound' },
    }, '31612345678@c.us', '31612345678@c.us');

    assert.equal(inboundResult, true);
    assert.equal(outboundResult, true);
    assert.equal(capturedBodies.length, 2);
    assert.equal(capturedBodies[0].source, 'history');
    assert.equal(capturedBodies[1].source, 'history');
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});

test('live WhatsApp forwarding leaves source unset outside the reconnect grace window', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;

  try {
    const whatsappClient = loadWhatsappClientWithWebhookConfigured();
    const { forwardInboundMessage, forwardOutboundMessage, __setLastReadyAtForTests } = whatsappClient;

    const capturedBodies = [];
    global.fetch = async (_url, options) => {
      capturedBodies.push(JSON.parse(options.body));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    __setLastReadyAtForTests(Date.now() - 60_000);

    const inboundResult = await forwardInboundMessage({
      fromMe: false,
      isStatus: false,
      body: 'hello from inbound',
      from: '31612345678@c.us',
      timestamp: 2000,
      id: { _serialized: 'wamid.normal-inbound' },
    });
    const outboundResult = await forwardOutboundMessage({
      body: 'hello from outbound',
      fromMe: true,
      to: '31612345678@c.us',
      timestamp: 2001,
      id: { _serialized: 'wamid.normal-outbound' },
    }, '31612345678@c.us', '31612345678@c.us');

    assert.equal(inboundResult, true);
    assert.equal(outboundResult, true);
    assert.equal(capturedBodies.length, 2);
    assert.ok(capturedBodies[0].source == null);
    assert.ok(capturedBodies[1].source == null);
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});
