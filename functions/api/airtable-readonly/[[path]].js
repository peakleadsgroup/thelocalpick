/**
 * Cloudflare Pages Function: READ-ONLY Airtable API proxy for dry-run pages.
 * Only GET/HEAD are forwarded. POST/PATCH/PUT/DELETE are rejected with 403.
 * Secret name: "Airtable" (same as live proxy).
 */
export async function onRequest(context) {
  const { request, env } = context;
  const method = String(request.method || 'GET').toUpperCase();

  if (method !== 'GET' && method !== 'HEAD') {
    return new Response(
      JSON.stringify({
        error: 'DRY_RUN_READ_ONLY_PROXY',
        message: 'airtable-readonly proxy allows GET/HEAD only',
        method,
      }),
      { status: 403, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const apiKey = env.Airtable;
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: 'Airtable secret not configured' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const url = new URL(request.url);
  const pathSegments = context.params.path;
  const path = Array.isArray(pathSegments) ? pathSegments.join('/') : (pathSegments || '');
  const airtableUrl = `https://api.airtable.com/${path}${url.search}`;

  const headers = new Headers(request.headers);
  headers.set('Authorization', `Bearer ${apiKey}`);
  headers.set('Content-Type', 'application/json');
  headers.delete('Host');

  try {
    const response = await fetch(airtableUrl, { method, headers });
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: 'Airtable proxy error', message: String(err.message) }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    );
  }
}
