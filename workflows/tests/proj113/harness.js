// Minimal n8n Code-node harness for PROJ-113 tests: in-memory Redis, fake
// Weaviate (GraphQL Get + REST PATCH/DELETE), fake thumbnailer, /mnt/nas -> temp dir.
const realFs = require('fs');
const path = require('path');
const os = require('os');

const WF_DIR = process.env.WF_DIR || path.join(__dirname, '..', '..');

function loadNodeCode(workflow, nodeName) {
  const w = JSON.parse(realFs.readFileSync(path.join(WF_DIR, workflow + '.json'), 'utf8'));
  const n = w.nodes.find(x => x.name === nodeName);
  if (!n) throw new Error('node not found: ' + nodeName);
  return n.parameters.jsCode;
}
function loadWorkflow(workflow) {
  return JSON.parse(realFs.readFileSync(path.join(WF_DIR, workflow + '.json'), 'utf8'));
}

// ---------------- Redis ----------------
class FakeRedis {
  constructor() { this.kv = new Map(); this.hashes = new Map(); this.sets = new Map(); this.lists = new Map(); this.down = false; this.calls = []; }
  h(k) { if (!this.hashes.has(k)) this.hashes.set(k, new Map()); return this.hashes.get(k); }
  s(k) { if (!this.sets.has(k)) this.sets.set(k, new Set()); return this.sets.get(k); }
  l(k) { if (!this.lists.has(k)) this.lists.set(k, []); return this.lists.get(k); }
  client() {
    const r = this;
    const chk = () => { if (r.down) throw new Error('redis down'); };
    return {
      connect: async () => { chk(); },
      quit: async () => {},
      get: async k => { chk(); return r.kv.has(k) ? r.kv.get(k) : null; },
      set: async (k, v, opts) => { chk(); if (opts && opts.NX && r.kv.has(k)) return null; r.kv.set(k, String(v)); return 'OK'; },
      del: async ks => { chk(); for (const k of [].concat(ks)) { r.kv.delete(k); r.hashes.delete(k); r.sets.delete(k); r.lists.delete(k); } return 1; },
      incr: async k => { chk(); const v = parseInt(r.kv.get(k) || '0', 10) + 1; r.kv.set(k, String(v)); return v; },
      hGet: async (k, f) => { chk(); const v = r.h(k).get(f); return v === undefined ? null : v; },
      hSet: async (k, f, v) => { chk(); r.h(k).set(f, String(v)); return 1; },
      hDel: async (k, f) => { chk(); return r.h(k).delete(f) ? 1 : 0; },
      hGetAll: async k => { chk(); return Object.fromEntries(r.h(k)); },
      hIncrBy: async (k, f, n) => { chk(); const v = parseInt(r.h(k).get(f) || '0', 10) + n; r.h(k).set(f, String(v)); return v; },
      sAdd: async (k, m) => { chk(); r.s(k).add(m); return 1; },
      sRem: async (k, m) => { chk(); const ok = r.s(k).delete(m); if (r.s(k).size === 0) r.sets.delete(k); return ok ? 1 : 0; },
      sMembers: async k => { chk(); return [...r.s(k)]; },
      sIsMember: async (k, m) => { chk(); return r.s(k).has(m); },
      rPush: async (k, v) => { chk(); r.l(k).push(v); return r.l(k).length; },
      lRange: async k => { chk(); return [...r.l(k)]; },
      lLen: async k => { chk(); return r.l(k).length; },
      lRem: async (k, c, v) => { chk(); r.lists.set(k, r.l(k).filter(x => x !== v)); return 1; },
      eval: async () => { chk(); return 1; },
    };
  }
}

// ---------------- Weaviate + thumbnailer ----------------
class FakeWeaviate {
  constructor() { this.objects = new Map(); this.schemaMissing = {}; this.failGraphql = false; this.calls = []; this.thumbDeletes = []; this.seq = 0; }
  add(cls, props, id) { id = id || ('00000000-0000-0000-0000-' + String(++this.seq).padStart(12, '0')); this.objects.set(id, { cls, id, props: { ...props } }); return id; }
  byClass(cls) { return [...this.objects.values()].filter(o => o.cls === cls); }
  graphql(query) {
    if (this.failGraphql) throw new Error('weaviate down');
    const out = {}; const errors = [];
    const re = /(\w+)\(([^)]*)\)\s*\{\s*_additional \{ id \}\s*([^}]*)\}/g;
    let m;
    while ((m = re.exec(query))) {
      const [, cls, args, fieldStr] = m;
      const fields = fieldStr.trim().split(/\s+/).filter(Boolean);
      for (const f of fields) {
        if ((this.schemaMissing[cls] || []).includes(f)) errors.push({ message: `Cannot query field "${f}" on type "${cls}".` });
      }
      let list = this.byClass(cls).sort((a, b) => (a.id < b.id ? -1 : 1));
      const w = args.match(/path: \["(\w+)"\], operator: Equal, valueText: "([^"]*)"/);
      if (w) list = list.filter(o => o.props[w[1]] === w[2]);
      const after = args.match(/after: "([^"]+)"/);
      if (after) list = list.filter(o => o.id > after[1]);
      const lim = args.match(/limit: (\d+)/); if (lim) list = list.slice(0, parseInt(lim[1], 10));
      out[cls] = list.map(o => { const r = { _additional: { id: o.id } }; for (const f of fields) r[f] = o.props[f] === undefined ? null : o.props[f]; return r; });
    }
    if (errors.length) return { errors };
    return { data: { Get: out } };
  }
  axios() {
    const wv = this;
    const resp = (status, data) => ({ status, data });
    return {
      post: async (url, body, opts) => {
        wv.calls.push(['POST', url, body]);
        if (url.endsWith('/v1/graphql')) return resp(200, wv.graphql(body.query));
        if (url.endsWith('/v1/objects')) { const id = wv.add(body.class, body.properties); return resp(200, { id }); }
        throw new Error('unexpected POST ' + url);
      },
      patch: async (url, body) => {
        wv.calls.push(['PATCH', url, body]);
        if (wv.failGraphql) throw new Error('weaviate down');
        const id = url.split('/').pop(); const o = wv.objects.get(id);
        if (!o) { const e = new Error('Request failed with status code 404'); throw e; }
        Object.assign(o.props, body.properties); return resp(204, {});
      },
      delete: async (url, opts) => {
        wv.calls.push(['DELETE', url]);
        const id = url.split('/').pop();
        if (url.includes('alice-dms-thumbnailer')) { wv.thumbDeletes.push(id); return resp(200, { deleted: true }); }
        if (wv.failGraphql) throw new Error('weaviate down');
        const existed = wv.objects.delete(id);
        if (!existed) { if (opts && opts.validateStatus) return resp(404, {}); throw new Error('Request failed with status code 404'); }
        return resp(204, {});
      },
      get: async (url) => { const id = url.split('/').pop(); return resp(wv.objects.has(id) ? 200 : 404, {}); },
    };
  }
}

// ---------------- fs: /mnt/nas -> temp dir ----------------
function makeFs(root) {
  const map = p => (typeof p === 'string' && p.startsWith('/mnt/nas') ? root + p.slice('/mnt/nas'.length) : p);
  const wrapped = {};
  for (const k of Object.keys(realFs)) wrapped[k] = realFs[k];
  for (const k of ['existsSync', 'accessSync', 'readdirSync', 'statSync', 'lstatSync', 'readFileSync']) {
    wrapped[k] = (p, ...a) => realFs[k](map(p), ...a);
  }
  wrapped.constants = realFs.constants;
  return wrapped;
}

const tempRoots = [];
process.on('exit', () => { for (const r of tempRoots) realFs.rmSync(r, { recursive: true, force: true }); });

function makeEnv() {
  const root = realFs.mkdtempSync(path.join(process.env.TEST_TMP || os.tmpdir(), 'nas-'));
  tempRoots.push(root);
  return {
    root,
    redis: new FakeRedis(),
    weaviate: new FakeWeaviate(),
    env: { REDIS_PASSWORD: '' },
    staticData: {},
    logs: [],
    file(p, content) { const real = root + p.slice('/mnt/nas'.length); realFs.mkdirSync(path.dirname(real), { recursive: true }); realFs.writeFileSync(real, content); return p; },
    rm(p) { realFs.rmSync(root + p.slice('/mnt/nas'.length), { recursive: true, force: true }); },
    hash(content) { return 'sha256:' + require('crypto').createHash('sha256').update(content).digest('hex'); },
  };
}

// run one Code node. nodeOutputs: { 'Node Name': [json, ...] } for $('...')
async function runNode(E, workflow, nodeName, inputItems, nodeOutputs = {}) {
  const code = loadNodeCode(workflow, nodeName);
  const fakeFs = makeFs(E.root);
  const logger = { info: m => E.logs.push(['info', nodeName, m]), warn: m => E.logs.push(['warn', nodeName, m]), error: m => E.logs.push(['error', nodeName, m]) };
  const req = name => {
    if (name === 'redis') return { createClient: () => E.redis.client() };
    if (name === 'axios') return E.weaviate.axios();
    if (name === 'fs') return fakeFs;
    if (name === 'winston') return { createLogger: () => logger, transports: { File: function () {} } };
    return require(name);
  };
  const items = inputItems.map(j => ({ json: j }));
  const $input = { first: () => items[0], all: () => items };
  const $ = n => {
    if (!(n in nodeOutputs)) throw new Error(`Node '${n}' hasn't been executed`);
    const arr = nodeOutputs[n].map(j => ({ json: j }));
    return { first: () => arr[0], all: () => arr };
  };
  const fn = new (Object.getPrototypeOf(async function () {}).constructor)('require', '$input', '$', '$env', '$getWorkflowStaticData', code);
  const out = await fn(req, $input, $, E.env, () => E.staticData);
  return (out || []).map(i => i.json);
}

module.exports = { makeEnv, runNode, loadWorkflow };
