function firstNonEmpty(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && String(value).trim() !== "") {
      return String(value).trim();
    }
  }
  return null;
}

function normalizeWhatsAppPhone(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const lowered = raw.toLowerCase();
  if (lowered.endsWith("@c.us")) {
    const digits = lowered.split("@", 1)[0].replace(/\D+/g, "");
    if (digits.length < 7 || /^0+$/.test(digits)) {
      return null;
    }
    return digits;
  }
  if (lowered.includes("@")) {
    return null;
  }
  const digits = raw.replace(/\D+/g, "");
  if (digits.length < 7 || /^0+$/.test(digits)) {
    return null;
  }
  return digits || null;
}

function normalizeWhatsAppChatId(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized || null;
}

function getCanonicalWhatsAppIdentity(input = {}, { direction = null } = {}) {
  const resolvedDirection = String(direction || input.direction || "").trim().toLowerCase();
  const rawChatId = normalizeWhatsAppChatId(
    firstNonEmpty(
      input.whatsapp_raw_chat_id,
      input.whatsapp_chat_id,
      input.chat_id,
      input.external_chat_namespace,
      input.sender_raw,
      input.sender,
      input.from,
      input.recipient,
      input.to,
    ),
  );

  const isGroup = Boolean(input.is_group || (rawChatId && rawChatId.endsWith("@g.us")));
  const phoneCandidates = [
    input.whatsapp_normalized_phone,
    input.sender_normalized,
    input.recipient_normalized,
    resolvedDirection === "outbound" ? firstNonEmpty(input.recipient, input.to) : firstNonEmpty(input.sender, input.from),
    input.wa_id,
    input.phone_number,
    input.whatsapp_chat_id,
    input.whatsapp_raw_chat_id,
    input.sender_raw,
    input.sender,
    input.from,
    input.recipient,
    input.to,
  ];

  let normalizedPhone = null;
  for (const candidate of phoneCandidates) {
    normalizedPhone = normalizeWhatsAppPhone(candidate);
    if (normalizedPhone) {
      break;
    }
  }

  if (!normalizedPhone && rawChatId && !isGroup && rawChatId.endsWith("@c.us")) {
    normalizedPhone = normalizeWhatsAppPhone(rawChatId) || null;
  }

  let canonicalChatId = normalizeWhatsAppChatId(
    firstNonEmpty(
      input.whatsapp_identity_key,
      normalizedPhone,
      rawChatId,
    ),
  );
  if (isGroup && rawChatId) {
    canonicalChatId = rawChatId;
  }

  return {
    rawChatId,
    normalizedPhone,
    canonicalChatId,
    isGroup,
  };
}

function buildWhatsAppIdentityCandidates(identity) {
  if (!identity) {
    return [];
  }
  const candidates = [];
  const seen = new Set();
  for (const value of [identity.canonicalChatId, identity.rawChatId, identity.normalizedPhone]) {
    if (!value) {
      continue;
    }
    const normalized = String(value).trim().toLowerCase();
    if (normalized && !seen.has(normalized)) {
      seen.add(normalized);
      candidates.push(normalized);
    }
  }
  return candidates;
}

module.exports = {
  buildWhatsAppIdentityCandidates,
  getCanonicalWhatsAppIdentity,
  normalizeWhatsAppChatId,
  normalizeWhatsAppPhone,
};
