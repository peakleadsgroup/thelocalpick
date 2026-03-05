/**
 * Cloudflare Pages Function: Airtable API proxy
 * Forwards requests to Airtable using the Airtable secret from Cloudflare env.
 * The secret must be named "Airtable" in your project's Variables and Secrets.
 */
export async function onRequest(context) {
  const { request, env } = context;
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

  const init = {
    method: request.method,
    headers,
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
  }

  try {
    const response = await fetch(airtableUrl, init);
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
