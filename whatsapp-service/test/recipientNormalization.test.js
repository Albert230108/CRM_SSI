const test = require('node:test');
const assert = require('node:assert/strict');

const { sendTextMessage } = require('../src/whatsappClient');
const { whatsappClientId } = require('../src/config');

function fakeClient() {
  const calls = [];
  let counter = 0;
  return {
    calls,
    sendMessage: async (chatId, content) => {
      counter += 1;
      calls.push({ chatId, content });
      return { id: { _serialized: `wamid.sent-${counter}` } };
    },
  };
}

function basePayload(client, overrides = {}) {
  return {
    message: 'Hi',
    tenant_id: 7,
    external_account_id: whatsappClientId,
    whatsapp_endpoint_id: null,
    clientOverride: client,
    readyOverride: true,
    ...overrides,
  };
}

test('a leading "00" international dialing prefix is stripped, not sent as part of the WhatsApp id', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { to: '00393455878277' }));

  assert.equal(client.calls[0].chatId, '393455878277@c.us');
  assert.equal(result.whatsapp_chat_id, '393455878277@c.us');
});

test('a "+" prefixed number is unaffected (already produces the correct digits)', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { to: '+393455878277' }));

  assert.equal(result.whatsapp_chat_id, '393455878277@c.us');
});

test('a number with no international prefix is unaffected', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { to: '31612345678' }));

  assert.equal(result.whatsapp_chat_id, '31612345678@c.us');
});

test('an already-suffixed chat id is passed through untouched, even if it starts with 00', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { to: '0012345@lid' }));

  assert.equal(result.whatsapp_chat_id, '0012345@lid');
});

function fakeClientResolvingToLid(lidChatId) {
  const calls = [];
  let counter = 0;
  return {
    calls,
    sendMessage: async (chatId, content) => {
      counter += 1;
      calls.push({ chatId, content });
      return { id: { _serialized: `false_${lidChatId}_wamid-${counter}`, remote: lidChatId } };
    },
  };
}

test('when WhatsApp resolves the send to a different (@lid) chat than requested, the resolved id wins', async () => {
  const client = fakeClientResolvingToLid('223845239795830@lid');

  const result = await sendTextMessage(basePayload(client, { to: '+393455878277' }));

  // We asked to send to the plain phone number, but the chat WhatsApp actually filed the
  // message under (and where future replies will arrive) is the @lid identity - that must be
  // what gets returned and persisted, not our best-guess request id.
  assert.equal(client.calls[0].chatId, '393455878277@c.us');
  assert.equal(result.whatsapp_chat_id, '223845239795830@lid');
});
