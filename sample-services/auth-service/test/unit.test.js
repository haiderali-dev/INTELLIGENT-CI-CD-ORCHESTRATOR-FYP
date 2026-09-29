/**
 * auth-service unit suite. Target runtime about 6 seconds (catalog: approx_seconds 6).
 *
 * The sleeps are deliberate. The experiment needs jobs whose durations differ predictably: the
 * execution-time factor T in the report's Algorithm 1 is normalised across the queue, so if every
 * job took the same time T would be constant and a third of the scoring formula would be
 * untestable. auth-service is the short one, payment-service the long one.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setTimeout as sleep } from 'node:timers/promises';

import { handle, reset, SERVICE_NAME } from '../src/app.js';

const STEP_MS = 850;

/** Drive handle() without binding a port, collecting the response. */
function call(method, path) {
  return new Promise((resolve) => {
    const chunks = [];
    const res = {
      writeHead(status, headers) {
        this.statusCode = status;
        this.headers = headers;
      },
      end(body) {
        if (body) chunks.push(body);
        resolve({ status: this.statusCode, body: JSON.parse(chunks.join('')) });
      },
    };
    handle({ method, url: path, headers: { host: 'localhost' } }, res);
  });
}

test('health reports ok', async () => {
  await sleep(STEP_MS);
  const { status, body } = await call('GET', '/health');
  assert.equal(status, 200);
  assert.deepEqual(body, { status: 'ok', service: SERVICE_NAME });
});

test('version exposes the commit', async () => {
  await sleep(STEP_MS);
  const { status, body } = await call('GET', '/version');
  assert.equal(status, 200);
  assert.equal(body.service, SERVICE_NAME);
  // Never asserted to a fixed value: it changes every build, which is the point.
  assert.ok('commit' in body);
});

test('login issues a token', async () => {
  await sleep(STEP_MS);
  reset();
  const { status, body } = await call('POST', '/login?username=alice');
  assert.equal(status, 201);
  assert.ok(body.token.startsWith('tok_'));
  assert.equal(body.username, 'alice');
});

test('login without a username is rejected', async () => {
  await sleep(STEP_MS);
  const { status, body } = await call('POST', '/login');
  assert.equal(status, 400);
  assert.match(body.error, /username/);
});

test('a valid token verifies', async () => {
  await sleep(STEP_MS);
  reset();
  const { body: issued } = await call('POST', '/login?username=bob');
  const { status, body } = await call('GET', `/verify?token=${issued.token}`);
  assert.equal(status, 200);
  assert.equal(body.valid, true);
  assert.equal(body.username, 'bob');
});

test('an unknown token does not verify', async () => {
  await sleep(STEP_MS);
  const { status, body } = await call('GET', '/verify?token=tok_nope');
  assert.equal(status, 401);
  assert.equal(body.valid, false);
});

test('an unknown path is a 404', async () => {
  await sleep(STEP_MS);
  const { status } = await call('GET', '/nope');
  assert.equal(status, 404);
});
