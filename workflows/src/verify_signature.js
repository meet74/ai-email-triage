// Slack request signing, v0 scheme. Runs before anything else in the handler.
// Needs NODE_FUNCTION_ALLOW_BUILTIN=crypto and SLACK_SIGNING_SECRET in n8n's environment,
// plus N8N_BLOCK_ENV_ACCESS_IN_NODE=false so the secret can be read here.
const crypto = require('crypto');
const MAX_AGE_SECONDS = 300;

const item = $input.first();
const headers = item.json.headers || {};
const timestamp = headers['x-slack-request-timestamp'] || '';
const signature = headers['x-slack-signature'] || '';
const secret = $env.SLACK_SIGNING_SECRET || '';

const fail = (reason) => [{ json: { valid: false, reason } }];
if (!secret) return fail('SLACK_SIGNING_SECRET is not set');
if (!timestamp || !signature) return fail('missing signature headers');
if (!/^\d+$/.test(timestamp)) return fail('bad timestamp');
const now = $now ? Math.floor($now.toSeconds()) : Math.floor(Date.now() / 1000);
if (Math.abs(now - Number(timestamp)) > MAX_AGE_SECONDS) return fail('stale timestamp');

// The signature covers the exact bytes Slack sent, so use the raw body, not the parsed one.
const raw = (await this.helpers.getBinaryDataBuffer(0, 'data')).toString('utf8');
const expected = 'v0=' + crypto.createHmac('sha256', secret).update(`v0:${timestamp}:${raw}`).digest('hex');
const a = Buffer.from(expected);
const b = Buffer.from(signature);
if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return fail('signature mismatch');

let payload;
try {
  payload = JSON.parse(new URLSearchParams(raw).get('payload'));
} catch (e) {
  return fail('payload is not valid JSON');
}
return [{ json: { valid: true, payload } }];
