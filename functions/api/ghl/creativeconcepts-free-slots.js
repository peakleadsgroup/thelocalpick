/**
 * Proxy to Go High Level "Get Free Slots" for Creative Concepts calendar.
 * Secret: CreativeConceptsGHLAPI (Cloudflare Pages env).
 * @see https://marketplace.gohighlevel.com/docs/ghl/calendars/get-slots
 */
const CALENDAR_ID = 'JA9Hs9cmV6uU9fXaQS9y';
const GHL_BASE = 'https://services.leadconnectorhq.com';

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method !== 'GET') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  const apiKey = env.CreativeConceptsGHLAPI;
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: 'CreativeConceptsGHLAPI secret not configured' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const url = new URL(request.url);
  const now = Date.now();
  const defaultEnd = now + 14 * 24 * 60 * 60 * 1000;

  let startDate = url.searchParams.get('startDate');
  let endDate = url.searchParams.get('endDate');
  const timezone = url.searchParams.get('timezone');

  if (!startDate) startDate = String(now);
  if (!endDate) endDate = String(defaultEnd);

  const qs = new URLSearchParams({ startDate, endDate });
  if (timezone) qs.set('timezone', timezone);

  const ghlUrl = `${GHL_BASE}/calendars/${CALENDAR_ID}/free-slots?${qs}`;

  try {
    const res = await fetch(ghlUrl, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Version: '2021-04-15',
        Accept: 'application/json',
      },
    });

    const body = await res.arrayBuffer();
    return new Response(body, {
      status: res.status,
      statusText: res.statusText,
      headers: {
        'Content-Type': res.headers.get('Content-Type') || 'application/json',
      },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: 'GHL proxy error', message: String(err.message) }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    );
  }
}
