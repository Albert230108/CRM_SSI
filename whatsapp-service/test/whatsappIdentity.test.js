const test = require('node:test');
const assert = require('node:assert/strict');

const { getCanonicalWhatsAppIdentity, normalizeWhatsAppChatId, normalizeWhatsAppPhone } = require('../src/whatsappIdentity');
const { resolveOutboundTenantOwnership } = require('../src/outboundResolution');

test('normalizes WhatsApp phones, preserves linked-device ids, and keeps groups raw', () => {
  const lidWithoutTrustedPhone = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '155066153590862@lid',
  }, { direction: 'inbound' });

  const lidWithTrustedPhone = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '155066153590862@lid',
    sender_normalized: '31612345678',
  }, { direction: 'inbound' });

  const personChat = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '31612345678@c.us',
  }, { direction: 'inbound' });

  const group = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '123456789@G.US',
  }, { direction: 'inbound' });

  const systemChat = getCanonicalWhatsAppIdentity({
    direction: 'inbound',
    whatsapp_chat_id: '0@c.us',
  }, { direction: 'inbound' });

  assert.equal(normalizeWhatsAppPhone('+31 6 123 456 78'), '31612345678');
  assert.equal(normalizeWhatsAppPhone('155066153590862@lid'), null);
  assert.equal(normalizeWhatsAppPhone('31612345678@c.us'), '31612345678');
  assert.equal(normalizeWhatsAppChatId('155066153590862@lid'), '155066153590862@lid');
  assert.equal(lidWithoutTrustedPhone.rawChatId, '155066153590862@lid');
  assert.equal(lidWithoutTrustedPhone.normalizedPhone, null);
  assert.equal(lidWithoutTrustedPhone.canonicalChatId, '155066153590862@lid');
  assert.equal(lidWithoutTrustedPhone.isGroup, false);
  assert.equal(lidWithTrustedPhone.normalizedPhone, '31612345678');
  assert.equal(lidWithTrustedPhone.canonicalChatId, '31612345678');
  assert.equal(personChat.rawChatId, '31612345678@c.us');
  assert.equal(personChat.normalizedPhone, '31612345678');
  assert.equal(personChat.canonicalChatId, '31612345678');
  assert.equal(group.rawChatId, '123456789@g.us');
  assert.equal(group.canonicalChatId, '123456789@g.us');
  assert.equal(group.isGroup, true);
  assert.equal(systemChat.rawChatId, '0@c.us');
  assert.equal(systemChat.normalizedPhone, null);
  assert.equal(systemChat.canonicalChatId, '0@c.us');
  assert.equal(systemChat.isGroup, false);
});

test('resolveOutboundTenantOwnership prioritizes provider message id, identity key, then raw chat id', async () => {
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
