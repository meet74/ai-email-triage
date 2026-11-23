// Runs the Code-node sources from workflows/src outside n8n, with the globals n8n provides stubbed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHmac } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (name) => readFileSync(path.join(here, '..', '..', 'workflows', 'src', name), 'utf8');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const require = createRequire(import.meta.url);

async function run(file, globals, self = {}) {
  const fn = new AsyncFunction('$input', '$env', '$now', '$', 'require', src(file));
  return fn.call(self, globals.input, globals.env || {}, globals.now, globals.ref, require);
}

const single = (json) => ({ item: { json }, first: () => ({ json }) });

test('normalise strips quoted history and signature, keeps forwarded text', async () => {
  const gmail = {
    id: '18c4f2ab9d3e1f07', threadId: 't1',
    from: { value: [{ address: 'dana@example.com', name: 'Dana Ortiz' }], text: 'Dana Ortiz <dana@example.com>' },
    subject: 'Re: tent poles',
    text: 'Thanks, works now.\n\nDana\n\nSent from my iPhone\n\nOn Tue, Nov 17, 2026 at 3:14 PM Support <s@example.com> wrote:\n> try rotating it',
  };
  const out = (await run('normalise.js', { input: single(gmail) })).json;
  assert.equal(out.body, 'Thanks, works now.\n\nDana');
  assert.match(out.thread[0], /try rotating/);
  assert.equal(out.from, 'Dana Ortiz <dana@example.com>');
  assert.equal(out.from_address, 'dana@example.com');
  assert.equal(out.thread_id, 't1');
  assert.match(out.ticket_id, /^T-\d{8}-[0-9A-F]{6}$/);

  const fwd = { id: 'abc123', from: 'Greg <greg@example.com>', subject: 'Fwd', text: 'Please handle.\n\n---------- Forwarded message ---------\nFrom: A\nOne section bent.' };
  assert.match((await run('normalise.js', { input: single(fwd) })).json.body, /One section bent/);
});

test('normalise detects language and falls back to html', async () => {
  const fr = { id: 'x1', from: 'a@example.com', subject: 'Commande', text: 'Bonjour, ma commande n\'est pas arrivée et je voudrais un suivi merci' };
  assert.equal((await run('normalise.js', { input: single(fr) })).json.language_hint, 'fr');
  const html = { id: 'x2', from: 'a@example.com', subject: 's', html: '<p>Hello&nbsp;there</p><div>Where is my order?</div>' };
  assert.match((await run('normalise.js', { input: single(html) })).json.body, /Where is my order\?/);
});

const SECRET = 'test-signing-secret';
const NOW = 1_800_000_000;
const sign = (ts, body, secret = SECRET) => 'v0=' + createHmac('sha256', secret).update(`v0:${ts}:${body}`).digest('hex');

function verifyRun(raw, headers, secret = SECRET, now = NOW) {
  const self = { helpers: { getBinaryDataBuffer: async () => Buffer.from(raw) } };
  return run('verify_signature.js', {
    input: { first: () => ({ json: { headers } }) },
    env: { SLACK_SIGNING_SECRET: secret },
    now: { toSeconds: () => now },
  }, self);
}

const payload = { type: 'block_actions', user: { username: 'sam' }, actions: [{ action_id: 'approve_reply', value: 'T-1' }] };
const raw = 'payload=' + encodeURIComponent(JSON.stringify(payload));

test('signature accepted, payload parsed', async () => {
  const [r] = await verifyRun(raw, { 'x-slack-request-timestamp': String(NOW), 'x-slack-signature': sign(NOW, raw) });
  assert.equal(r.json.valid, true);
  assert.equal(r.json.payload.actions[0].value, 'T-1');
});

test('signature matches the Python reference implementation', async () => {
  // same vector as tests/test_slack.py::test_known_vector
  const expected = 'v0=' + createHmac('sha256', '8f742231b10e8888abcd99yyyzzz85a5').update('v0:1531420618:token=xyzz0WbapA4vBCDEFasx0q6G').digest('hex');
  assert.equal(sign(1531420618, 'token=xyzz0WbapA4vBCDEFasx0q6G', '8f742231b10e8888abcd99yyyzzz85a5'), expected);
});

test('bad signature, tampered body, stale timestamp, missing secret are rejected', async () => {
  const ok = { 'x-slack-request-timestamp': String(NOW), 'x-slack-signature': sign(NOW, raw) };
  assert.equal((await verifyRun(raw, { ...ok, 'x-slack-signature': sign(NOW, raw, 'other') }))[0].json.valid, false);
  assert.equal((await verifyRun(raw + 'x', ok))[0].json.valid, false);
  assert.equal((await verifyRun(raw, ok, SECRET, NOW + 301))[0].json.reason, 'stale timestamp');
  assert.equal((await verifyRun(raw, ok, ''))[0].json.valid, false);
  assert.equal((await verifyRun(raw, {}))[0].json.valid, false);
  assert.equal((await verifyRun(raw, { ...ok, 'x-slack-signature': 'v0=short' }))[0].json.valid, false);
});

test('parse interaction maps buttons, modal submit, and rejects odd ticket ids', async () => {
  const p = (payload) => run('parse_interaction.js', { input: single({ payload }) }).then((r) => r.json);
  assert.equal((await p(payload)).kind, 'approve');
  assert.equal((await p({ ...payload, actions: [{ action_id: 'reject_reply', value: 'T-2' }] })).kind, 'reject');
  assert.equal((await p({ ...payload, actions: [{ action_id: 'edit_reply', value: 'T-3' }] })).kind, 'edit');
  assert.equal((await p({ ...payload, actions: [{ action_id: 'approve_reply', value: "T-1'; drop" }] })).kind, 'ignore');
  const view = { type: 'view_submission', user: { id: 'U1' }, view: { callback_id: 'edit_reply_submit', private_metadata: 'T-9',
    state: { values: { draft_block: { draft_input: { value: 'Edited text' } } } } } };
  const s = await p(view);
  assert.deepEqual([s.kind, s.ticket_id, s.edited_text], ['submit_edit', 'T-9', 'Edited text']);
  view.view.state.values.draft_block.draft_input.value = '  ';
  assert.equal((await p(view)).kind, 'ignore');
});
