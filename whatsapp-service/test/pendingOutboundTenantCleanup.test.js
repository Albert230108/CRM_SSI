const test = require('node:test');
const assert = require('node:assert/strict');

// Regression for WA-1: the per-message pending-tenant map (pendingOutboundTenantByMessageId) was
// written on every outbound send but never deleted -- unlike the chat/identity maps -- so it grew
// unbounded for the life of the process. forwardOutboundCapturedMessage must now release the
// message-id entry alongside the chat/identity entries once the message has been forwarded.
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

test('forwarding a captured outbound message releases its pending-tenant message-id entry', async () => {
  const originalFetch = global.fetch;
  const originalEnv = process.env.CRM_WEBHOOK_URL;
  try {
    const client = loadWhatsappClientWithWebhookConfigured();
    global.fetch = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }), text: async () => '' });

    const messageId = 'wamid.leak-1';
    const message = {
      fromMe: true,
      id: { _serialized: messageId },
      body: 'hello there',
      from: 'me@c.us',
      to: '31612345678@c.us',
      chatId: '31612345678@c.us',
      timestamp: 1710000000,
    };

    client.__seedPendingOutboundTenantByMessageId(messageId, 42);
    assert.equal(client.__hasPendingOutboundTenantByMessageId(messageId), true);

    await client.forwardOutboundCapturedMessage(message, message.chatId, message.to, 'test', 42);

    assert.equal(
      client.__hasPendingOutboundTenantByMessageId(messageId),
      false,
      'the message-id entry must be deleted after the message is forwarded',
    );
  } finally {
    global.fetch = originalFetch;
    process.env.CRM_WEBHOOK_URL = originalEnv;
  }
});
