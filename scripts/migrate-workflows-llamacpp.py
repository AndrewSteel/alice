#!/usr/bin/env python3
"""
PROJ-99: rewrite the DMS workflows' Ollama /api/generate calls to llama.cpp's
OpenAI-compatible /v1/chat/completions.

Operates on the RAW JSON text with surgical string replacement so the diff is
limited to the changed node bodies — no whole-file reformat.

Strategy — minimal, mechanical, reviewable:
  * A shared shim `llamaGenerate(body, cfg)` is prepended to each affected Code
    node. It accepts the OLD Ollama request body ({model, prompt, format,
    options:{temperature,num_predict}}) and returns an object shaped exactly
    like the old axios response: { data: { response: "<text>" }, status, ... }.
    Each call site changes only:
       axios.post('http://ollama-3090:11434/api/generate', BODY, CFG)
         ->  await llamaGenerate(BODY, CFG)
  * axios.get('.../api/tags')  ->  axios.get(<OLLAMA_URL>/v1/models)   (same 2xx)
  * `const OLLAMA_URL = 'http://ollama-3090:11434'`  ->  env-driven
  * The two HTTP Request nodes are handled by scripts/migrate-http-nodes.py
    (see PROJ-99 spec) — this script only touches Code nodes.

Run from repo root:
  python3 scripts/migrate-workflows-llamacpp.py           # apply
  python3 scripts/migrate-workflows-llamacpp.py --check    # verify clean
"""
import json
import pathlib
import re
import sys

WF_DIR = pathlib.Path("workflows")
OLD_HOST = "http://ollama-3090:11434"

SHIM_LINES = [
    "const _LLAMA_URL = (() => { try { return ($env.OLLAMA_URL || 'http://llama-3090:11434').replace(/\\/$/, ''); } catch(e) { return 'http://llama-3090:11434'; } })();",
    "const _LLAMA_KEY = (() => { try { return $env.OLLAMA_API_KEY || ''; } catch(e) { return ''; } })();",
    "function _llamaHeaders() { const h = { 'Content-Type': 'application/json' }; if (_LLAMA_KEY) h['Authorization'] = 'Bearer ' + _LLAMA_KEY; return h; }",
    "// PROJ-99 shim: takes an OLD Ollama /api/generate body, calls llama.cpp /v1/chat/completions, returns a { data: { response } } shaped result.",
    "async function llamaGenerate(body, cfg) {",
    "  const opts = body.options || {};",
    "  const payload = { model: body.model, messages: [{ role: 'user', content: body.prompt }], stream: false };",
    "  if (opts.temperature !== undefined) payload.temperature = opts.temperature;",
    "  if (opts.num_predict !== undefined) payload.max_tokens = opts.num_predict;",
    "  if (body.format === 'json') payload.response_format = { type: 'json_object' };",
    "  const rcfg = Object.assign({}, cfg || {}, { headers: Object.assign({}, _llamaHeaders(), (cfg && cfg.headers) || {}) });",
    "  const resp = await axios.post(_LLAMA_URL + '/v1/chat/completions', payload, rcfg);",
    "  const content = (((resp.data || {}).choices || [{}])[0].message || {}).content || '';",
    "  return { data: { response: content }, status: resp.status, statusText: resp.statusText };",
    "}",
]
SHIM = "\n".join(SHIM_LINES) + "\n"

CALL_RE = re.compile(
    r"(await\s+)?axios\.post\(\s*(['\"])" + re.escape(OLD_HOST) + r"/api/generate\2\s*,"
)
CALL_RE_TMPL = re.compile(
    r"(await\s+)?axios\.post\(\s*`\$\{OLLAMA_URL\}/api/generate`\s*,"
)
TAGS_RE = re.compile(
    r"axios\.get\(\s*(['\"])" + re.escape(OLD_HOST) + r"/api/tags\1"
)


def patch_code(js: str) -> str:
    orig = js

    if TAGS_RE.search(js):
        js = TAGS_RE.sub(
            "axios.get((($env.OLLAMA_URL || 'http://llama-3090:11434').replace(/\\/$/, '')) + '/v1/models'",
            js,
        )

    js = CALL_RE.sub("await llamaGenerate(", js)
    js = CALL_RE_TMPL.sub("await llamaGenerate(", js)

    js = js.replace(
        "const OLLAMA_URL = 'http://ollama-3090:11434';",
        "const OLLAMA_URL = (() => { try { return $env.OLLAMA_URL || 'http://llama-3090:11434'; } catch(e) { return 'http://llama-3090:11434'; } })();",
    )

    if js == orig:
        return js

    # Only inject the shim where a call to it now exists.
    if "await llamaGenerate(" in js and "async function llamaGenerate(" not in js:
        m = re.search(r"^.*require\('axios'\);\n", js, re.M)
        if m:
            js = js[: m.end()] + SHIM + js[m.end():]
        else:
            js = "const axios = require('axios');\n" + SHIM + js
    return js


def main() -> int:
    check = "--check" in sys.argv
    touched = []
    leftover = []

    for wf_path in sorted(WF_DIR.glob("*.json")):
        raw = wf_path.read_text()
        wf = json.loads(raw)
        new_raw = raw

        for node in wf.get("nodes", []):
            if node.get("type") != "n8n-nodes-base.code":
                continue
            js = node.get("parameters", {}).get("jsCode", "")
            if not js:
                continue
            new_js = patch_code(js)
            if new_js != js:
                # The file may escape non-ASCII (\uXXXX) or not — try both and
                # swap whichever literal actually occurs in the raw text.
                for ea in (False, True):
                    old_lit = json.dumps(js, ensure_ascii=ea)
                    if old_lit in new_raw:
                        new_lit = json.dumps(new_js, ensure_ascii=ea)
                        new_raw = new_raw.replace(old_lit, new_lit, 1)
                        break
                else:
                    raise SystemExit(
                        f"{wf_path.name}: {node['name']} — jsCode literal not found in raw JSON"
                    )

        if new_raw != raw:
            touched.append(wf_path.name)
            if not check:
                wf_path.write_text(new_raw)

        # post-check for anything still pointing at the old host in a Code node
        after = new_raw
        if OLD_HOST in after or "${OLLAMA_URL}/api/generate" in after:
            # HTTP nodes are handled separately; only flag Code-node residue
            for node in json.loads(after).get("nodes", []):
                if node.get("type") == "n8n-nodes-base.code":
                    j = node.get("parameters", {}).get("jsCode", "")
                    if OLD_HOST in j or "${OLLAMA_URL}/api/generate" in j or "/api/tags" in j:
                        leftover.append(f"{wf_path.name}:{node['name']}")

    if check:
        if leftover:
            print("STILL REFERENCES OLD OLLAMA (Code nodes):")
            for x in leftover:
                print("  -", x)
            return 1
        print("Code nodes clean.  (touched by a real run: %s)" % (", ".join(touched) or "none"))
        return 0

    print("patched:", ", ".join(touched) if touched else "(none)")
    if leftover:
        print("WARNING residue:", leftover)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
