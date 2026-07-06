const test = require('node:test');
const assert = require('node:assert/strict');

const { resolveOutboundTenantOwnership } = require('../src/outboundResolution');

test('resolves durable provider_message_id before memory fallback', async () => {
  const calls = [];
  const result = await resolveOutboundTenantOwnership({
    messageId: 'msg-1',
    chatId: '155066153590862@lid',
    externalAccountId: 'client-a',
    lookupDurableTenant: async (params) => {
      calls.push(params);
      if (params.provider_message_id === 'msg-1') {
        return { found: true, tenant_id: 42 };
      }
      return { found: false };
    },
    getMemoryTenantId: () => null,
    retryDelaysMs: [0],
  });

  assert.equal(result.tenantId, 42);
  assert.equal(result.resolutionSource, 'durable');
  assert.equal(result.resolutionStrategy, 'provider_message_id');
  assert.deepEqual(calls, [{ provider_message_id: 'msg-1' }]);
});

test('falls back to durable chat_id plus external_account_id after provider message lookup misses', async () => {
  const calls = [];
  const result = await resolveOutboundTenantOwnership({
    messageId: 'msg-missing',
    chatId: '155066153590862@lid',
    externalAccountId: 'client-b',
    lookupDurableTenant: async (params) => {
      calls.push(params);
      if (params.whatsapp_chat_id === '155066153590862@lid' && params.external_account_id === 'client-b') {
        return { found: true, tenant_id: 77 };
      }
      return { found: false };
    },
    getMemoryTenantId: () => null,
    retryDelaysMs: [0],
  });

  assert.equal(result.tenantId, 77);
  assert.equal(result.resolutionSource, 'durable');
  assert.equal(result.resolutionStrategy, 'chat_id_external_account_id');
  assert.deepEqual(calls, [
    { provider_message_id: 'msg-missing' },
    { whatsapp_chat_id: '155066153590862@lid', external_account_id: 'client-b' },
  ]);
});

test('returns null when durable lookup and memory fallback both fail', async () => {
  const result = await resolveOutboundTenantOwnership({
    messageId: 'msg-missing',
    chatId: '155066153590862@lid',
    externalAccountId: 'client-c',
    lookupDurableTenant: async () => ({ found: false }),
    getMemoryTenantId: () => null,
    retryDelaysMs: [0],
  });

  assert.equal(result, null);
});

test("falls back to in-memory mapping when durable lookup misses", async () => {
  const result = await resolveOutboundTenantOwnership({
    messageId: "msg-memory",
    chatId: "155066153590862@lid",
    externalAccountId: "client-memory",
    lookupDurableTenant: async () => ({ found: false }),
    getMemoryTenantId: () => 88,
    retryDelaysMs: [0],
  });

  assert.equal(result.tenantId, 88);
  assert.equal(result.resolutionSource, "memory");
  assert.equal(result.resolutionStrategy, "memory_fallback");
});
