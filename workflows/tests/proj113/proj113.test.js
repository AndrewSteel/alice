// PROJ-113 logic tests — run: node --test workflows/tests/proj113/
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeEnv, runNode, loadWorkflow } = require('./harness');

const P2H = 'alice:dms:path_to_hash';
const H2P = h => 'alice:dms:hash_to_paths:' + h;
const LOCK = { 'Code: Acquire Processor Lock': [{ lock_owner: 'o1' }] };

// ---------- helpers ----------
async function processImage(E, item) {
  const [out] = await runNode(E, 'alice-dms-processor', 'Code: Process Image Item', [item], LOCK);
  return out;
}
async function lifecycle(E, msg) {
  const [parsed] = await runNode(E, 'alice-dms-lifecycle', 'Code: Parse & Validate', [{ message: JSON.stringify(msg) }]);
  if (!parsed) return null;
  const [found] = await runNode(E, 'alice-dms-lifecycle', 'Code: Weaviate Find by Hash', [parsed]);
  const node = { add_path: 'Code: PATCH additionalPaths', update_path: 'Code: PATCH filePath', delete_file: 'Code: Handle delete_file', remove_path: 'Code: Handle remove_path' }[found.action];
  const [res] = await runNode(E, 'alice-dms-lifecycle', node, [found]);
  if (found.action === 'add_path') await runNode(E, 'alice-dms-lifecycle', 'Code: Redis Update (add_path)', [res]);
  if (found.action === 'update_path') await runNode(E, 'alice-dms-lifecycle', 'Code: Redis Update (update_path)', [res]);
  return res;
}
const FOLDERS = [{ id: 14, path: '/mnt/nas/pictures' }, { id: 5, path: '/mnt/nas/andreas/Documents/Haus' }];
async function findStale(E, folders = FOLDERS) {
  return runNode(E, 'alice-dms-scanner', 'Code: Find Stale Paths', [{ event: 'x' }], { 'PG: Active Folders': folders });
}
function completeAllPasses(E, folders = FOLDERS, at = Date.now() + 1000) {
  for (const f of folders) E.redis.kv.set(`alice:dms:scanner:last_full_pass:folder:${f.id}`, String(at));
}
async function lifecycleCheck(E, item) {
  const [out] = await runNode(E, 'alice-dms-path-worker', 'Code: Lifecycle Check', [item], { 'Execute Workflow Trigger': [{ id: 14 }] });
  return out;
}

// ======================= A) processor image branch =======================
test('A1/A3: new image -> Weaviate insert + path_to_hash + hash_to_paths, queued_files cleared', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'a'.repeat(64);
  await E.redis.client().sAdd('alice:dms:queued_files', h);
  const out = await processImage(E, { file_path: '/mnt/nas/pictures/a.jpg', file_hash: h, file_type: 'jpg', ai_description: 'x' });
  assert.equal(out._image_action, 'new');
  assert.equal(E.weaviate.byClass('Image').length, 1);
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/a.jpg'), h);
  assert.ok(E.redis.s(H2P(h)).has('/mnt/nas/pictures/a.jpg'));
  assert.ok(!E.redis.s('alice:dms:queued_files').has(h));
  assert.ok(E.redis.s('alice:dms:processed').has(h));
});

test('A2/A5: duplicate at other path -> additionalPaths + Redis maps; main path never in additionalPaths', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'b'.repeat(64);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/main.jpg', file_hash: h, additionalPaths: ['/mnt/nas/pictures/main.jpg'] });
  await E.redis.client().sAdd('alice:dms:queued_files', h);
  const out = await processImage(E, { file_path: '/mnt/nas/pictures/copy.jpg', file_hash: h });
  assert.equal(out._image_action, 'add_path');
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, ['/mnt/nas/pictures/copy.jpg']);
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/copy.jpg'), h);
  assert.ok(!E.redis.s('alice:dms:queued_files').has(h));
  assert.equal(E.weaviate.byClass('Image').length, 1);
});

test('A5: re-sent known image (own main path) -> not added to additionalPaths, path registered', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'c'.repeat(64);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/x.jpg', file_hash: h, additionalPaths: [] });
  await processImage(E, { file_path: '/mnt/nas/pictures/x.jpg', file_hash: h });
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, []);
  assert.ok(!E.weaviate.calls.some(c => c[0] === 'PATCH'), 'no needless PATCH');
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/x.jpg'), h);
});

test('A4: processed image with registered path is skipped by the next scan', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'd'.repeat(64);
  await processImage(E, { file_path: '/mnt/nas/pictures/d.jpg', file_hash: h });
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/d.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'already_processed');
  assert.equal(out._skip, true);
});

test('Edge: replaced image (same path, new hash) -> old Image object + thumbnail removed', async () => {
  const E = makeEnv();
  const oldH = 'sha256:' + '1'.repeat(64), newH = 'sha256:' + '2'.repeat(64);
  const oldId = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/r.jpg', file_hash: oldH, additionalPaths: [] });
  const c = E.redis.client();
  await c.hSet(P2H, '/mnt/nas/pictures/r.jpg', oldH); await c.sAdd(H2P(oldH), '/mnt/nas/pictures/r.jpg');
  await processImage(E, { file_path: '/mnt/nas/pictures/r.jpg', file_hash: newH });
  assert.ok(!E.weaviate.objects.has(oldId));
  assert.ok(E.weaviate.thumbDeletes.includes(oldId));
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/r.jpg'), newH);
  assert.ok(!E.redis.s(H2P(oldH)).has('/mnt/nas/pictures/r.jpg'));
  assert.equal(E.weaviate.byClass('Image').length, 1);
});

test('Edge: replaced image whose old object has a copy elsewhere -> copy becomes main path', async () => {
  const E = makeEnv();
  const oldH = 'sha256:' + '3'.repeat(64), newH = 'sha256:' + '4'.repeat(64);
  const oldId = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/r.jpg', file_hash: oldH, additionalPaths: ['/mnt/nas/pictures/copy.jpg'] });
  await E.redis.client().hSet(P2H, '/mnt/nas/pictures/r.jpg', oldH);
  await processImage(E, { file_path: '/mnt/nas/pictures/r.jpg', file_hash: newH });
  assert.equal(E.weaviate.objects.get(oldId).props.file_path, '/mnt/nas/pictures/copy.jpg');
  assert.deepEqual(E.weaviate.objects.get(oldId).props.additionalPaths, []);
});

// ======================= B) self-healing in the scan =======================
test('B: known image without Redis path -> registered, no LLM, no PATCH when it is the main path', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'e'.repeat(64);
  E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/e.jpg', file_hash: h, additionalPaths: [] });
  const c = E.redis.client(); await c.sAdd('alice:dms:processed', h); await c.sAdd('alice:dms:queued_files', h);
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/e.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'registered');
  assert.equal(out._skip, true);
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/e.jpg'), h);
  assert.ok(E.redis.s(H2P(h)).has('/mnt/nas/pictures/e.jpg'));
  assert.ok(!E.redis.s('alice:dms:queued_files').has(h));
  assert.equal(E.redis.kv.get('alice:dms:scanner:stats:folder:14:registered_files'), '1');
  assert.ok(!E.weaviate.calls.some(c => c[0] === 'PATCH'));
  // idempotent: second scan -> already_processed, no duplicate entries
  const again = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/e.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(again._lifecycle_action, 'already_processed');
  assert.equal(E.redis.s(H2P(h)).size, 1);
});

test('B: known image at a new path (moved/copied) -> registered + added as additional path', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'f'.repeat(64);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/old.jpg', file_hash: h, additionalPaths: [] });
  await E.redis.client().sAdd('alice:dms:processed', h);
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/new.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'registered');
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, ['/mnt/nas/pictures/new.jpg']);
});

test('B: hash not processed but in queued_files and in Weaviate -> registered (not stuck as already_queued)', async () => {
  const E = makeEnv();
  const h = 'sha256:' + '5'.repeat(64);
  E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/q.jpg', file_hash: h, additionalPaths: [] });
  await E.redis.client().sAdd('alice:dms:queued_files', h);
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/q.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'registered');
  assert.ok(E.redis.s('alice:dms:processed').has(h));
});

test('B: no Weaviate object -> unchanged behaviour (new / already_queued)', async () => {
  const E = makeEnv();
  const h1 = 'sha256:' + '6'.repeat(64), h2 = 'sha256:' + '7'.repeat(64), h3 = 'sha256:' + '8'.repeat(64);
  const c = E.redis.client(); await c.sAdd('alice:dms:processed', h1); await c.sAdd('alice:dms:queued_files', h2);
  assert.equal((await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/1.jpg', file_hash: h1, file_type: 'jpg' }))._lifecycle_action, 'new');
  assert.equal((await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/2.jpg', file_hash: h2, file_type: 'jpg' }))._lifecycle_action, 'already_queued');
  assert.equal((await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/3.jpg', file_hash: h3, file_type: 'jpg' }))._lifecycle_action, 'new');
});

test('B: document self-heal searches the document collections (fileHash)', async () => {
  const E = makeEnv();
  const h = 'sha256:' + '9'.repeat(64);
  E.weaviate.add('Invoice', { filePath: '/mnt/nas/andreas/Documents/Haus/r.pdf', fileHash: h, additionalPaths: [] });
  await E.redis.client().sAdd('alice:dms:processed', h);
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/andreas/Documents/Haus/r.pdf', file_hash: h, file_type: 'pdf' });
  assert.equal(out._lifecycle_action, 'registered');
});

test('B: Weaviate unreachable during self-heal -> skip with error, NOT sent to the LLM', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'a1'.repeat(32);
  await E.redis.client().sAdd('alice:dms:processed', h);
  E.weaviate.failGraphql = true;
  const out = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/w.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(out._lifecycle_action, 'skip');
  assert.equal(E.redis.l('alice:dms:scanner:stats:folder:14:errors').length, 1);
});

// ======================= C4) resume after the time limit =======================
test('C4: fixed order, resume marker, full-pass bookkeeping', async () => {
  const E = makeEnv();
  for (const n of ['c.jpg', 'a.jpg', 'sub/b.jpg', 'd.jpg']) E.file('/mnt/nas/pictures/' + n, n);
  const trig = { 'Execute Workflow Trigger': [{ id: 14, path: '/mnt/nas/pictures' }] };
  const scan = () => runNode(E, 'alice-dms-path-worker', 'Code: Scan Single Folder', [{ id: 14, path: '/mnt/nas/pictures' }], trig);
  let files = await scan();
  assert.deepEqual(files.map(f => f.file_path.split('/pictures/')[1]), ['a.jpg', 'c.jpg', 'd.jpg', 'sub/b.jpg']);
  const passStart = E.redis.kv.get('alice:dms:scanner:pass_start:folder:14');
  assert.ok(passStart);
  // time limit hit while c.jpg is the current item
  await runNode(E, 'alice-dms-path-worker', 'Code: Abort on Time Limit', [{ ...files[1], _elapsed_seconds: 7200 }], trig);
  assert.equal(E.redis.kv.get('alice:dms:scanner:resume:folder:14'), files[1].file_path);
  const s1 = await runNode(E, 'alice-dms-path-worker', 'Code: Path Worker Summary', [{ _time_limit_reached: true }], trig);
  assert.equal(s1[0].full_pass_completed, false);
  assert.ok(!E.redis.kv.has('alice:dms:scanner:last_full_pass:folder:14'));
  // next run resumes at c.jpg, pass_start unchanged
  files = await scan();
  assert.deepEqual(files.map(f => f.file_path.split('/pictures/')[1]), ['c.jpg', 'd.jpg', 'sub/b.jpg']);
  assert.equal(E.redis.kv.get('alice:dms:scanner:pass_start:folder:14'), passStart);
  // folder end reached -> marker gone, last_full_pass = pass start
  const s2 = await runNode(E, 'alice-dms-path-worker', 'Code: Path Worker Summary', [{}], trig);
  assert.equal(s2[0].full_pass_completed, true);
  assert.ok(!E.redis.kv.has('alice:dms:scanner:resume:folder:14'));
  assert.equal(E.redis.kv.get('alice:dms:scanner:last_full_pass:folder:14'), passStart);
  // marker behind the last file (files deleted) -> restart from the beginning
  E.redis.kv.set('alice:dms:scanner:resume:folder:14', '/mnt/nas/pictures/zzz.jpg');
  files = await scan();
  assert.equal(files.length, 4);
  assert.ok(!E.redis.kv.has('alice:dms:scanner:resume:folder:14'));
});

// ======================= C) scanner stale sweep =======================
async function seedPictures(E, n, h = i => 'sha256:' + String(i).padStart(64, '0')) {
  const c = E.redis.client();
  for (let i = 0; i < n; i++) { const p = E.file(`/mnt/nas/pictures/p${i}.jpg`, 'x' + i); await c.hSet(P2H, p, h(i)); await c.sAdd(H2P(h(i)), p); }
}

test('C1/C2: deleted image reported as delete_file only after a full pass; scanner leaves Redis untouched', async () => {
  const E = makeEnv();
  await seedPictures(E, 10);
  E.rm('/mnt/nas/pictures/p3.jpg');
  let out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 0, 'first sighting only marks');
  assert.ok(E.redis.h('alice:dms:scanner:missing_since').has('/mnt/nas/pictures/p3.jpg'));
  assert.equal(out.at(-1).waiting_paths, 1);
  completeAllPasses(E);
  out = await findStale(E);
  const msgs = out.filter(o => o._stale_for_deletion);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].action, 'delete_file');
  assert.equal(msgs[0].file_path, '/mnt/nas/pictures/p3.jpg');
  assert.ok(E.redis.h(P2H).has('/mnt/nas/pictures/p3.jpg'), 'Redis entry stays until lifecycle handled it');
  // lost message -> reported again on the next run
  out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 1);
});

test('C1: grace waits for EVERY folder pass', async () => {
  const E = makeEnv();
  await seedPictures(E, 10);
  E.rm('/mnt/nas/pictures/p1.jpg');
  await findStale(E);
  E.redis.kv.set('alice:dms:scanner:last_full_pass:folder:14', String(Date.now() + 1000)); // folder 5 never completed
  const out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 0);
});

test('Story: moved image is found by the path worker before the grace ends -> update_path, never deleted', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'ab'.repeat(32);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/old/m.jpg', file_hash: h, additionalPaths: [] });
  for (let i = 0; i < 9; i++) E.file(`/mnt/nas/pictures/k${i}.jpg`, 'k');
  E.file('/mnt/nas/pictures/new/m.jpg', 'm');
  const c = E.redis.client();
  await c.hSet(P2H, '/mnt/nas/pictures/old/m.jpg', h); await c.sAdd(H2P(h), '/mnt/nas/pictures/old/m.jpg'); await c.sAdd('alice:dms:processed', h);
  for (let i = 0; i < 9; i++) await c.hSet(P2H, `/mnt/nas/pictures/k${i}.jpg`, 'sha256:k' + i);
  assert.equal((await findStale(E)).filter(o => o._stale_for_deletion).length, 0);
  const lc = await lifecycleCheck(E, { file_path: '/mnt/nas/pictures/new/m.jpg', file_hash: h, file_type: 'jpg' });
  assert.equal(lc._lifecycle_action, 'update_path');
  await lifecycle(E, { action: 'update_path', file_hash: h, file_path: lc.file_path, old_paths: lc._old_paths });
  assert.equal(E.weaviate.objects.get(id).props.file_path, '/mnt/nas/pictures/new/m.jpg');
  completeAllPasses(E);
  assert.equal((await findStale(E)).filter(o => o._stale_for_deletion).length, 0);
  assert.ok(!E.redis.h('alice:dms:scanner:missing_since').has('/mnt/nas/pictures/old/m.jpg'));
});

test('C3: deleted path with a live copy -> remove_path with alive_paths', async () => {
  const E = makeEnv();
  await seedPictures(E, 10);
  const h = 'sha256:' + '0'.repeat(64);
  const copy = E.file('/mnt/nas/pictures/copy0.jpg', 'x0');
  await E.redis.client().sAdd(H2P(h), copy); await E.redis.client().hSet(P2H, copy, h);
  E.rm('/mnt/nas/pictures/p0.jpg');
  await findStale(E); completeAllPasses(E);
  const msgs = (await findStale(E)).filter(o => o._stale_for_deletion);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].action, 'remove_path');
  assert.deepEqual(msgs[0].alive_paths, [copy]);
});

test('F1: unreachable (empty) share -> nothing reported, markers untouched', async () => {
  const E = makeEnv();
  await seedPictures(E, 5);
  E.rm('/mnt/nas/pictures');
  require('fs').mkdirSync(E.root + '/pictures');
  const out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 0);
  assert.deepEqual(out.at(-1).unreachable_shares, ['/mnt/nas/pictures']);
  assert.equal(E.redis.h('alice:dms:scanner:missing_since').size, 0);
  assert.ok(E.logs.some(l => l[0] === 'warn' && /not reachable/.test(l[2])));
});

test('F2: more than 20 % of a share missing -> no messages; configurable via DMS_DELETE_MAX_RATIO', async () => {
  const E = makeEnv();
  await seedPictures(E, 10);
  for (const i of [1, 2, 3]) E.rm(`/mnt/nas/pictures/p${i}.jpg`);
  await findStale(E); completeAllPasses(E);
  let out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 0);
  assert.deepEqual(out.at(-1).delete_limit_blocked, [{ share: '/mnt/nas/pictures', missing: 3, known: 10 }]);
  E.env.DMS_DELETE_MAX_RATIO = '0.5';
  out = await findStale(E);
  assert.equal(out.filter(o => o._stale_for_deletion).length, 3);
});

test('C: scanner MQTT message carries action + alive_paths', () => {
  const w = loadWorkflow('alice-dms-scanner');
  const n = w.nodes.find(x => x.name === 'MQTT: Publish lifecycle (stale path)');
  assert.match(n.parameters.message, /remove_path/);
  assert.match(n.parameters.message, /alive_paths/);
  assert.equal(w.connections['IF: Is Stale Deletion'].main[0][0].node, 'MQTT: Publish lifecycle (stale path)');
});

// ======================= D) lifecycle =======================
test('D1/D2: delete_file for an image -> object + thumbnail deleted, THEN Redis cleaned', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'cd'.repeat(32);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/g.jpg', file_hash: h, additionalPaths: [] });
  const c = E.redis.client(); await c.hSet(P2H, '/mnt/nas/pictures/g.jpg', h); await c.sAdd(H2P(h), '/mnt/nas/pictures/g.jpg'); await c.sAdd('alice:dms:processed', h);
  const res = await lifecycle(E, { action: 'delete_file', file_hash: h, file_path: '/mnt/nas/pictures/g.jpg' });
  assert.ok(!E.weaviate.objects.has(id));
  assert.ok(E.weaviate.thumbDeletes.includes(id));
  assert.equal(res._deleted_thumbnail, true);
  assert.ok(!E.redis.h(P2H).has('/mnt/nas/pictures/g.jpg'));
  assert.ok(!E.redis.s('alice:dms:processed').has(h));
  assert.ok(!E.redis.sets.has(H2P(h)));
});

test('C2/D: Weaviate lookup fails -> delete_file throws, Redis unchanged (re-reported next scan)', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'ce'.repeat(32);
  await E.redis.client().hSet(P2H, '/mnt/nas/pictures/g.jpg', h);
  E.weaviate.failGraphql = true;
  await assert.rejects(lifecycle(E, { action: 'delete_file', file_hash: h, file_path: '/mnt/nas/pictures/g.jpg' }));
  assert.ok(E.redis.h(P2H).has('/mnt/nas/pictures/g.jpg'));
});

test('D: delete_file without any Weaviate object (duplicate message) -> Redis cleaned, no error', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'cf'.repeat(32);
  await E.redis.client().hSet(P2H, '/mnt/nas/pictures/g.jpg', h);
  await lifecycle(E, { action: 'delete_file', file_hash: h, file_path: '/mnt/nas/pictures/g.jpg' });
  assert.ok(!E.redis.h(P2H).has('/mnt/nas/pictures/g.jpg'));
});

test('C3/D: remove_path of the MAIN path -> live copy becomes main path, dead path gone', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'da'.repeat(32);
  const alive = E.file('/mnt/nas/pictures/b/copy.jpg', 'c');
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/a/main.jpg', file_hash: h, additionalPaths: [alive] });
  const c = E.redis.client(); await c.hSet(P2H, '/mnt/nas/pictures/a/main.jpg', h); await c.sAdd(H2P(h), '/mnt/nas/pictures/a/main.jpg'); await c.sAdd(H2P(h), alive);
  await lifecycle(E, { action: 'remove_path', file_hash: h, file_path: '/mnt/nas/pictures/a/main.jpg', alive_paths: [alive] });
  assert.equal(E.weaviate.objects.get(id).props.file_path, alive);
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, []);
  assert.ok(!E.redis.h(P2H).has('/mnt/nas/pictures/a/main.jpg'));
  assert.deepEqual([...E.redis.s(H2P(h))], [alive]);
});

test('C3/D: remove_path of an ADDITIONAL path -> removed from additionalPaths (document)', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'db'.repeat(32);
  const main = E.file('/mnt/nas/andreas/Documents/Haus/a.pdf', 'a');
  const id = E.weaviate.add('Document', { filePath: main, fileHash: h, fileName: 'a.pdf', additionalPaths: ['/mnt/nas/andreas/Documents/Haus/b.pdf'] });
  await lifecycle(E, { action: 'remove_path', file_hash: h, file_path: '/mnt/nas/andreas/Documents/Haus/b.pdf', alive_paths: [main] });
  assert.equal(E.weaviate.objects.get(id).props.filePath, main);
  assert.equal(E.weaviate.objects.get(id).props.fileName, 'a.pdf');
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, []);
});

test('D3: add_path / update_path work for Image (file_path field, main path never additional)', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'dc'.repeat(32);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/m.jpg', file_hash: h, additionalPaths: [] });
  await lifecycle(E, { action: 'add_path', file_hash: h, file_path: '/mnt/nas/pictures/m2.jpg' });
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, ['/mnt/nas/pictures/m2.jpg']);
  await lifecycle(E, { action: 'add_path', file_hash: h, file_path: '/mnt/nas/pictures/m.jpg' });
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, ['/mnt/nas/pictures/m2.jpg']);
  await lifecycle(E, { action: 'update_path', file_hash: h, file_path: '/mnt/nas/pictures/m2.jpg', old_paths: ['/mnt/nas/pictures/m.jpg'] });
  assert.equal(E.weaviate.objects.get(id).props.file_path, '/mnt/nas/pictures/m2.jpg');
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, []);
  assert.equal(E.redis.h(P2H).get('/mnt/nas/pictures/m2.jpg'), h);
});

test('D4: documents keep working (fileHash/filePath), BankStatement cascade intact', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'dd'.repeat(32);
  const id = E.weaviate.add('BankStatement', { filePath: '/mnt/nas/andreas/k.pdf', fileHash: h, additionalPaths: [] });
  const tx = E.weaviate.add('BankTransaction', { parentStatementId: id });
  const res = await lifecycle(E, { action: 'delete_file', file_hash: h, file_path: '/mnt/nas/andreas/k.pdf' });
  assert.ok(!E.weaviate.objects.has(id));
  assert.ok(!E.weaviate.objects.has(tx));
  assert.equal(res._deleted_transactions, 1);
});

test('D: lifecycle wiring — remove_path branch connected', () => {
  const w = loadWorkflow('alice-dms-lifecycle');
  assert.equal(w.connections['IF: Is delete_file'].main[1][0].node, 'IF: Is remove_path');
  assert.equal(w.connections['IF: Is remove_path'].main[0][0].node, 'Code: Handle remove_path');
  assert.equal(w.connections['Code: Handle remove_path'].main[0][0].node, 'MQTT: Done (remove_path)');
  const mq = w.nodes.find(n => n.name === 'MQTT: Done (remove_path)');
  assert.equal(mq.credentials.mqtt.id, 'Kqy6cn7hyDDXrBA0');
});

// ======================= E/F/G) reconcile =======================
async function reconcile(E, opts = {}) {
  E.staticData = {};
  const body = { confirm: opts.confirm !== false, ...(opts.ignore ? { ignore_delete_limit: true } : {}) };
  const [init] = await runNode(E, 'alice-dms-reconcile', 'Code: Init Run', [{}], { 'Webhook: POST /alice-dms-reconcile': [{ body, query: {} }] });
  const run = { ...init, lock_owner: 'o', _lock_acquired: true };
  const [maps] = await runNode(E, 'alice-dms-reconcile', 'Code: Load Redis Maps', [run]);
  const work = await runNode(E, 'alice-dms-reconcile', 'Code: Query Weaviate', [maps], { 'Code: Load Redis Maps': [maps] });
  const outs = { 'Code: Query Weaviate': work, 'Code: Load Redis Maps': [maps] };
  const actions = [];
  if (!work[0]._empty) for (const w of work) actions.push((await runNode(E, 'alice-dms-reconcile', 'Code: Process Object', [w], outs))[0]._action);
  const [summary] = await runNode(E, 'alice-dms-reconcile', 'Code: Build Summary', [{}], outs);
  return { summary, actions };
}

test('E1/E3: Image is checked; a field missing in the schema is dropped + logged, not a silent skip', async () => {
  const E = makeEnv();
  E.weaviate.schemaMissing.Image = ['thumbnail_path'];
  for (let i = 0; i < 5; i++) E.weaviate.add('Image', { file_path: E.file(`/mnt/nas/pictures/i${i}.jpg`, 'i'), file_hash: 'sha256:' + String(i).repeat(64), additionalPaths: [] });
  E.weaviate.add('Document', { filePath: E.file('/mnt/nas/andreas/d.pdf', 'd'), fileHash: 'sha256:' + 'e'.repeat(64), fileName: 'd.pdf' });
  const { summary } = await reconcile(E);
  assert.equal(summary.checked, 6);
  assert.equal(summary.skipped_ok, 6);
  assert.deepEqual(summary.collection_errors, []);
  assert.ok(E.logs.some(l => /field thumbnail_path not in schema/.test(l[2])));
  // the Image query never asks for file_name
  assert.ok(!E.weaviate.calls.some(c => c[0] === 'POST' && /Image\(limit[^}]*file_name/.test(c[2].query)));
});

test('E2: Image path drift via hash (sha256: prefix) -> file_path corrected', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'ef'.repeat(32);
  for (let i = 0; i < 9; i++) E.weaviate.add('Image', { file_path: E.file(`/mnt/nas/pictures/ok${i}.jpg`, 'o'), file_hash: 'sha256:' + String(i).repeat(64) });
  const live = E.file('/mnt/nas/pictures/moved/x.jpg', 'x');
  await E.redis.client().hSet(P2H, live, h);
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/x.jpg', file_hash: h, additionalPaths: [] });
  const { summary } = await reconcile(E);
  assert.equal(E.weaviate.objects.get(id).props.file_path, live);
  assert.equal(summary.path_repaired, 1);
});

test('E2: orphan image -> object + thumbnail deleted, dead Redis entries removed; own main path cleaned from additionalPaths', async () => {
  const E = makeEnv();
  const h = 'sha256:' + 'fa'.repeat(32);
  for (let i = 0; i < 9; i++) E.weaviate.add('Image', { file_path: E.file(`/mnt/nas/pictures/ok${i}.jpg`, 'o'), file_hash: 'sha256:' + String(i).repeat(64) });
  const dirty = E.weaviate.objects.get([...E.weaviate.objects.keys()][0]);
  dirty.props.additionalPaths = [dirty.props.file_path, '/mnt/nas/pictures/gone.jpg'];
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/dead.jpg', file_hash: h, additionalPaths: [] });
  const c = E.redis.client(); await c.hSet(P2H, '/mnt/nas/pictures/dead.jpg', h); await c.sAdd(H2P(h), '/mnt/nas/pictures/dead.jpg'); await c.sAdd('alice:dms:processed', h);
  const { summary } = await reconcile(E);
  assert.ok(!E.weaviate.objects.has(id));
  assert.ok(E.weaviate.thumbDeletes.includes(id));
  assert.ok(!E.redis.h(P2H).has('/mnt/nas/pictures/dead.jpg'));
  assert.deepEqual(dirty.props.additionalPaths, []);
  assert.equal(summary.deleted_orphan, 1);
  assert.equal(summary.additional_paths_cleaned, 1);
});

test('E2: main path dead but additional path alive -> promoted, NOT deleted', async () => {
  const E = makeEnv();
  const live = E.file('/mnt/nas/pictures/b.jpg', 'b');
  E.file('/mnt/nas/pictures/keep.jpg', 'k');
  const id = E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/a.jpg', file_hash: 'sha256:' + 'fb'.repeat(32), additionalPaths: [live] });
  await reconcile(E);
  assert.ok(E.weaviate.objects.has(id));
  assert.equal(E.weaviate.objects.get(id).props.file_path, live);
  assert.deepEqual(E.weaviate.objects.get(id).props.additionalPaths, []);
});

test('F2/F3: > 20 % orphans in a collection -> no deletes; ignore_delete_limit lifts it', async () => {
  const E = makeEnv();
  E.file('/mnt/nas/pictures/keep.jpg', 'k');
  for (let i = 0; i < 7; i++) E.weaviate.add('Image', { file_path: E.file(`/mnt/nas/pictures/ok${i}.jpg`, 'o'), file_hash: 'sha256:' + String(i).repeat(64) });
  for (let i = 0; i < 3; i++) E.weaviate.add('Image', { file_path: `/mnt/nas/pictures/dead${i}.jpg`, file_hash: 'sha256:' + 'c'.repeat(63) + i });
  let { summary } = await reconcile(E);
  assert.equal(E.weaviate.byClass('Image').length, 10);
  assert.deepEqual(summary.delete_blocked, { Image: { would_delete: 3, total: 10 } });
  assert.equal(summary.skipped_delete_limit, 3);
  ({ summary } = await reconcile(E, { ignore: true }));
  assert.equal(E.weaviate.byClass('Image').length, 7);
  assert.equal(summary.deleted_orphan, 3);
  assert.equal(summary.ignore_delete_limit, true);
});

test('F1/G1: unreachable share -> nothing deleted even with ignore_delete_limit', async () => {
  const E = makeEnv();
  require('fs').mkdirSync(E.root + '/pictures', { recursive: true }); // mounted point, but empty
  for (let i = 0; i < 4; i++) E.weaviate.add('Image', { file_path: `/mnt/nas/pictures/p${i}.jpg`, file_hash: 'sha256:' + String(i).repeat(64) });
  const { summary } = await reconcile(E, { ignore: true });
  assert.equal(E.weaviate.byClass('Image').length, 4);
  assert.equal(summary.skipped_unreachable, 4);
  assert.equal(summary.checked, 4);
});

test('E: dry-run writes nothing', async () => {
  const E = makeEnv();
  E.file('/mnt/nas/pictures/keep.jpg', 'k');
  E.weaviate.add('Image', { file_path: '/mnt/nas/pictures/dead.jpg', file_hash: 'sha256:' + 'aa'.repeat(32) });
  for (let i = 0; i < 9; i++) E.weaviate.add('Image', { file_path: E.file(`/mnt/nas/pictures/ok${i}.jpg`, 'o'), file_hash: 'sha256:' + String(i).repeat(64) });
  const { summary } = await reconcile(E, { confirm: false });
  assert.equal(summary.deleted_orphan, 1);
  assert.equal(E.weaviate.byClass('Image').length, 10);
  assert.ok(!E.weaviate.calls.some(c => c[0] !== 'POST'));
});

test('E4: schedule is weekly Monday 00:00 UTC and wired to Init Run', () => {
  const w = loadWorkflow('alice-dms-reconcile');
  const n = w.nodes.find(x => x.type === 'n8n-nodes-base.scheduleTrigger');
  assert.equal(n.name, 'Schedule Trigger: Weekly');
  assert.equal(n.parameters.rule.interval[0].expression, '0 0 * * 1');
  assert.equal(w.connections['Schedule Trigger: Weekly'].main[0][0].node, 'Code: Init Run');
});
