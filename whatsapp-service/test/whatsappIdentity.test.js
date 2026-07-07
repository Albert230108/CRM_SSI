const test = require('node:test');
const assert = require('node:assert/strict');

const { getCanonicalWhatsAppIdentity, normalizeWhatsAppChatId, normalizeWhatsAppPhone } = require('../src/whatsappIdentity');
const { resolveOutboundTenantOwnership } = require('../src/outboundResolution');

test('normalizes WhatsApp phone and preserves raw group chat ids', () => {
  const inbound = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '155066153590862@lid',
    sender: '+31 6 123 456 78',
    sender_normalized: '31612345678',
  }, { direction: 'inbound' });

  const group = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '123456789@G.US',
    sender: '+31 6 123 456 78',
    sender_normalized: '31612345678',
  }, { direction: 'inbound' });

  assert.equal(normalizeWhatsAppPhone('+31 6 123 456 78'), '31612345678');
  assert.equal(normalizeWhatsAppChatId('155066153590862@lid'), '155066153590862@lid');
  assert.equal(inbound.rawChatId, '155066153590862@lid');
  assert.equal(inbound.normalizedPhone, '31612345678');
  assert.equal(inbound.canonicalChatId, '31612345678');
  assert.equal(inbound.isGroup, false);
  assert.equal(group.rawChatId, '123456789@g.us');
  assert.equal(group.canonicalChatId, '123456789@g.us');
  assert.equal(group.isGroup, true);
});

test('resolveOutboundTenantOwnership prefers canonical identity before raw chat id', async () => {
  const calls = [];
  const result = await resolveOutboundTenantOwnership({
    messageId: 'msg-identity',
    chatId: '155066153590862@lid',
    identityKey: '31612345678',
    normalizedPhone: '31612345678',
    externalAccountId: 'client-identity',
    lookupDurableTenant: async (params) => {
      calls.push(params);
      if (params.whatsapp_identity_key === '31612345678' && params.external_account_id === 'client-identity') {
        return { found: true, tenant_id: 44 };
      }
      return { found: false };
    },
    getMemoryTenantId: () => null,
    retryDelaysMs: [0],
  });

  assert.equal(result.tenantId, 44);
  assert.equal(result.resolutionSource, 'durable');
  assert.equal(result.resolutionStrategy, 'identity_key_external_account_id');
  assert.deepEqual(calls, [
    { provider_message_id: 'msg-identity' },
    { whatsapp_identity_key: '31612345678', external_account_id: 'client-identity' },
  ]);
});
