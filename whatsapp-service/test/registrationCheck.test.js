const test = require('node:test');
const assert = require('node:assert/strict');

const { sendTextMessage } = require('../src/whatsappClient');
const { whatsappClientId } = require('../src/config');

function fakeClient({ registered = true, getNumberIdImpl } = {}) {
  const calls = [];
  let counter = 0;
  return {
    calls,
    sendMessage: async (chatId, content, options) => {
      counter += 1;
      calls.push({ chatId, content, options: options ?? null });
      return { id: { _serialized: `wamid.sent-${counter}` } };
    },
    getNumberId: getNumberIdImpl || (async () => (registered ? { _serialized: '31612345678@c.us' } : null)),
  };
}

function basePayload(client, overrides = {}) {
  return {
    to: '31612345678',
    message: 'Hi there',
    tenant_id: 7,
    external_account_id: whatsappClientId,
    whatsapp_endpoint_id: null,
    clientOverride: client,
    readyOverride: true,
    ...overrides,
  };
}

test('require_registered_recipient true + registered number sends normally', async () => {
  const client = fakeClient({ registered: true });

  const result = await sendTextMessage(basePayload(client, { require_registered_recipient: true }));

  assert.equal(client.calls.length, 1);
  assert.equal(result.whatsapp_chat_id, '31612345678@c.us');
});

test('require_registered_recipient true + unregistered number rejects before any send', async () => {
  const client = fakeClient({ registered: false });

  await assert.rejects(
    () => sendTextMessage(basePayload(client, { require_registered_recipient: true })),
    /not a registered WhatsApp user/,
  );
  assert.equal(client.calls.length, 0);
});

test('require_registered_recipient omitted skips the check entirely (existing reply path)', async () => {
  const client = fakeClient();
  delete client.getNumberId;

  const result = await sendTextMessage(basePayload(client));

  assert.equal(client.calls.length, 1);
  assert.equal(result.whatsapp_chat_id, '31612345678@c.us');
});

test('getNumberId throwing propagates the underlying error, not "not registered"', async () => {
  const client = fakeClient({
    getNumberIdImpl: async () => {
      throw new Error('client not ready internally');
    },
  });

  await assert.rejects(
    () => sendTextMessage(basePayload(client, { require_registered_recipient: true })),
    /client not ready internally/,
  );
  assert.equal(client.calls.length, 0);
});

test('require_registered_recipient true fetches and returns the contact display name best-effort', async () => {
  const client = fakeClient({ registered: true });
  client.getContactById = async () => ({ pushname: 'Mario Rossi' });

  const result = await sendTextMessage(basePayload(client, { require_registered_recipient: true }));

  assert.equal(result.whatsapp_contact_name, 'Mario Rossi');
});

test('require_registered_recipient true retries once after a transient No LID send failure', async () => {
  const contactLookups = [];
  const calls = [];
  let sendCount = 0;
  const client = {
    calls,
    getNumberId: async () => ({ _serialized: '31612345678@c.us' }),
    getContactById: async (chatId) => {
      contactLookups.push(chatId);
      return { pushname: 'Mario Rossi' };
    },
    sendMessage: async (chatId, content, options) => {
      sendCount += 1;
      calls.push({ chatId, content, options: options ?? null });
      if (sendCount === 1) {
        throw new Error('No LID for user');
      }
      return { id: { _serialized: `wamid.sent-${sendCount}` } };
    },
  };

  const result = await sendTextMessage(basePayload(client, { require_registered_recipient: true }));

  assert.equal(contactLookups.length, 3);
  assert.deepEqual(contactLookups.slice(0, 2), ['31612345678@c.us', '31612345678@c.us']);
  assert.equal(calls.length, 2);
  assert.equal(result.whatsapp_message_id, 'wamid.sent-2');
  assert.equal(result.whatsapp_contact_name, 'Mario Rossi');
});

test('a contact name lookup failure is swallowed and does not fail the send', async () => {
  const client = fakeClient({ registered: true });
  client.getContactById = async () => {
    throw new Error('contact lookup exploded');
  };

  const result = await sendTextMessage(basePayload(client, { require_registered_recipient: true }));

  assert.equal(client.calls.length, 1);
  assert.equal(result.whatsapp_contact_name, null);
});

test('require_registered_recipient omitted never attempts a contact name lookup', async () => {
  const client = fakeClient();
  client.getContactById = async () => {
    throw new Error('should not be called for the normal reply path');
  };

  const result = await sendTextMessage(basePayload(client));

  assert.equal(result.whatsapp_contact_name, null);
});
