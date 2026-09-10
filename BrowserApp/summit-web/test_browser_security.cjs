// Offline regression checks using synthetic scraped data; no browser or API calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
const context = vm.createContext({
  document: {
    addEventListener() {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { innerHTML: '', querySelectorAll: () => [] });
      return elements.get(id);
    },
  },
  window: { location: { href: '' } },
  console,
  LEAD_KEY: 'synthetic-lead',
});
for (const filename of ['app.js', 'lead_detail.js', 'leads.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'app/static/js', filename), 'utf8'), context, { filename });
}

async function main() {
  const attack = `"><img src=x onerror="alert(1)">'&`;
  const escaped = context.esc(attack);
  assert(!/[<>"']/.test(escaped), 'Text and attribute escaping must include quotes');
  assert(escaped.includes('&quot;') && escaped.includes('&#39;') && escaped.includes('&amp;'));
  context.renderDetailGrid('grid', [['Injected', attack]]);
  assert(!elements.get('grid').innerHTML.includes('<img'));

  context.syntheticLead = {
    lead_key: `';alert(1);//`, business_name: attack,
    last_lead_score: attack, last_opportunity_score: attack,
    similarity_level: attack, similarity_score: attack,
  };
  context.api = async () => [context.syntheticLead];
  await context.loadSimilar();
  const similar = elements.get('similarBody').innerHTML;
  assert(!similar.includes('<img'), 'Similar-lead fields must be text');
  assert(!similar.includes('onclick='), 'Lead identifiers cannot be interpolated into inline scripts');
  assert(similar.includes('data-lead-url='));

  vm.runInContext('allLeads = [syntheticLead]; renderTable();', context);
  assert(!elements.get('leadsBody').innerHTML.includes('<img'), 'Untrusted score fields must be escaped');
  console.log('Browser security regression checks passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
