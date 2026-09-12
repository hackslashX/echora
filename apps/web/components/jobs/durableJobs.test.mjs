// Run: node --test apps/web/components/jobs/durableJobs.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';
const source = stripTypeScriptTypes(readFileSync(new URL('./durableJobs.ts', import.meta.url), 'utf8'));
const { discoverJob, watchJob, isActiveJob, isTerminalJob, jobPresentation } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const job = status => ({ id: 'job', job_id: 'job', status, phase: status, completed: 0, total: 1 });
const response = body => ({ ok: true, json: async () => body });
test('all active and terminal states are classified', () => {
  for (const status of ['queued', 'running', 'waiting']) assert.ok(isActiveJob(job(status)));
  for (const status of ['complete', 'partial', 'failed', 'cancelled']) { assert.ok(isTerminalJob(job(status))); assert.ok(!isActiveJob(job(status))); }
});
test('discovery scopes the connection, excludes curation and children, then falls back to latest history', async t => {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async url => { urls.push(url); return response({ jobs: urls.length === 1 ? [{ ...job('running'), kind: 'curation_refresh' }, { ...job('running'), parent_id: 'parent' }] : [job('partial')] }); });
  assert.equal((await discoverJob('connection', new AbortController().signal)).status, 'partial');
  assert.deepEqual(urls, ['/analysis/jobs?connection_id=connection&active_only=true', '/analysis/jobs?connection_id=connection&active_only=false']);
});
test('active discovery does not request history', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return response({ jobs: [job('waiting')] }); });
  assert.equal((await discoverJob('connection', new AbortController().signal)).status, 'waiting');
  assert.equal(calls, 1);
});
test('poll errors remain visible and retry until terminal', async t => {
  let calls = 0; const errors = [];
  t.mock.method(globalThis, 'fetch', async () => { calls++; if (calls === 1) throw new Error('offline'); return response(job(calls === 2 ? 'waiting' : 'cancelled')); });
  let stop;
  await new Promise(resolve => { stop = watchJob('connection', 'job', value => { if (value.status === 'cancelled') resolve(); }, error => errors.push(error), 1); });
  stop(); assert.equal(calls, 3); assert.match(errors[0], /Connection error.*Retrying/); assert.equal(errors.at(-1), '');
});
test('cleanup aborts requests and ignores late results', async t => {
  let finish; let signal; let received = false;
  t.mock.method(globalThis, 'fetch', (_url, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); });
  const stop = watchJob('connection', 'job', () => { received = true; }, () => {});
  stop(); assert.equal(signal.aborted, true); finish(response(job('complete')));
  await new Promise(resolve => setImmediate(resolve)); assert.equal(received, false);
});
test('library job surfaces and hook expose no cancellation action', () => {
  // Source-level contract guard: the frontend suite has no DOM rendering harness.
  for (const path of ['../sync/SyncLibrary.tsx', '../SetupWizard.tsx', './useDurableJob.ts']) {
    const source = readFileSync(new URL(path, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /cancel/i, `${path} must not expose job cancellation`);
  }
});
test('historical cancelled jobs stop polling without scheduling another request', async t => {
  let calls = 0;
  const timers = [];
  t.mock.method(globalThis, 'setTimeout', (...args) => { timers.push(args); return 0; });
  t.mock.method(globalThis, 'fetch', async () => { calls++; return response(job('cancelled')); });
  let received;
  const stop = watchJob('connection', 'job', value => { received = value; }, () => {});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(received.status, 'cancelled');
  assert.equal(calls, 1);
  assert.equal(timers.length, 0);
  stop();
});

test('cancelled history does not reopen on entry', async t => {
  t.mock.method(globalThis, 'fetch', async url => response({ jobs: url.includes('active_only=true') ? [] : [job('cancelled')] }));
  assert.equal(await discoverJob('connection', new AbortController().signal), null);
});
test('legacy cancelled batch counters do not imply successful completion', () => {
  const result = jobPresentation({ ...job('cancelled'), unit: 'batches', completed: 30, total: 30,
    message: 'Processed 30 of 30 batches', summary: { complete: 1, cancelled: 29, total: 30, completed: 30 } });
  assert.equal(result.showPercent, false);
  assert.equal(result.percent, 3);
  assert.equal(result.message, '1 of 30 batches successful');
  assert.deepEqual(result.summary, ['1 successful', '29 cancelled']);
});
test('batch failures are distinct from successes', () => {
  const result = jobPresentation({ ...job('partial'), unit: 'batches', completed: 3, total: 3,
    summary: { complete: 1, partial: 1, failed: 1 } });
  assert.equal(result.showPercent, false);
  assert.deepEqual(result.summary, ['1 successful', '1 partially successful', '1 failed']);
});
test('song metrics are only displayed when actually reported', () => {
  assert.deepEqual(jobPresentation(job('complete')).summary, []);
  assert.deepEqual(jobPresentation({ ...job('complete'), summary: { inserted: 2, failed: 0 } }).summary,
    ['2 new', '0 failed']);
});
