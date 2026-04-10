/**
 * Home Pro MI — availability via Make.com webhook (zip-scoped).
 *
 * URL: https://YOUR_DOMAIN/api/availability/homepromi?zip=49534
 * Query:
 *   - zip (required) — forwarded to Make as ?zip=
 *   - startDate, endDate — Unix ms (optional; echoed in response range for the funnel)
 *
 * Make returns an array of day rows (SDate, TMS_Descr1–6, T1–T6). A slot is offered when Tn > 0
 * and TMS_Descr is non-empty. Output matches the funnel calendar: slots["YYYY-MM-DD"] = [{ start, label }].
 */
const MAKE_WEBHOOK = 'https://hook.us2.make.com/dn7kjdagrc6goimlozfan1zpt2dp9lvs';

const PARTNER_SLUG = 'homepromi';
/** Michigan — used to interpret SDate + time labels into UTC ISO instants */
const DEFAULT_TIMEZONE = 'America/Detroit';

const DATE_KEY = /^\d{4}-\d{2}-\d{2}$/;
const SLOT_INDEXES = [1, 2, 3, 4, 5, 6];

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

/**
 * @param {number} ms
 * @param {string} timeZone
 */
function partsForTz(ms, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
    hourCycle: 'h23',
  }).formatToParts(new Date(ms));
  const o = { year: 0, month: 0, day: 0, hour: 0, minute: 0 };
  for (const p of parts) {
    if (p.type === 'year') o.year = Number(p.value);
    if (p.type === 'month') o.month = Number(p.value);
    if (p.type === 'day') o.day = Number(p.value);
    if (p.type === 'hour') o.hour = Number(p.value);
    if (p.type === 'minute') o.minute = Number(p.value);
  }
  return o;
}

/**
 * @param {{ year: number, month: number, day: number, hour: number, minute: number }} a
 * @param {{ year: number, month: number, day: number, hour: number, minute: number }} b
 */
function cmpWallParts(a, b) {
  if (a.year !== b.year) return a.year - b.year;
  if (a.month !== b.month) return a.month - b.month;
  if (a.day !== b.day) return a.day - b.day;
  if (a.hour !== b.hour) return a.hour - b.hour;
  return a.minute - b.minute;
}

/**
 * UTC ms such that `timeZone` wall clock reads (year, month, day, hour, minute).
 * @param {number} year
 * @param {number} month 1–12
 * @param {number} day
 * @param {number} hour 0–23
 * @param {number} minute 0–59
 * @param {string} timeZone
 */
function localWallTimeToUtcMs(year, month, day, hour, minute, timeZone) {
  const target = { year, month, day, hour, minute };
  let lo = Date.UTC(year, month - 1, day - 1, 12, 0, 0);
  let hi = Date.UTC(year, month - 1, day + 1, 12, 0, 0);
  for (let i = 0; i < 64; i++) {
    const mid = (lo + hi) / 2;
    const a = partsForTz(mid, timeZone);
    const c = cmpWallParts(a, target);
    if (c === 0) return Math.round(mid);
    if (c < 0) lo = mid;
    else hi = mid;
  }
  return Math.round((lo + hi) / 2);
}

/** @param {unknown} sDate */
function parseSDateYmd(sDate) {
  const s = String(sDate ?? '');
  const datePart = s.split('T')[0];
  const m = datePart.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  return {
    ymd: datePart,
    y: Number(m[1]),
    mo: Number(m[2]),
    d: Number(m[3]),
  };
}

/** @param {string} descr e.g. "10am", "1pm" */
function parseTimeDescr(descr) {
  const s = String(descr).trim().toLowerCase();
  if (!s) return null;
  const match = s.match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$/);
  if (!match) return null;
  let h = Number(match[1]);
  const min = match[2] ? Number(match[2]) : 0;
  const ap = match[3];
  if (ap === 'pm' && h !== 12) h += 12;
  if (ap === 'am' && h === 12) h = 0;
  return { hour: h, minute: min };
}

/**
 * @param {unknown} row
 * @returns {boolean}
 */
function looksLikeHomepromiDayRow(row) {
  return (
    row != null &&
    typeof row === 'object' &&
    !Array.isArray(row) &&
    'SDate' in /** @type {object} */ (row) &&
    'TMS_Descr1' in /** @type {object} */ (row)
  );
}

/**
 * @param {unknown[]} rows
 * @param {string} timeZone
 * @returns {Record<string, { start: string, label: string }[]>}
 */
function homepromiRowsToSlots(rows, timeZone) {
  /** @type {Record<string, { start: string, label: string }[]>} */
  const slots = {};
  for (const row of rows) {
    if (!looksLikeHomepromiDayRow(row)) continue;
    const r = /** @type {Record<string, unknown>} */ (row);
    const day = parseSDateYmd(r.SDate);
    if (!day) continue;

    /** @type {{ start: string, label: string }[]} */
    const daySlots = [];
    for (const i of SLOT_INDEXES) {
      const descr = r[`TMS_Descr${i}`];
      const t = r[`T${i}`];
      if (typeof descr !== 'string' || !descr.trim()) continue;
      if (typeof t !== 'number' || t <= 0) continue;
      const tparts = parseTimeDescr(descr);
      if (!tparts) continue;

      const utcMs = localWallTimeToUtcMs(day.y, day.mo, day.d, tparts.hour, tparts.minute, timeZone);
      const start = new Date(utcMs).toISOString();
      const label = new Date(utcMs).toLocaleString('en-US', {
        timeZone,
        weekday: 'short',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      });
      daySlots.push({ start, label });
    }

    daySlots.sort((a, b) => a.start.localeCompare(b.start));
    if (daySlots.length > 0) slots[day.ymd] = daySlots;
  }
  return slots;
}

/**
 * @param {unknown} body
 * @returns {{ slots: Record<string, { start: string, label: string }[]>, timezone: string }}
 */
function slotsFromMakeBody(body) {
  if (body == null) {
    return { slots: {}, timezone: DEFAULT_TIMEZONE };
  }

  if (Array.isArray(body)) {
    if (body.length > 0 && looksLikeHomepromiDayRow(body[0])) {
      return { slots: homepromiRowsToSlots(body, DEFAULT_TIMEZONE), timezone: DEFAULT_TIMEZONE };
    }
    return { slots: {}, timezone: DEFAULT_TIMEZONE };
  }

  if (typeof body === 'object') {
    const o = /** @type {Record<string, unknown>} */ (body);
    if (o.slots && typeof o.slots === 'object' && !Array.isArray(o.slots)) {
      const tz =
        typeof o.timezone === 'string' && o.timezone.trim() ? o.timezone.trim() : DEFAULT_TIMEZONE;
      return { slots: /** @type {Record<string, { start: string, label: string }[]>} */ (o.slots), timezone: tz };
    }
    const dateKeys = Object.keys(o).filter((k) => DATE_KEY.test(k));
    if (dateKeys.length > 0) {
      const slots = {};
      for (const k of dateKeys) {
        const v = o[k];
        slots[k] = Array.isArray(v) ? /** @type {{ start: string, label: string }[]} */ (v) : [];
      }
      const tz =
        typeof o.timezone === 'string' && o.timezone.trim() ? o.timezone.trim() : DEFAULT_TIMEZONE;
      return { slots, timezone: tz };
    }
    const nested = o.data;
    if (nested && typeof nested === 'object') {
      return slotsFromMakeBody(nested);
    }
  }

  return { slots: {}, timezone: DEFAULT_TIMEZONE };
}

export async function onRequest(context) {
  const { request } = context;

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
    return jsonResponse({ schemaVersion: 1, partner: PARTNER_SLUG, error: 'Method not allowed', code: 'METHOD' }, 405);
  }

  const url = new URL(request.url);
  const zipRaw = url.searchParams.get('zip');
  const zip = zipRaw != null ? String(zipRaw).trim() : '';
  if (!zip) {
    return jsonResponse(
      {
        schemaVersion: 1,
        partner: PARTNER_SLUG,
        error: 'Query parameter "zip" is required',
        code: 'ZIP_REQUIRED',
      },
      400
    );
  }

  const now = Date.now();
  const defaultEnd = now + 14 * 24 * 60 * 60 * 1000;
  let startMs = Number(url.searchParams.get('startDate'));
  let endMs = Number(url.searchParams.get('endDate'));
  if (!Number.isFinite(startMs)) startMs = now;
  if (!Number.isFinite(endMs)) endMs = defaultEnd;

  const makeUrl = new URL(MAKE_WEBHOOK);
  makeUrl.searchParams.set('zip', zip);

  let upstreamText;
  try {
    const res = await fetch(makeUrl.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
    upstreamText = await res.text();
    if (!res.ok) {
      return jsonResponse(
        {
          schemaVersion: 1,
          partner: PARTNER_SLUG,
          error: `Make webhook returned ${res.status}`,
          code: 'UPSTREAM',
        },
        res.status >= 400 && res.status < 600 ? res.status : 502
      );
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return jsonResponse(
      {
        schemaVersion: 1,
        partner: PARTNER_SLUG,
        error: `Failed to reach Make webhook: ${msg}`,
        code: 'UPSTREAM',
      },
      502
    );
  }

  let parsed;
  try {
    parsed = JSON.parse(upstreamText);
  } catch {
    return jsonResponse(
      {
        schemaVersion: 1,
        partner: PARTNER_SLUG,
        error: 'Make webhook did not return valid JSON',
        code: 'UPSTREAM',
      },
      502
    );
  }

  const { slots, timezone } = slotsFromMakeBody(parsed);

  return jsonResponse({
    schemaVersion: 1,
    partner: PARTNER_SLUG,
    timezone,
    range: { startMs, endMs },
    slots,
  });
}
