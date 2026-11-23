// Offline check of the exported workflows against n8n's own node definitions:
// every node type must exist, parameters must be valid for that node version, and
// connections must point at real nodes. Pass the folder that holds node_modules/n8n.
const path = require('path');
const fs = require('fs');

const base = path.resolve(process.argv[2] || '.tools24', 'node_modules');
const files = process.argv.slice(3);
const known = require(path.join(base, 'n8n-nodes-base/dist/known/nodes.json'));
const { NodeHelpers } = require(path.join(base, 'n8n-workflow'));

function typeFor(type, version) {
  const short = type.replace('n8n-nodes-base.', '');
  const info = known[short];
  if (!info) return null;
  const mod = require(path.join(base, 'n8n-nodes-base', info.sourcePath));
  const inst = new mod[info.className]();
  if (!inst.nodeVersions) return inst;
  return inst.nodeVersions[version] || null;
}

let problems = 0;
for (const file of files) {
  const wf = JSON.parse(fs.readFileSync(file, 'utf8'));
  const names = new Set(wf.nodes.map((n) => n.name));
  console.log(`${path.basename(file)}: ${wf.nodes.length} nodes`);
  for (const n of wf.nodes) {
    const t = typeFor(n.type, n.typeVersion);
    if (!t) { console.log(`  ! ${n.name}: unknown type or version ${n.type}@${n.typeVersion}`); problems++; continue; }
    const issues = NodeHelpers.getNodeParametersIssues(t.description.properties, n, t.description);
    const flat = issues && issues.parameters ? Object.entries(issues.parameters).map(([k, v]) => `${k}: ${[].concat(v).join(', ')}`) : [];
    if (flat.length) { console.log(`  ! ${n.name}: ${flat.join(' | ')}`); problems++; }
  }
  for (const [src, outs] of Object.entries(wf.connections)) {
    if (!names.has(src)) { console.log(`  ! connection from unknown node ${src}`); problems++; }
    for (const branch of outs.main || []) for (const c of branch) if (!names.has(c.node)) { console.log(`  ! connection to unknown node ${c.node}`); problems++; }
  }
}
console.log(problems ? `${problems} problem(s)` : 'all nodes and connections check out');
process.exit(problems ? 1 : 0);
