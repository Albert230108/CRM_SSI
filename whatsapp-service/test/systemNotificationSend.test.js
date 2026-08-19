const test = require('node:test');
const assert = require('node:assert/strict');

const { sendSystemMessage } = require('../src/whatsappClient');

function fakeClient() {
  const calls = [];
  let counter = 0;
  return {
    calls,
    sendMessage: async (chatId, content) => {
      counter += 1;
      calls.push({ chatId, content });
      return { id: { _serialized: `wamid.system-${counter}` } };
    },
  };
}

test('sendSystemMessage sends to a raw phone number without tenant context', async () => {
  const client = fakeClient();

  const result = await sendSystemMessage({
    to: '31612345678',
    message: 'You have 2 new notification(s) in CRM_SSI',
    clientOverride: client,
    readyOverride: true,
  });

  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].chatId, '31612345678@c.us');
  assert.equal(client.calls[0].content, 'You have 2 new notification(s) in CRM_SSI');
  assert.equal(result.whatsapp_message_id, 'wamid.system-1');
  assert.equal(result.whatsapp_chat_id, '31612345678@c.us');
});

test('sendSystemMessage preserves an already-suffixed chat id', async () => {
  const client = fakeClient();

  await sendSystemMessage({
    to: '31612345678@c.us',
    message: 'Alert',
    clientOverride: client,
    readyOverride: true,
  });

  assert.equal(client.calls[0].chatId, '31612345678@c.us');
});

test('sendSystemMessage rejects when the client is not ready', async () => {
  await assert.rejects(
    () => sendSystemMessage({ to: '31612345678', message: 'Alert', clientOverride: fakeClient(), readyOverride: false }),
    /not ready/,
  );
});

test('sendSystemMessage rejects an invalid recipient', async () => {
  await assert.rejects(
    () => sendSystemMessage({ to: '', message: 'Alert', clientOverride: fakeClient(), readyOverride: true }),
    /Invalid recipient phone number/,
  );
});

test('sendSystemMessage rejects an empty message', async () => {
  await assert.rejects(
    () => sendSystemMessage({ to: '31612345678', message: '', clientOverride: fakeClient(), readyOverride: true }),
    /missing message/,
  );
});
