#!/usr/bin/env bash
# Static checks for the n8n workflow exports in workflows/*.json.
# Workflows are never deployed from here (the user deploys them manually), so this
# is the only automated safety net for workflow changes:
#   - valid JSON with a nodes array and a connections object
#   - unique node names, every connection points to an existing node
#   - no console.log in Code/Function nodes (use winston, see CLAUDE.md)
set -uo pipefail
cd "$(dirname "$0")/.."
FAILED=0
for f in workflows/*.json; do
  if ! jq -e '(.nodes | type) == "array" and (.connections | type) == "object"' "$f" >/dev/null 2>&1; then
    echo "✗ $f: not a valid n8n workflow export (nodes/connections missing or invalid JSON)"; FAILED=1; continue
  fi
  dup=$(jq -r '[.nodes[].name] | group_by(.) | map(select(length > 1) | .[0]) | join(", ")' "$f")
  [ -n "$dup" ] && { echo "✗ $f: duplicate node names: $dup"; FAILED=1; }
  missing=$(jq -r '([.nodes[].name]) as $names
    | [.connections | to_entries[] | .key as $src | (if ($names | index($src)) then empty else $src end),
       (.value[][][]? | .node | select(. as $n | $names | index($n) | not))] | unique | join(", ")' "$f")
  [ -n "$missing" ] && { echo "✗ $f: connections reference unknown nodes: $missing"; FAILED=1; }
  logs=$(jq -r '[.nodes[] | select((.parameters.jsCode // .parameters.functionCode // .parameters.pythonCode // "") | test("console\\.log")) | .name] | join(", ")' "$f")
  [ -n "$logs" ] && { echo "✗ $f: console.log in Code nodes ($logs), use winston"; FAILED=1; }
done
[ $FAILED -eq 0 ] && echo "✓ $(ls workflows/*.json | wc -l) workflows OK"
exit $FAILED
