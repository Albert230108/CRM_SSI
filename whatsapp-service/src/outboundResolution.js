function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeCorrelationValue(value) {
  const normalized = String(value || "").trim();
  return normalized || null;
}

async function resolveOutboundTenantOwnership({
  messageId,
  chatId,
  identityKey,
  normalizedPhone,
  externalAccountId,
  lookupDurableTenant,
  getMemoryTenantId,
  retryDelaysMs = [0, 100, 250],
}) {
  const normalizedMessageId = normalizeCorrelationValue(messageId);
  const normalizedChatId = normalizeCorrelationValue(chatId);
  const normalizedIdentityKey = normalizeCorrelationValue(identityKey);
  const normalizedNormalizedPhone = normalizeCorrelationValue(normalizedPhone);
  const normalizedExternalAccountId = normalizeCorrelationValue(externalAccountId);

  const durableCandidates = [];
  if (normalizedMessageId) {
    durableCandidates.push({
      strategy: "provider_message_id",
      params: { provider_message_id: normalizedMessageId },
    });
  }
  if (normalizedExternalAccountId) {
    if (normalizedIdentityKey) {
      durableCandidates.push({
        strategy: "identity_key_external_account_id",
        params: {
          whatsapp_identity_key: normalizedIdentityKey,
          external_account_id: normalizedExternalAccountId,
        },
      });
    }
    if (normalizedNormalizedPhone) {
      durableCandidates.push({
        strategy: "normalized_phone_external_account_id",
        params: {
          whatsapp_normalized_phone: normalizedNormalizedPhone,
          external_account_id: normalizedExternalAccountId,
        },
      });
    }
    if (normalizedChatId) {
      durableCandidates.push({
        strategy: "chat_id_external_account_id",
        params: {
          whatsapp_chat_id: normalizedChatId,
          external_account_id: normalizedExternalAccountId,
        },
      });
    }
  }

  for (const candidate of durableCandidates) {
    for (let attempt = 0; attempt < retryDelaysMs.length; attempt += 1) {
      if (attempt > 0) {
        await sleep(retryDelaysMs[attempt]);
      }
      const resolution = await lookupDurableTenant(candidate.params);
      if (resolution && resolution.found && resolution.tenant_id != null) {
        return {
          tenantId: resolution.tenant_id,
          resolutionSource: "durable",
          resolutionStrategy: candidate.strategy,
          matchedValue: candidate.strategy === "provider_message_id" ? normalizedMessageId : candidate.strategy === "identity_key_external_account_id" ? normalizedIdentityKey : candidate.strategy === "normalized_phone_external_account_id" ? normalizedNormalizedPhone : normalizedChatId,
          durableResolution: resolution,
        };
      }
    }
  }

  if (typeof getMemoryTenantId === "function") {
    const memoryTenantId = getMemoryTenantId({
      messageId: normalizedMessageId,
      chatId: normalizedChatId,
      identityKey: normalizedIdentityKey,
      normalizedPhone: normalizedNormalizedPhone,
      externalAccountId: normalizedExternalAccountId,
    });
    if (memoryTenantId != null) {
      return {
        tenantId: memoryTenantId,
        resolutionSource: "memory",
        resolutionStrategy: "memory_fallback",
        matchedValue: normalizedMessageId || normalizedIdentityKey || normalizedNormalizedPhone || normalizedChatId || normalizedExternalAccountId,
      };
    }
  }

  return null;
}

module.exports = {
  resolveOutboundTenantOwnership,
};
