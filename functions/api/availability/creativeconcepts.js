/**
 * Creative Concepts — GHL calendar availability (JSON for landing pages).
 *
 * URL: https://YOUR_DOMAIN/api/availability/creativeconcepts
 * Query: startDate & endDate = Unix ms (optional; default now → +14d), timezone (optional).
 *
 * Response (200):
 * {
 *   "schemaVersion": 1,
 *   "partner": "creativeconcepts",
 *   "timezone": "America/New_York",
 *   "range": { "startMs": number, "endMs": number },
 *   "slots": { "YYYY-MM-DD": [{ "start": "<ISO8601>", "label": "<display>" }] }
 * }
 *
 * GHL: https://marketplace.gohighlevel.com/docs/ghl/calendars/get-slots
 */
const GHL_BASE = 'https://services.leadconnectorhq.com';

const PARTNER_SLUG = 'creativeconcepts';
const CALENDAR_ID = 'JA9Hs9cmV6uU9fXaQS9y';
const DEFAULT_TIMEZONE = 'America/New_York';

/** @param {{ CreativeConceptsGHLAPI?: string }} env */
function getApiToken(env) {
  return env.CreativeConceptsGHLAPI;
}

const DATE_KEY = /^\d{4}-\d{2}-\d{2}$/;

function jsonResponse(data, status = 200, extraHeaders = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'Cache-Control': 'public, max-age=60',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    ...extraHeaders,
  };
  return new Response(JSON.stringify(data), { status, headers });
}

/** @param {Record<string, unknown>} obj */
function extractGhlDateMap(obj) {
  const top = {};
  for (const [k, v] of Object.entries(obj)) {
    if (DATE_KEY.test(k)) top[k] = v;
  }
  if (Object.keys(top).length) return top;
  const nestedKeys = ['slots', 'data', 'freeSlots', 'availability', 'calendar'];
  for (const nk of nestedKeys) {
    const inner = obj[nk];
    if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
      const found = extractGhlDateMap(/** @type {Record<string, unknown>} */ (inner));
      if (Object.keys(found).length) return found;
    }
  }
  return {};
}

/**
 * @param {unknown} item
 * @param {string} timeZone
 * @returns {{ start: string, label: string } | null}
 */
function slotFromItem(item, timeZone) {
  if (item == null) return null;
  let d = null;
  if (typeof item === 'string') {
    const t = Date.parse(item);
    if (!Number.isNaN(t)) d = new Date(t);
  } else if (typeof item === 'object') {
    const o = /** @type {Record<string, unknown>} */ (item);
    const cand = o.startTime ?? o.time ?? o.slotTime ?? o.datetime ?? o.date ?? o.start;
    if (typeof cand === 'string') {
      const t = Date.parse(cand);
      if (!Number.isNaN(t)) d = new Date(t);
    } else if (typeof cand === 'number') {
      d = new Date(cand);
    }
  }
  if (!d || Number.isNaN(d.getTime())) return null;
  const start = d.toISOString();
  const label = d.toLocaleString('en-US', {
    timeZone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
  return { start, label };
}

/** @param {unknown} value @param {string} timeZone */
function normalizeDay(value, timeZone) {
  const out = [];
  if (value == null) return out;
  let arr = null;
  if (Array.isArray(value)) arr = value;
  else if (typeof value === 'object' && Array.isArray(/** @type {{ slots?: unknown }} */ (value).slots)) {
    arr = /** @type {{ slots: unknown[] }} */ (value).slots;
  }
  if (!arr) return out;
  for (const item of arr) {
    const s = slotFromItem(item, timeZone);
    if (s) out.push(s);
  }
  return out;
}

/**
 * @param {string} apiKey
 * @param {string} calendarId
 * @param {string} startDate
 * @param {string} endDate
 * @param {string} [timezone]
 */
async function fetchGhlFreeSlots(apiKey, calendarId, startDate, endDate, timezone) {
  const qs = new URLSearchParams({ startDate, endDate });
  if (timezone) qs.set('timezone', timezone);
  const ghlUrl = `${GHL_BASE}/calendars/${calendarId}/free-slots?${qs}`;
  const res = await fetch(ghlUrl, {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Version: '2021-04-15',
      Accept: 'application/json',
    },
  });
  const text = await res.text();
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, status: res.status, error: 'Invalid JSON from GHL', body: text.slice(0, 500) };
  }
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: raw.message || raw.error || res.statusText,
      traceId: raw.traceId,
    };
  }
  return { ok: true, raw };
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '86400',
      },
    });
  }

  if (request.method !== 'GET') {
    return jsonResponse({ schemaVersion: 1, error: 'Method not allowed', code: 'METHOD' }, 405);
  }

  const url = new URL(request.url);
  const now = Date.now();
  const defaultEnd = now + 14 * 24 * 60 * 60 * 1000;

  let startDate = url.searchParams.get('startDate');
  let endDate = url.searchParams.get('endDate');
  const timezone = url.searchParams.get('timezone') || DEFAULT_TIMEZONE;

  if (!startDate) startDate = String(now);
  if (!endDate) endDate = String(defaultEnd);

  const apiKey = getApiToken(env);
  if (!apiKey) {
    return jsonResponse(
      {
        schemaVersion: 1,
        error: 'Partner API token not configured in environment',
        code: 'CONFIG',
      },
      500
    );
  }

  const ghl = await fetchGhlFreeSlots(apiKey, CALENDAR_ID, startDate, endDate, timezone);
  if (!ghl.ok) {
    return jsonResponse(
      {
        schemaVersion: 1,
        partner: PARTNER_SLUG,
        error: typeof ghl.error === 'string' ? ghl.error : JSON.stringify(ghl.error),
        code: 'UPSTREAM',
        traceId: ghl.traceId,
      },
      ghl.status >= 400 && ghl.status < 600 ? ghl.status : 502
    );
  }

  const dateMap = extractGhlDateMap(/** @type {Record<string, unknown>} */ (ghl.raw));
  /** @type {Record<string, { start: string, label: string }[]>} */
  const slots = {};
  for (const [date, value] of Object.entries(dateMap)) {
    slots[date] = normalizeDay(value, timezone);
  }

  return jsonResponse({
    schemaVersion: 1,
    partner: PARTNER_SLUG,
    timezone,
    range: { startMs: Number(startDate), endMs: Number(endDate) },
    slots,
  });
}
