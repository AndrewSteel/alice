// PROJ-113 QA edge-case tests — run: node --test workflows/tests/proj113/
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeEnv, runNode } = require('./harness');

const P2H = 'alice:dms:path_to_hash';
const FOLDERS = [{ id: 14, path: '/mnt/nas/pictures' }];

async function lifecycleCheck(E, item) {
  const [out] = await runNode(E, 'alice-dms-path-worker', 'Code: Lifecycle Check', [item], { 'Execute Workflow Trigger': [{ id: 14 }] });
  return out;
}

test('QA: GraphQL injection via file_hash in a lifecycle message is neutralised', async () => {
  const E = makeEnv();
  const evil = 'sha256:x" } } } { Get { Image { file_path';
  const [parsed] = await runNode(E, 'alice-dms-lifecycle', 'Code: Parse & Validate', [{ message: JSON.stringify({ action: 'delete_file', file_hash: evil, file_path: '/mnt/nas/pictures/a.jpg' }) }]);
  await runNode(E, 'alice-dms-lifecycle', 'Code: Weaviate Find by Hash', [parsed]);
  const q = E.weaviate.calls.filter(c => c[0] === 'POST').map(c => c[2].query);
  assert.ok(q.length > 0);
  for (const s of q) assert.ok(!s.includes('" } } }'), 'quote/braces must be stripped');
});

test('QA: GraphQL injection via file_hash in the path worker self-heal is neutralised', async () => {
  const E = makeEnv();
  await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/a.jpg', file_hash: 'sha256:a"}) { x', file_type: 'jpg' });
  for (const c of E.weaviate.calls) assert.ok(!c[2].query.includes('a"}'));
});

test('QA: unknown lifecycle action is still discarded', async () => {
  const E = makeEnv();
  const out = await runNode(E, 'alice-dms-lifecycle', 'Code: Parse & Validate', [{ message: JSON.stringify({ action: 'drop_all', file_hash: 'sha256:1', file_path: '/x' }) }]);
  assert.deepEqual(out, []);
});

test('QA: scanner with Redis down -> no messages, stats item still emitted', async () => {
  const E = makeEnv();
  E.redis.down = true;
  const out = await runNode(E, 'alice-dms-scanner', 'Code: Find Stale Paths', [{ event: 'x' }], { 'PG: Active Folders': FOLDERS });
  assert.equal(out.length, 1);
  assert.equal(out[0]._stale_for_deletion, false);
});

test('QA: reconcile accepts ignore_delete_limit as string "true" (query param) and ignores other values', async () => {
  const E = makeEnv();
  const run = async query => (await runNode(E, 'alice-dms-reconcile', 'Code: Init Run', [{}], { 'Webhook: POST /alice-dms-reconcile': [{ body: {}, query }] }))[0];
  assert.equal((await run({ ignore_delete_limit: 'true' })).ignore_delete_limit, true);
  assert.equal((await run({ ignore_delete_limit: '1' })).ignore_delete_limit, false);
  assert.equal((await run({})).ignore_delete_limit, false);
  assert.equal((await run({})).mode, 'dry-run');
});

test('QA: schedule run never lifts the delete limit', async () => {
  const E = makeEnv();
  const [init] = await runNode(E, 'alice-dms-reconcile', 'Code: Init Run', [{}], { 'Schedule Trigger: Weekly': [{}], 'Webhook: POST /alice-dms-reconcile': [{ body: { ignore_delete_limit: true } }] });
  assert.equal(init.trigger, 'schedule');
  assert.equal(init.ignore_delete_limit, false);
  assert.equal(init.mode, 'confirm');
});

test('QA: invalid DMS_DELETE_MAX_RATIO falls back to 0.2', async () => {
  const E = makeEnv();
  for (const v of ['abc', '0', '5', '-1']) {
    E.env.DMS_DELETE_MAX_RATIO = v;
    const [init] = await runNode(E, 'alice-dms-reconcile', 'Code: Init Run', [{}], { 'Webhook: POST /alice-dms-reconcile': [{ body: {} }] });
    assert.equal(init.max_delete_ratio, 0.2, v);
  }
});

test('QA: resume marker file itself deleted -> resume continues at the next path', async () => {
  const E = makeEnv();
  for (const n of ['a.jpg', 'c.jpg', 'e.jpg']) E.file('/mnt/nas/pictures/' + n, n);
  E.redis.kv.set('alice:dms:scanner:resume:folder:14', '/mnt/nas/pictures/b.jpg');
  const files = await runNode(E, 'alice-dms-path-worker', 'Code: Scan Single Folder', [{ id: 14, path: '/mnt/nas/pictures' }], { 'Execute Workflow Trigger': [{ id: 14 }] });
  assert.deepEqual(files.map(f => f.file_path.split('/').pop()), ['c.jpg', 'e.jpg']);
});

test('QA: unreadable folder -> no full pass recorded', async () => {
  const E = makeEnv();
  const out = await runNode(E, 'alice-dms-path-worker', 'Code: Scan Single Folder', [{ id: 14, path: '/mnt/nas/doesnotexist' }], { 'Execute Workflow Trigger': [{ id: 14 }] });
  assert.equal(out[0]._no_files, true);
  assert.ok(!E.redis.kv.has('alice:dms:scanner:last_full_pass:folder:14'));
});

test('QA: image moved BEFORE deployment -> self-heal keeps the dead main path (finding BUG-1)', async () => {
  // Weaviate knows the image only under its old (now dead) path, Redis knows nothing.
  const E = makeEnv();
  const h = 'sha256:' + 'ee'.repeat(32);
  E.file('/mnt/nas/pictures/new/m.jpg', 'm');
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/old/m.jpg', file_hash: h, additionalPaths: [] });
  await E.redis.client().sAdd('alice:dms:processed', h);
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/new/m.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'registered');
  // documents the current behaviour: the dead path stays main path until the reconcile repairs it
  assert.equal(E.weaviate.objects.get(id).props.file_path, '/mnt/nas/pictures/old/m.jpg');
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, ['/mnt/nas/pictures/new/m.jpg']);
  // and the scanner never reports the old path (it is not in path_to_hash)
  assert.ok(!E.redis.h(P2H).has('/mnt/nas/pictures/old/m.jpg'));
});
