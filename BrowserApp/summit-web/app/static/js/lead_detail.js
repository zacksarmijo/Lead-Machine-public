let currentLead = null;
let isPinned = false;

const DETAIL_AI_MODELS = {
  OpenAI: [
    { value: 'gpt-5.5', label: 'GPT-5.5 (best quality)' },
    { value: 'gpt-5.4', label: 'GPT-5.4 (balanced)' },
    { value: 'gpt-5.4-mini', label: 'GPT-5.4 Mini (recommended value)' },
    { value: 'gpt-5.4-nano', label: 'GPT-5.4 Nano (cheapest)' },
    { value: 'gpt-5.5-pro', label: 'GPT-5.5 Pro (expensive)' },
    { value: 'gpt-4.1', label: 'GPT-4.1 (legacy)' },
    { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini (legacy value)' },
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini (legacy cheap)' },
  ],
  Anthropic: [
    { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (recommended)' },
    { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (fast/value)' },
    { value: 'claude-opus-4-7', label: 'Claude Opus 4.7 (best/expensive)' },
    { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4 (legacy)' },
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4 (legacy)' },
  ],
};

document.addEventListener('DOMContentLoaded', async () => {
  if (window.WEBSITE_STUDIO_MODE) {
    await loadAiProviderDefault();
    await loadWebsitePackage();
    wpInstallDirtyGuard();
    return;
  }
  await loadLead();
  await checkPinStatus();
});

async function loadLead() {
  try {
    currentLead = await api(`/api/leads/${encodeURIComponent(LEAD_KEY)}`);
    renderLead();
    loadActivity();
    loadSimilar();
  } catch (err) {
    console.error('Load lead error:', err);
    document.getElementById('leadContent').innerHTML =
      '<div class="empty-state"><div class="empty-state-title">Lead not found</div></div>';
  }
}

function renderLead() {
  const lead = currentLead;
  const data = getPayload(lead);
  const tmpl = document.getElementById('detailTemplate');
  document.getElementById('leadContent').innerHTML = tmpl.innerHTML;

  document.getElementById('leadTitle').textContent = lead.business_name || data['Business Name'] || 'Lead Detail';
  document.getElementById('detailName').textContent = lead.business_name || data['Business Name'] || '';

  const bucket = lead.website_bucket || data['Website Bucket'] || data['Web Presence Status'] || '';
  const bucketEl = document.getElementById('detailBucket');
  bucketEl.textContent = bucket || 'Unknown';
  bucketEl.className = `badge ${webBucketBadge(bucket)}`;

  const pipeline = lead.pipeline_status || 'Needs review';
  const pipEl = document.getElementById('detailPipeline');
  pipEl.textContent = pipeline;
  pipEl.className = `badge ${pipelineBadge(pipeline)}`;

  const score = lead.last_lead_score ?? data['Lead Score'] ?? '';
  const scoreEl = document.getElementById('detailScore');
  scoreEl.textContent = score !== '' ? score : '--';
  scoreEl.className = `score ${scoreClass(+score)}`;

  const oppScore = lead.last_opportunity_score ?? data['Opportunity Score'] ?? '';
  const oppEl = document.getElementById('detailOppScore');
  if (oppEl) {
    oppEl.textContent = oppScore !== '' ? oppScore : '--';
    oppEl.className = `score ${scoreClass(+oppScore)}`;
  }
  const oppLabelEl = document.getElementById('detailOppLabel');
  if (oppLabelEl) {
    oppLabelEl.textContent = data['Opportunity Label'] || '';
  }

  // Overview grid
  const overviewFields = [
    ['Business Name', lead.business_name || data['Business Name']],
    ['Address', lead.address || data['Address']],
    ['City / Area', lead.city_area || data['City/Area']],
    ['Business Type', data['Business Type']],
    ['Rating', data['Rating']],
    ['Reviews', data['Reviews']],
    ['Phone', data['Phone']],
    ['Email', data['Email']],
    ['Seed Source', data['Seed Source'] || lead.last_seed_source],
    ['Review Bucket', data['Review Bucket']],
    ['Opportunity Score', data['Opportunity Score']],
    ['Opportunity Label', data['Opportunity Label']],
    ['Business Reality', data['Business Reality']],
    ['Reality Confidence', data['Reality Confidence']],
  ];
  renderDetailGrid('overviewGrid', overviewFields);

  const officialRecordStatus = data['Official Record Status'] || data['Colorado Record Status'];
  const officialStatusCategory = data['Official Status Category'] || data['Colorado Status Category'];
  const officialMatchType = data['Official Match Type'] || data['Colorado Match Type'];
  const officialHistorySummary = data['Official History Summary'] || data['Colorado History Summary'];

  // Web + official records grid
  const webFields = [
    ['Web Presence Status', data['Web Presence Status'] || lead.last_web_presence_status],
    ['Website Failure Type', data['Website Failure Type']],
    ['Official Website', data['Official Website']],
    ['Web Presence Confidence', data['Web Presence Confidence']],
    ['Source Confidence', data['Source Confidence Tier']],
    ['Source Confidence Score', data['Source Confidence Score']],
    ['Website Assertion Status', data['Website Assertion Status']],
    ['Why Surfaced', data['Why Surfaced']],
    ['Why Suppressed', data['Why Suppressed']],
    ['Next Best Action', data['Next Best Action']],
    ['LinkedIn Profile', data['LinkedIn Profile']],
    ['Social Profiles', data['Social Profiles']],
    ['Contact Cross-Reference', data['Contact Cross-Reference']],
    ['Cross-Reference Details', data['Cross-Reference Details']],
    ['Formation Date', data['Formation Date']],
    ['Business Age Days', data['Business Age Days']],
    ['Official Record Source', data['Official Record Source']],
    ['Official Record State', data['Official Record State']],
    ['Official Record Status', officialRecordStatus],
    ['Official Status Category', officialStatusCategory],
    ['Official Match Type', officialMatchType],
    ['Official History Summary', officialHistorySummary],
    ['License Status', data['License Status']],
    ['License Details', data['License Details']],
  ];
  renderDetailGrid('webGrid', webFields);

  // Audit evidence
  const audit = lead.latest_audit || {};
  const evidenceFields = [
    ['Resolved URL', audit.resolved_url || data['Resolved Website URL']],
    ['HTTP Status', audit.http_status || data['HTTP Status']],
    ['Fetch Time (ms)', audit.fetch_time_ms || data['Fetch Time Ms']],
    ['Page Title', audit.page_title || data['Page Title']],
    ['Meta Description', audit.meta_description || data['Meta Description']],
    ['Word Count', audit.word_count || data['Word Count']],
    ['Total Word Count (all pages)', data['Total Word Count']],
    ['Form Count', audit.form_count || data['Form Count']],
    ['Image Count', audit.image_count || data['Image Count']],
    ['Internal Links', audit.internal_link_count || data['Internal Link Count']],
    ['On-Page Phones', audit.on_page_phones || data['On-Page Phones']],
    ['On-Page Emails', audit.on_page_emails || data['On-Page Emails']],
    ['CTA Terms', audit.cta_terms || data['CTA Terms']],
    ['Inner Pages Checked', data['Inner Pages Checked']],
    ['Inner Page URLs', data['Inner Page URLs']],
    ['Contact Page Found', data['Contact Page Found']],
    ['Contact Page Has Form', data['Contact Page Has Form']],
    ['Services Described', data['Services Described']],
    ['About Page Found', data['About Page Found']],
    ['Discovery Sources', data['Discovery Sources']],
    ['Sources Checked', data['Sources Checked']],
    ['Source Matrix', data['Source Confidence Matrix']],
    ['Source Warnings', data['Source Confidence Warnings']],
    ['Evidence Summary', audit.evidence_summary || data['Website Evidence Summary']],
  ];
  renderDetailGrid('auditEvidenceGrid', evidenceFields);

  // Audit diagnostics
  const diagFields = [
    ['Mobile Readiness', audit.mobile_readiness || data['Mobile Readiness']],
    ['SSL Status', audit.ssl_status || data['SSL Status']],
    ['Page Speed Signal', audit.page_speed_signal || data['Page Speed Signal']],
    ['PageSpeed Status', data['PageSpeed Status']],
    ['PageSpeed Performance', data['PageSpeed Performance Score']],
    ['PageSpeed Accessibility', data['PageSpeed Accessibility Score']],
    ['PageSpeed Best Practices', data['PageSpeed Best Practices Score']],
    ['PageSpeed SEO', data['PageSpeed SEO Score']],
    ['PageSpeed FCP', data['PageSpeed FCP']],
    ['PageSpeed LCP', data['PageSpeed LCP']],
    ['PageSpeed Speed Index', data['PageSpeed Speed Index']],
    ['PageSpeed TBT', data['PageSpeed TBT']],
    ['PageSpeed CLS', data['PageSpeed CLS']],
    ['CrUX Overall', data['PageSpeed CrUX Overall']],
    ['CrUX Field Summary', data['PageSpeed Field Summary']],
    ['PageSpeed Opportunities', data['PageSpeed Opportunities']],
    ['PageSpeed Error', data['PageSpeed Error']],
    ['BuiltWith Status', data['BuiltWith Status']],
    ['BuiltWith Domain', data['BuiltWith Domain']],
    ['Tech Stack Signal', data['Tech Stack Signal']],
    ['Tech Stack Score', data['Tech Stack Score']],
    ['Tech Stack Summary', data['Tech Stack Summary']],
    ['Tech Stack Weak Signals', data['Tech Stack Weak Signals']],
    ['Tech Stack Strong Signals', data['Tech Stack Strong Signals']],
    ['BuiltWith Groups', data['BuiltWith Groups']],
    ['BuiltWith Categories', data['BuiltWith Category Summary']],
    ['Tech Stack Error', data['Tech Stack Error']],
    ['Contact Form Status', audit.contact_form_status || data['Contact Form Status']],
    ['Booking Flow Status', audit.booking_flow_status || data['Booking Flow Status']],
    ['CTA Strength', audit.cta_strength || data['CTA Strength']],
    ['SEO Basics', audit.seo_basics || data['SEO Basics']],
    ['Navigation Quality', audit.navigation_quality || data['Navigation Quality']],
    ['Image Quality Signal', audit.image_quality_signal || data['Image Quality Signal']],
    ['Social Dependence', audit.social_dependence || data['Social Dependence']],
    ['Directory Dependence', audit.directory_dependence || data['Directory Dependence']],
    ['Audit Confidence', audit.audit_confidence || data['Audit Confidence']],
    ['Audit Confidence Score', data['Audit Confidence Score']],
    ['Quality Score (0-100)', data['Quality Score']],
    ['Primary Business Impact', audit.primary_business_impact || data['Primary Business Impact']],
    ['Best Pitch Angle', audit.best_pitch_angle || data['Best Pitch Angle']],
  ];
  renderDetailGrid('auditDiagGrid', diagFields);

  // Workflow fields
  const wfPipeline = document.getElementById('wfPipeline');
  if (wfPipeline) wfPipeline.value = lead.pipeline_status || 'Needs review';
  setVal('wfOwner', lead.lead_owner);
  setVal('wfNextAction', lead.next_action);
  setVal('wfSummary', lead.opportunity_summary);
  setVal('wfStrategy', lead.outreach_angle);
  setVal('wfDraft', lead.draft_message);
  setVal('wfNotes', lead.personalization_notes);

  // Render website grading panel
  if (typeof renderWebsiteGrading === 'function') {
    renderWebsiteGrading('gradingContainer', lead);
  }

  // Enable/disable export button based on draft content
  updateExportButton();
  // Listen for changes on draft/summary fields to toggle button
  ['wfDraft', 'wfSummary'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updateExportButton);
  });

  // Render existing agent review if present
  if (lead.agent_review && lead.agent_review.verdict) {
    renderAgentReview(
      lead.agent_review,
      lead.agent_review_status || '',
      lead.agent_review_model || '',
      lead.agent_review_updated_at || ''
    );
  }

  initTabs('#leadContent');
  wpInstallDirtyGuard();
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val || '';
}

function renderDetailGrid(gridId, fields) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = fields.map(([label, value]) => {
    if (value == null || value === '') {
      return `<div class="detail-item"><div class="detail-label">${esc(label)}</div><div class="detail-value"><span class="text-muted">--</span></div></div>`;
    }
    const raw = String(value);
    const escaped = esc(raw);
    const isUrl = /^https?:\/\//i.test(raw.trim());
    const inner = isUrl
      ? `<a href="${escaped}" target="_blank" rel="noopener noreferrer">${escaped}</a>`
      : escaped;
    const dataAttr = escaped;
    return `<div class="detail-item">`
      + `<div class="detail-label">${esc(label)}</div>`
      + `<div class="detail-value detail-value-copyable" data-copy="${dataAttr}" title="Click icon to copy">`
      + `${inner}`
      + `<button type="button" class="detail-copy-btn" onclick="copyDetailValue(event)" title="Copy">&#128203;</button>`
      + `</div></div>`;
  }).join('');
}

function copyDetailValue(ev) {
  ev.preventDefault();
  ev.stopPropagation();
  const btn = ev.currentTarget;
  const host = btn.closest('.detail-value-copyable');
  if (!host) return;
  const text = host.getAttribute('data-copy') || host.textContent.trim();
  const done = () => {
    btn.classList.add('copied');
    const original = btn.innerHTML;
    btn.innerHTML = '&#10003;';
    if (typeof toast === 'function') toast('Copied', 'success');
    setTimeout(() => { btn.classList.remove('copied'); btn.innerHTML = original; }, 1200);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => legacyCopy(text, done));
  } else {
    legacyCopy(text, done);
  }
}

function legacyCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); done(); } catch (e) { /* noop */ }
  document.body.removeChild(ta);
}

async function saveWorkflow() {
  try {
    await api(`/api/leads/${encodeURIComponent(LEAD_KEY)}/state`, {
      method: 'PUT',
      body: {
        pipeline_status: document.getElementById('wfPipeline').value,
        lead_owner: document.getElementById('wfOwner').value,
        next_action: document.getElementById('wfNextAction').value,
        opportunity_summary: document.getElementById('wfSummary').value,
        outreach_angle: document.getElementById('wfStrategy').value,
        draft_message: document.getElementById('wfDraft').value,
        personalization_notes: document.getElementById('wfNotes').value,
      }
    });
    toast('Workflow saved', 'success');
    await loadLead();
  } catch (err) {
    toast('Save failed', 'error');
  }
}

async function generateDraft() {
  const btn = document.getElementById('btnGenerate');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating...';
  try {
    const provider = document.getElementById('aiProviderToggle')?.value || 'OpenAI';
    const model = document.getElementById('aiModelToggle')?.value || '';
    const result = await api('/api/ai/generate', {
      method: 'POST',
      body: {
        lead_key: LEAD_KEY,
        ai_provider: provider,
        ai_model: model,
        personalization_notes: document.getElementById('wfNotes').value,
        outreach_angle: document.getElementById('wfStrategy').value,
        existing_draft: document.getElementById('wfDraft').value,
        existing_summary: document.getElementById('wfSummary').value,
      }
    });
    if (result.ok) {
      document.getElementById('wfSummary').value = result.opportunity_summary || '';
      document.getElementById('wfStrategy').value = result.outreach_strategy || '';
      document.getElementById('wfDraft').value = result.draft_message || '';
      toast('AI draft generated', 'success');
    } else {
      toast(result.error || 'Generation failed', 'error');
    }
  } catch (err) {
    toast('AI generation failed', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate AI Draft';
  }
}

async function loadActivity() {
  try {
    const activities = await api(`/api/leads/${encodeURIComponent(LEAD_KEY)}/activity`);
    const list = document.getElementById('activityList');
    if (!list) return;
    if (!activities.length) {
      list.innerHTML = '<li class="text-muted" style="padding:16px;text-align:center;">No activity logged yet</li>';
      return;
    }
    list.innerHTML = activities.map(a =>
      `<li class="activity-item">
        <div class="activity-meta">
          <span>${esc(a.activity_type)}</span>
          <span>${formatDate(a.created_at)}</span>
        </div>
        <div class="activity-summary">${esc(a.summary)}</div>
        ${a.details ? `<div class="activity-details">${esc(a.details)}</div>` : ''}
      </li>`
    ).join('');
  } catch (e) { console.error('Load activity error:', e); }
}

async function addActivity() {
  const summary = document.getElementById('actSummary').value.trim();
  if (!summary) { toast('Enter a summary', 'error'); return; }
  try {
    await api(`/api/leads/${encodeURIComponent(LEAD_KEY)}/activity`, {
      method: 'POST',
      body: {
        activity_type: document.getElementById('actType').value,
        summary: summary,
        details: document.getElementById('actDetails').value,
      }
    });
    document.getElementById('actSummary').value = '';
    document.getElementById('actDetails').value = '';
    toast('Activity added', 'success');
    await loadActivity();
  } catch (err) { toast('Failed to add activity', 'error'); }
}

async function loadSimilar() {
  try {
    const similar = await api(`/api/leads/${encodeURIComponent(LEAD_KEY)}/similar`);
    const tbody = document.getElementById('similarBody');
    if (!tbody) return;
    if (!similar.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-muted" style="text-align:center;padding:24px;">No similar leads found</td></tr>';
      const btn = document.getElementById('pinAllSimilarBtn');
      if (btn) btn.style.display = 'none';
      return;
    }
    tbody.innerHTML = similar.map(s => {
      const data = getPayload(s);
      return `<tr style="cursor:pointer" data-lead-url="${esc('/leads/' + encodeURIComponent(s.lead_key))}">
        <td style="font-weight:600">${esc(s.business_name || data['Business Name'])}</td>
        <td>${esc(s.city_area || data['City/Area'])}</td>
        <td><span class="score ${scoreClass(+(s.last_lead_score || 0))}">${esc(s.last_lead_score || '--')}</span></td>
        <td><span class="badge badge-blue">${esc(s.similarity_level || '')} (${esc(s.similarity_score || 0)})</span></td>
        <td class="text-sm">${esc((s.similarity_reasons || []).join(', '))}</td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('[data-lead-url]').forEach(row => {
      row.addEventListener('click', () => { window.location.href = row.dataset.leadUrl; });
    });
  } catch (e) { console.error('Load similar error:', e); }
}

// ── AI Provider Toggle ────────────────────────────

function updateDetailModelDropdown(selectedModel) {
  const provider = document.getElementById('aiProviderToggle')?.value || 'OpenAI';
  const sel = document.getElementById('aiModelToggle');
  if (!sel) return;
  const models = DETAIL_AI_MODELS[provider] || [];
  sel.innerHTML = models.map(m =>
    `<option value="${m.value}">${m.label}</option>`
  ).join('');
  if (selectedModel && models.some(m => m.value === selectedModel)) {
    sel.value = selectedModel;
  }
}

function inferProviderFromModel(model) {
  const value = String(model || '').toLowerCase();
  if (value.startsWith('gpt') || value.includes('openai')) return 'OpenAI';
  if (value.includes('claude')) return 'Anthropic';
  return '';
}

function getSelectedAiConfig(defaultProvider = 'OpenAI') {
  const providerToggle = document.getElementById('aiProviderToggle');
  const modelToggle = document.getElementById('aiModelToggle');
  let provider = providerToggle?.value || inferProviderFromModel(modelToggle?.value) || defaultProvider;
  if (provider === 'Claude') provider = 'Anthropic';
  if (!DETAIL_AI_MODELS[provider]) provider = defaultProvider;

  let model = modelToggle?.value || '';
  const validModels = DETAIL_AI_MODELS[provider] || [];
  if (!model || !validModels.some(m => m.value === model)) {
    model = validModels[0]?.value || '';
  }

  return { ai_provider: provider, ai_model: model };
}

async function loadAiProviderDefault() {
  try {
    const s = await api('/api/settings');
    const toggle = document.getElementById('aiProviderToggle');
    const modelProvider = inferProviderFromModel(s.ai_model || '');
    const provider = modelProvider || s.ai_provider || 'OpenAI';
    if (toggle) {
      toggle.value = DETAIL_AI_MODELS[provider] ? provider : 'OpenAI';
    }
    updateDetailModelDropdown(s.ai_model || '');
  } catch (e) {
    updateDetailModelDropdown('');
  }
}

// ── Pinned Leads ──────────────────────────────────

async function checkPinStatus() {
  try {
    const res = await api('/api/leads/pinned-keys');
    const pinned = new Set(res.pinned_keys || []);
    isPinned = pinned.has(LEAD_KEY);
    updatePinButton();
  } catch (e) { console.error('Check pin status error:', e); }
}

function updatePinButton() {
  const btn = document.getElementById('pinToggleBtn');
  if (!btn) return;
  if (isPinned) {
    btn.textContent = '\u{1F4CC} Pinned';
    btn.classList.add('btn-primary');
    btn.classList.remove('btn-secondary');
  } else {
    btn.textContent = 'Pin';
    btn.classList.remove('btn-primary');
    btn.classList.add('btn-secondary');
  }
}

async function togglePin() {
  try {
    if (isPinned) {
      const res = await api('/api/leads/unpin', {
        method: 'POST',
        body: { lead_keys: [LEAD_KEY] }
      });
      isPinned = false;
      toast('Unpinned lead', 'success');
    } else {
      const res = await api('/api/leads/pin', {
        method: 'POST',
        body: { lead_keys: [LEAD_KEY] }
      });
      isPinned = true;
      toast('Pinned lead', 'success');
    }
    updatePinButton();
  } catch (err) { toast('Pin update failed', 'error'); }
}

async function pinAllSimilar() {
  try {
    const res = await api(`/api/leads/pin-similar/${encodeURIComponent(LEAD_KEY)}`, {
      method: 'POST'
    });
    toast(`Pinned ${res.pinned} similar lead${res.pinned !== 1 ? 's' : ''}`, 'success');
  } catch (err) { toast('Pin similar failed', 'error'); }
}

// ── Agent Review ─────────────────────────────────────

function renderAgentReview(review, status, model, updatedAt) {
  const panel = document.getElementById('agentReviewContent');
  const empty = document.getElementById('agentReviewEmpty');
  if (!panel || !review || !review.verdict) {
    if (empty) empty.style.display = '';
    if (panel) panel.style.display = 'none';
    return;
  }
  if (empty) empty.style.display = 'none';
  panel.style.display = '';

  const verdictColors = {
    high_opportunity: 'badge-green',
    medium_opportunity: 'badge-blue',
    low_opportunity: 'badge-yellow',
    unclear: 'badge-gray',
  };
  const actionColors = {
    surface: 'badge-green',
    review: 'badge-blue',
    suppress: 'badge-red',
  };

  const fields = [
    ['Verdict', `<span class="badge ${verdictColors[review.verdict] || 'badge-gray'}">${esc(review.verdict.replace(/_/g, ' '))}</span>`],
    ['Action', `<span class="badge ${actionColors[review.recommended_action] || 'badge-gray'}">${esc(review.recommended_action)}</span>`],
    ['Priority', esc(review.priority)],
    ['Suppress', review.suppress_opportunity ? '<span class="badge badge-red">Yes</span>' : 'No'],
    ['Best Pitch Angle', esc(review.best_pitch_angle)],
    ['Confidence', review.pitch_angle_confidence != null ? (review.pitch_angle_confidence * 100).toFixed(0) + '%' : '--'],
    ['Why Now', esc(review.why_now)],
    ['Summary', esc(review.human_summary)],
  ];

  const grid = document.getElementById('agentReviewGrid');
  if (grid) {
    grid.innerHTML = fields.map(([label, value]) => {
      const display = value || '<span class="text-muted">--</span>';
      return `<div class="detail-item"><div class="detail-label">${esc(label)}</div><div class="detail-value">${display}</div></div>`;
    }).join('');
  }

  const reasonsEl = document.getElementById('agentReviewReasons');
  if (reasonsEl && review.top_reasons && review.top_reasons.length) {
    reasonsEl.innerHTML = '<div class="detail-label" style="margin-bottom:4px">Top Reasons</div><ul style="margin:0;padding-left:1.25rem;color:var(--text-primary)">' +
      review.top_reasons.map(r => `<li class="text-sm">${esc(r)}</li>`).join('') + '</ul>';
  } else if (reasonsEl) {
    reasonsEl.innerHTML = '';
  }

  const risksEl = document.getElementById('agentReviewRisks');
  if (risksEl && review.risk_notes && review.risk_notes.length) {
    risksEl.innerHTML = '<div class="detail-label" style="margin-bottom:4px">Risk Notes</div><ul style="margin:0;padding-left:1.25rem;color:var(--warning)">' +
      review.risk_notes.map(r => `<li class="text-sm">${esc(r)}</li>`).join('') + '</ul>';
  } else if (risksEl) {
    risksEl.innerHTML = '';
  }

  const metaEl = document.getElementById('agentReviewMeta');
  if (metaEl) {
    const parts = [];
    if (status) parts.push(`Status: ${status}`);
    if (model) parts.push(`Model: ${model}`);
    if (updatedAt) parts.push(`Updated: ${updatedAt.replace('T', ' ').slice(0, 16)}`);
    metaEl.textContent = parts.join(' · ');
  }
}

// ── Outreach Export ─────────────────────────────────────

let outreachDraft = null;

function updateExportButton() {
  const btn = document.getElementById('btnExportOutlook');
  if (!btn) return;
  const draft = document.getElementById('wfDraft')?.value?.trim();
  const summary = document.getElementById('wfSummary')?.value?.trim();
  btn.disabled = !(draft || summary);
}

async function openOutreachPreview() {
  const btn = document.getElementById('btnExportOutlook');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Loading...';
  }
  try {
    const result = await api('/api/outreach/generate-draft', {
      method: 'POST',
      body: { lead_key: LEAD_KEY }
    });
    if (!result.ok) {
      toast(result.error || 'Failed to generate outreach draft', 'error');
      return;
    }
    outreachDraft = result.draft;

    // Populate modal
    document.getElementById('outreachTo').value = outreachDraft.recipient_email || '';
    document.getElementById('outreachSubject').value = outreachDraft.subject || '';
    document.getElementById('outreachBody').value = outreachDraft.body_plain || '';
    document.getElementById('outreachPreviewUrl').value = outreachDraft.preview_url || '';

    // Show hint if no email
    const hint = document.getElementById('outreachToHint');
    if (hint) {
      hint.textContent = outreachDraft.recipient_email ? '' : 'No email on file — you can enter one manually';
      hint.style.color = outreachDraft.recipient_email ? '' : 'var(--warning)';
    }

    // Clear errors
    const errEl = document.getElementById('outreachErrors');
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

    // Show modal
    document.getElementById('outreachModal').style.display = 'flex';
  } catch (err) {
    toast('Failed to prepare outreach draft', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = 'Export to Outlook';
    }
    updateExportButton();
  }
}

function closeOutreachModal() {
  document.getElementById('outreachModal').style.display = 'none';
}

async function doExportOutlook() {
  const btn = document.getElementById('btnDoExport');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Exporting...';
  }

  // Read edited values from the modal
  const draft = {
    ...(outreachDraft || {}),
    recipient_email: document.getElementById('outreachTo').value.trim(),
    subject: document.getElementById('outreachSubject').value.trim(),
    body_plain: document.getElementById('outreachBody').value.trim(),
    preview_url: document.getElementById('outreachPreviewUrl').value.trim(),
    lead_key: LEAD_KEY,
    business_name: currentLead?.business_name || '',
  };

  if (!draft.subject && !draft.body_plain) {
    const errEl = document.getElementById('outreachErrors');
    if (errEl) {
      errEl.textContent = 'Subject or body is required';
      errEl.style.display = 'block';
    }
    if (btn) { btn.disabled = false; btn.textContent = 'Open in Outlook'; }
    return;
  }

  try {
    const result = await api('/api/outreach/export-outlook', {
      method: 'POST',
      body: { draft }
    });
    if (result.ok) {
      toast(`Draft opened in Outlook (${result.method})`, 'success');
      closeOutreachModal();
    } else {
      const errEl = document.getElementById('outreachErrors');
      if (errEl) {
        errEl.textContent = result.error || 'Export failed';
        errEl.style.display = 'block';
        errEl.style.color = 'var(--danger)';
      }
      toast(result.error || 'Export failed', 'error');
    }
  } catch (err) {
    toast('Export failed: ' + err.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Open in Outlook'; }
  }
}

// ── Agent Review ─────────────────────────────────────

async function runAgentReview(force) {
  const btn = document.getElementById('btnAgentReview');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Reviewing...';
  }
  try {
    const result = await api('/api/ai/agent-review', {
      method: 'POST',
      body: { lead_key: LEAD_KEY, force: !!force },
    });
    if (result.ok || result.status === 'skipped') {
      if (result.status === 'cached') {
        renderAgentReview(result.review, result.status, result.model, result.review_updated_at || '');
        toast('Agent review loaded from cache', 'info');
      } else if (result.status === 'skipped') {
        renderAgentReview(result.review, result.status, result.model, '');
        toast('Review skipped: ' + (result.skip_reason || 'insufficient evidence'), 'info');
      } else {
        renderAgentReview(result.review, result.status, result.model, new Date().toISOString());
        toast('Agent review complete', 'success');
      }
    } else {
      toast(result.error || 'Agent review failed', 'error');
    }
  } catch (err) {
    toast('Agent review failed', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Agent Review';
    }
  }
}

// ── Website Package (Phase 6) ────────────────────────────────────

let wpBusy = false;
let wpGenerating = false;
let wpGenerationCanceling = false;
let wpPackageView = 'preview';
let wpAdvancedEditor = null;
let wpAdvancedEditorLoadedFor = '';
let wpAdvancedEditorStamp = '';
let wpMonacoLoaderPromise = null;
let wpAdvancedOriginalHtml = '';
let wpAdvancedDirty = false;
let wpAdvancedSaving = false;
let wpKnownSectionIds = [];
let wpDirtyGuardInstalled = false;
let wpAdvancedDecorations = [];
let wpAdvancedWordWrap = false;
let wpAdvancedMinimap = false;
let wpDesignBrief = null;
let wpDesignBriefLoaded = false;
let wpDesignBriefSaved = false;
let wpDesignBriefDirty = false;
let wpDesignBriefSaving = false;
let wpPreviewQaRunning = false;
let wpCurrentWebsitePackage = null;
let wpSelectedPageSections = [];
let wpSelectedPageSectionsPath = '';
let wpSelectedPageSectionsLoading = false;

function wpSetButtons({ scraping, generating, reporting, previewQa, hasScrape, hasMockup, hasReport }) {
  const bScr = document.getElementById('btnWpScrape');
  const bGen = document.getElementById('btnWpGenerate');
  const bRep = document.getElementById('btnWpReport');
  const bQa = document.getElementById('btnWpPreviewQa');
  const busy = !!(scraping || generating || reporting || previewQa || wpPreviewQaRunning);
  if (bScr) {
    bScr.disabled = busy;
    bScr.innerHTML = scraping
      ? '<span class="spinner"></span> Scraping...'
      : (hasScrape ? 'Re-scrape Website' : 'Scrape Website');
  }
  if (bGen) {
    bGen.classList.toggle('btn-danger', !!generating);
    bGen.classList.toggle('btn-primary', !generating);
    bGen.disabled = generating ? wpGenerationCanceling : (busy || !hasScrape);
    bGen.innerHTML = generating
      ? (wpGenerationCanceling
        ? '<span class="spinner"></span> Canceling...'
        : 'Cancel Generation')
      : (hasMockup ? 'Regenerate Site' : 'Generate Site');
  }
  if (bRep) {
    bRep.disabled = busy || !hasMockup;
    bRep.innerHTML = reporting
      ? '<span class="spinner"></span> Building Report...'
      : (hasReport ? 'Rebuild Report + Email' : 'Generate Report + Email');
  }
  if (bQa) {
    const running = !!(previewQa || wpPreviewQaRunning);
    bQa.disabled = busy || !hasMockup;
    bQa.innerHTML = running
      ? '<span class="spinner"></span> Running QA...'
      : 'Run Preview QA';
  }
  wpSetDesignBriefButtons();
}

function wpFmtDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString([], {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function wpRenderStatus(pkg) {
  const panel = document.getElementById('wpStatusPanel');
  if (!panel) return;

  const scr = pkg.scrape;
  const gen = pkg.generated_info;
  const generationError = pkg.generation_error;
  const rows = [];

  if (!scr) {
    rows.push('<div class="text-muted text-sm">No scrape on file. Click <b>Scrape Website</b> to pull this lead\'s current site.</div>');
  } else {
    const counts = scr.counts || {};
    const countParts = [
      `${counts.photos || 0} photo${counts.photos === 1 ? '' : 's'}`,
      `${counts.services || 0} services`,
      `${counts.phones || 0} phone${counts.phones === 1 ? '' : 's'}`,
      `${counts.emails || 0} email${counts.emails === 1 ? '' : 's'}`,
      `${counts.main_text_chars || 0} chars`,
    ].join(' · ');
    const url = scr.final_url || scr.source_url || '';
    const safeUrl = /^https?:\/\//i.test((url || '').trim()) ? url : '';
    const urlHtml = safeUrl
      ? `<a href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer">${esc(safeUrl)}</a>`
      : (url ? `<span class="text-muted">${esc(url)}</span>` : '<span class="text-muted">--</span>');
    rows.push(
      `<div class="detail-item"><div class="detail-label">Scraped URL</div><div class="detail-value">${urlHtml}</div></div>` +
      `<div class="detail-item"><div class="detail-label">HTTP Status</div><div class="detail-value">${esc(scr.status_code ?? '--')}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Assets</div><div class="detail-value">${esc(countParts)}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Scraped At</div><div class="detail-value">${esc(wpFmtDate(scr.saved_at))}</div></div>`
    );
  }

  if (gen) {
    const meta = gen.meta || {};
    const plan = gen.site_plan || {};
    const exportInfo = gen.multi_page_export || {};
    const exportManifest = exportInfo.manifest || {};
    const exportFiles = exportInfo.files || [];
    const kb = gen.bytes ? (gen.bytes / 1024).toFixed(1) + ' KB' : '--';
    const mode = meta.generation_mode || plan.mode || '--';
    const exportLinks = exportFiles.length
      ? exportFiles.slice(0, 6).map(f => {
        const safePath = String(f.path || f.filename || '')
          .split('/')
          .map(part => encodeURIComponent(part))
          .join('/');
        const href = `/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/files/${safePath}`;
        return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(f.filename || f.path)}</a>`;
      }).join('<br>')
      : '<span class="text-muted">No multi-page export</span>';
    rows.push(
      `<div class="detail-item"><div class="detail-label">Site Model</div><div class="detail-value">${esc(meta.model || '--')}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Category</div><div class="detail-value">${esc(meta.category || '--')}${meta.fallback_category ? ' <span class="badge badge-amber">fallback</span>' : ''}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Generation Mode</div><div class="detail-value">${esc(mode.replace(/_/g, ' '))}${meta.multi_page_export_enabled ? ' <span class="badge badge-amber">multi-page plan</span>' : ''}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Site Size</div><div class="detail-value">${esc(kb)}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Generated At</div><div class="detail-value">${esc(wpFmtDate(gen.generated_at))}</div></div>` +
      `<div class="detail-item"><div class="detail-label">Multi-page Export</div><div class="detail-value wp-review-links">${exportManifest.version ? `<span class="badge badge-green">v${esc(exportManifest.version)} ${esc((exportManifest.kind || 'export').replace(/_/g, ' '))}</span>${exportManifest.ai_generated_count != null ? ` <span class="badge badge-amber">${esc(exportManifest.ai_generated_count)} AI pages</span>` : ''}<br>` : ''}${exportLinks}</div></div>`
    );
  }

  if (generationError) {
    rows.push(
      `<div class="detail-item" style="grid-column:1/-1">` +
      `<div class="detail-label">Last Generation Attempt Failed</div>` +
      `<div class="detail-value" style="color:var(--danger)">` +
      `${esc(generationError.error || 'Generation failed before a site was saved.')}` +
      `</div>` +
      `<div class="text-muted text-sm" style="margin-top:0.35rem">` +
      `${esc([generationError.provider, generationError.model, generationError.stage, wpFmtDate(generationError.created_at)].filter(Boolean).join(' - '))}` +
      `</div></div>`
    );
  } else if (!gen && scr) {
    rows.push('<div class="detail-item" style="grid-column:1/-1"><div class="text-muted text-sm">Scrape ready. Click <b>Generate Site</b> to build the preview and any detected multi-page export.</div></div>');
  }

  panel.innerHTML = `<div class="detail-grid">${rows.join('')}</div>`;
}

function wpUpdateStudioLinks(pkg) {
  const link = document.getElementById('leadWebsiteStudioLink');
  const wrap = document.getElementById('leadWebsiteStudioLinkWrap');
  const generated = !!(pkg && pkg.generated);
  if (link) {
    link.href = `/website-studio/${encodeURIComponent(LEAD_KEY)}`;
    link.classList.toggle('disabled', !generated);
    link.setAttribute('aria-disabled', generated ? 'false' : 'true');
  }
  if (wrap) wrap.style.display = generated ? '' : 'none';
}

function wpChipList(items, emptyText = 'None found', limit = 14) {
  const values = (items || []).filter(Boolean).slice(0, limit);
  if (!values.length) return `<span class="text-muted">${esc(emptyText)}</span>`;
  return values.map(v => `<span class="wp-review-chip">${esc(v)}</span>`).join('');
}

function wpLinkList(items, emptyText = 'None found', limit = 8) {
  const values = (items || []).filter(Boolean).slice(0, limit);
  if (!values.length) return `<span class="text-muted">${esc(emptyText)}</span>`;
  return values.map(v => {
    const safe = /^https?:\/\//i.test(String(v || '').trim());
    return safe
      ? `<a href="${esc(v)}" target="_blank" rel="noopener noreferrer">${esc(v)}</a>`
      : `<span>${esc(v)}</span>`;
  }).join('<br>');
}

function wpSocialList(links) {
  const entries = Object.entries(links || {}).slice(0, 10);
  if (!entries.length) return '<span class="text-muted">None found</span>';
  return entries.map(([key, url]) => {
    const safe = /^https?:\/\//i.test(String(url || '').trim());
    const label = key.replace(/_/g, ' ');
    return safe
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`
      : `<span>${esc(label)}: ${esc(url)}</span>`;
  }).join(' &middot; ');
}

function wpCrawledPagesList(pages, errors) {
  const good = (pages || []).slice(0, 8);
  const bad = (errors || []).slice(0, 4);
  if (!good.length && !bad.length) return '<span class="text-muted">Homepage only</span>';
  const goodRows = good.map(p => {
    const url = p.url || '';
    const safe = /^https?:\/\//i.test(url);
    const link = safe
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(p.title || url)}</a>`
      : esc(p.title || url || 'Inner page');
    const bits = [
      p.status_code ? `HTTP ${p.status_code}` : '',
      p.text_chars != null ? `${p.text_chars} chars` : '',
    ].filter(Boolean).join(' · ');
    return `<li>${link}${bits ? ` <span class="text-muted text-sm">${esc(bits)}</span>` : ''}</li>`;
  }).join('');
  const badRows = bad.map(e =>
    `<li><span class="text-muted">${esc(e.url || 'Inner page')}</span> <span class="badge badge-amber">${esc(e.error || 'Skipped')}</span></li>`
  ).join('');
  return `<ul class="wp-review-list">${goodRows}${badRows}</ul>`;
}

function wpRenderScrapeReview(pkg) {
  const panel = document.getElementById('wpScrapeReviewPanel');
  if (!panel) return;
  const scr = pkg && pkg.scrape;
  if (!scr) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    return;
  }

  panel.style.display = '';
  const missing = scr.missing_fields || [];
  const missingHtml = missing.length
    ? missing.map(v => `<span class="badge badge-amber">${esc(v.replace(/_/g, ' '))}</span>`).join(' ')
    : '<span class="badge badge-green">Core fields found</span>';
  const photoLinks = wpLinkList(scr.photos, 'No photos found', 6);
  const mainText = scr.main_text_preview
    ? esc(scr.main_text_preview)
    : '<span class="text-muted">No main text extracted.</span>';

  panel.innerHTML = `
    <div class="wp-review-header">
      <div>
        <div class="detail-label">Scrape Review</div>
      <div class="text-muted text-sm">Review this evidence before generating the site.</div>
      </div>
      <div class="wp-review-missing">${missingHtml}</div>
    </div>
    <div class="wp-review-grid">
      <div class="detail-item"><div class="detail-label">Business</div><div class="detail-value">${esc(scr.business_name || '--')}</div></div>
      <div class="detail-item"><div class="detail-label">Title</div><div class="detail-value">${esc(scr.title || '--')}</div></div>
      <div class="detail-item"><div class="detail-label">HTTPS</div><div class="detail-value">${scr.has_https ? '<span class="badge badge-green">Yes</span>' : '<span class="badge badge-amber">No / unknown</span>'}</div></div>
      <div class="detail-item"><div class="detail-label">Robots</div><div class="detail-value">${scr.robots_allowed ? '<span class="badge badge-green">Allowed</span>' : '<span class="badge badge-red">Blocked</span>'}</div></div>
      <div class="detail-item"><div class="detail-label">Phones</div><div class="detail-value">${wpChipList(scr.phones, 'No phones found')}</div></div>
      <div class="detail-item"><div class="detail-label">Emails</div><div class="detail-value">${wpChipList(scr.emails, 'No emails found')}</div></div>
      <div class="detail-item"><div class="detail-label">Services / Nav</div><div class="detail-value">${wpChipList(scr.services, 'No services found', 20)}</div></div>
      <div class="detail-item"><div class="detail-label">Headings</div><div class="detail-value">${wpChipList(scr.headings, 'No headings found', 12)}</div></div>
      <div class="detail-item"><div class="detail-label">Tech Hints</div><div class="detail-value">${wpChipList(scr.tech_hints, 'No tech hints found', 12)}</div></div>
      <div class="detail-item"><div class="detail-label">Social</div><div class="detail-value">${wpSocialList(scr.social_links)}</div></div>
      <div class="detail-item"><div class="detail-label">Crawled Pages</div><div class="detail-value">${wpCrawledPagesList(scr.crawled_pages, scr.crawl_errors)}</div></div>
      <div class="detail-item"><div class="detail-label">Colors</div><div class="detail-value">${wpChipList(scr.colors, 'No colors found', 10)}</div></div>
      <div class="detail-item"><div class="detail-label">Fonts</div><div class="detail-value">${wpChipList(scr.fonts, 'No fonts found', 8)}</div></div>
      <div class="detail-item" style="grid-column:1/-1"><div class="detail-label">Photos</div><div class="detail-value wp-review-links">${photoLinks}</div></div>
      <div class="detail-item" style="grid-column:1/-1"><div class="detail-label">Main Text Preview</div><div class="detail-value wp-review-text">${mainText}</div></div>
    </div>
  `;
}

function wpDesignBriefSourceLabel(source, saved) {
  if (source === 'saved_user_approved') return 'Saved';
  if (source === 'saved_generated') return 'Generated';
  if (source === 'preview_from_scrape') return 'Preview';
  return saved ? 'Saved' : 'Preview';
}

function wpSetDesignBriefStatus(message, isError = false) {
  const el = document.getElementById('wpDesignBriefStatus');
  if (!el) return;
  el.textContent = message || '';
  el.style.color = isError ? 'var(--danger)' : 'var(--text-secondary)';
}

function wpSetDesignBriefButtons({ loading = false, saving = false } = {}) {
  const loadBtn = document.getElementById('btnWpBriefLoad');
  const refreshBtn = document.getElementById('btnWpBriefRefresh');
  const saveBtn = document.getElementById('btnWpBriefSave');
  const busy = wpBusy || loading || saving || wpDesignBriefSaving;
  if (loadBtn) {
    loadBtn.disabled = busy;
    loadBtn.innerHTML = loading ? '<span class="spinner"></span> Loading...' : 'Load Brief';
  }
  if (refreshBtn) refreshBtn.disabled = busy;
  if (saveBtn) {
    saveBtn.disabled = busy || !wpDesignBriefLoaded;
    saveBtn.innerHTML = (saving || wpDesignBriefSaving)
      ? '<span class="spinner"></span> Saving...'
      : (wpDesignBriefDirty ? 'Save Changes' : 'Save Brief');
  }
}

function wpRenderDesignBriefSummary(summary, brief) {
  const grid = document.getElementById('wpDesignBriefSummary');
  if (!grid) return;
  const exp = (brief && brief.experience_dna) || {};
  const creative = (brief && brief.creative_variation) || {};
  const siteDna = (brief && brief.site_dna) || {};
  const s = summary || {};
  const source = wpDesignBriefSourceLabel(s.source || '', !!s.exists);
  const approved = !!(s.approved_by_user || s.saved_in_website_studio);
  const rows = [
    ['Source', `<span class="badge ${approved ? 'badge-green' : 'badge-amber'}">${esc(source)}</span>`],
    ['Category', esc(s.category || siteDna.category || '--')],
    ['Experience', esc(s.archetype_label || exp.archetype_label || exp.archetype_key || '--')],
    ['Motion', esc(s.motion_level || exp.motion_level || '--')],
    ['Hero', esc(s.hero_system || creative.hero_system || '--')],
    ['Nav', esc(s.nav_system || creative.nav_system || '--')],
    ['Saved', s.saved_at ? esc(wpFmtDate(s.saved_at)) : '<span class="text-muted">Not saved</span>'],
    ['Generated', s.generated_at ? esc(wpFmtDate(s.generated_at)) : '<span class="text-muted">--</span>'],
  ];
  grid.innerHTML = rows.map(([label, value]) =>
    `<div class="detail-item"><div class="detail-label">${esc(label)}</div><div class="detail-value">${value}</div></div>`
  ).join('');
}

function wpMarkDesignBriefDirty() {
  if (!document.getElementById('wpDesignBriefEditor')) return;
  if (!wpDesignBriefLoaded) return;
  wpDesignBriefDirty = true;
  wpDesignBriefSaved = false;
  wpSetDesignBriefButtons();
  wpSetDesignBriefStatus('Unsaved brief changes.', false);
}

function wpRenderDesignBrief(result) {
  const card = document.getElementById('wpDesignBriefCard');
  const editor = document.getElementById('wpDesignBriefEditor');
  if (!card || !editor) return;
  card.style.display = '';
  wpDesignBrief = result && result.brief ? result.brief : null;
  wpDesignBriefLoaded = !!wpDesignBrief;
  wpDesignBriefSaved = !!(result && result.saved);
  wpDesignBriefDirty = false;
  if (!wpDesignBriefLoaded) {
    editor.value = '';
    wpRenderDesignBriefSummary(null, null);
    wpSetDesignBriefStatus('Scrape required.', false);
    wpSetDesignBriefButtons();
    return;
  }
  editor.value = JSON.stringify(wpDesignBrief, null, 2);
  wpRenderDesignBriefSummary(result.summary, wpDesignBrief);
  const label = wpDesignBriefSourceLabel(result.source, result.saved);
  wpSetDesignBriefStatus(`${label} design brief loaded.`, false);
  wpSetDesignBriefButtons();
}

async function wpLoadDesignBrief(options = {}) {
  const card = document.getElementById('wpDesignBriefCard');
  if (!card) return;
  const pkg = options.pkg || null;
  if (options.auto && wpDesignBriefLoaded && !options.refresh) return;
  if (options.auto && wpDesignBriefDirty && !options.force) return;
  if (options.auto && pkg && !pkg.scraped && !pkg.design_brief) {
    wpRenderDesignBrief(null);
    return;
  }
  if (wpDesignBriefDirty && options.force) {
    const ok = window.confirm('Discard unsaved design brief changes?');
    if (!ok) return;
  }

  const query = options.refresh ? '?refresh=true' : '';
  wpSetDesignBriefButtons({ loading: true });
  wpSetDesignBriefStatus(options.refresh ? 'Rebuilding design brief...' : 'Loading design brief...', false);
  try {
    const result = await api(`/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/design-brief${query}`);
    if (!result.ok) throw new Error(result.error || 'Design brief failed');
    wpRenderDesignBrief(result);
  } catch (err) {
    wpDesignBriefLoaded = false;
    wpDesignBriefSaved = false;
    wpDesignBriefDirty = false;
    wpSetDesignBriefStatus(err.message || 'Could not load design brief.', true);
    wpSetDesignBriefButtons();
  }
}

async function wpSaveDesignBrief(options = {}) {
  const editor = document.getElementById('wpDesignBriefEditor');
  if (!editor) return true;
  if (!wpDesignBriefLoaded && !editor.value.trim()) {
    wpSetDesignBriefStatus('Load or rebuild a brief first.', true);
    return false;
  }
  let brief;
  try {
    brief = JSON.parse(editor.value);
  } catch (err) {
    wpSetDesignBriefStatus(`JSON error: ${err.message}`, true);
    if (!options.silent) toast('Design brief JSON is invalid', 'error');
    return false;
  }

  wpDesignBriefSaving = true;
  wpSetDesignBriefButtons({ saving: true });
  wpSetDesignBriefStatus('Saving design brief...', false);
  try {
    const result = await api(`/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/design-brief`, {
      method: 'POST',
      body: { brief },
    });
    if (!result.ok) throw new Error(result.error || 'Save failed');
    wpRenderDesignBrief(result);
    if (!options.silent) toast('Design brief saved', 'success');
    return true;
  } catch (err) {
    wpSetDesignBriefStatus(err.message || 'Could not save design brief.', true);
    if (!options.silent) toast('Design brief save failed', 'error');
    return false;
  } finally {
    wpDesignBriefSaving = false;
    wpSetDesignBriefButtons();
  }
}

function wpRenderValidation(report) {
  const card = document.getElementById('wpValidationCard');
  const badge = document.getElementById('wpValidationBadge');
  const grid = document.getElementById('wpValidationGrid');
  const issuesEl = document.getElementById('wpValidationIssues');
  if (!card || !badge || !grid || !issuesEl) return;

  if (!report) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';

  const passed = !!report.passed;
  badge.innerHTML = passed
    ? '<span class="badge badge-green">Passed</span>'
    : '<span class="badge badge-red">Failed</span>';

  const runs = report.tool_runs || {};
  grid.innerHTML =
    `<div class="detail-item"><div class="detail-label">Errors</div><div class="detail-value">${esc(report.error_count ?? 0)}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Warnings</div><div class="detail-value">${esc(report.warning_count ?? 0)}</div></div>` +
    `<div class="detail-item"><div class="detail-label">htmlhint</div><div class="detail-value">${esc(runs.htmlhint || '--')}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Structure</div><div class="detail-value">${esc(runs.structure || '--')}</div></div>` +
    `<div class="detail-item"><div class="detail-label">A11y</div><div class="detail-value">${esc(runs.a11y || '--')}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Design Contract</div><div class="detail-value">${esc(runs.design_contract || '--')}</div></div>`;

  const issues = (report.issues || []).slice(0, 200);
  if (!issues.length) {
    issuesEl.innerHTML = '<div class="text-muted text-sm">No issues reported.</div>';
    return;
  }
  const sevBadge = (sev) => ({
    error: 'badge-red',
    warning: 'badge-amber',
    info: 'badge-gray',
  }[sev] || 'badge-gray');
  const rows = issues.map(i => {
    const line = (i.line != null && i.line > 0) ? ` <span class="text-muted text-sm">line ${esc(i.line)}</span>` : '';
    return `<li class="text-sm" style="margin-bottom:4px">
      <span class="badge ${sevBadge(i.severity)}">${esc(i.severity)}</span>
      <span class="text-muted">${esc(i.source)}/${esc(i.rule)}</span>${line}
      <div style="margin-left:0.5rem">${esc(i.message || '')}</div>
    </li>`;
  }).join('');
  const extraCount = (report.issues || []).length - issues.length;
  const extra = extraCount > 0
    ? `<div class="text-muted text-sm" style="margin-top:4px">(+${extraCount} more omitted)</div>`
    : '';
  issuesEl.innerHTML = `<div class="detail-label" style="margin-bottom:4px">Issues</div><ul style="margin:0;padding-left:1.25rem">${rows}</ul>${extra}`;
}

function wpGeneratedFileUrl(assetPath) {
  const parts = String(assetPath || '')
    .split(/[\\/]+/)
    .filter(part => part && part !== '.' && part !== '..');
  if (!parts.length) return '#';
  const safePath = parts.map(part => encodeURIComponent(part)).join('/');
  return `/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/files/${safePath}`;
}

function wpRenderPreviewQa(report, hasMockup) {
  const card = document.getElementById('wpPreviewQaCard');
  const badge = document.getElementById('wpPreviewQaBadge');
  const grid = document.getElementById('wpPreviewQaGrid');
  const screensEl = document.getElementById('wpPreviewQaScreens');
  const issuesEl = document.getElementById('wpPreviewQaIssues');
  if (!card || !badge || !grid || !screensEl || !issuesEl) return;

  if (!hasMockup) {
    card.style.display = 'none';
    grid.innerHTML = '';
    screensEl.innerHTML = '';
    issuesEl.innerHTML = '';
    badge.innerHTML = '';
    return;
  }

  card.style.display = wpPackageView === 'preview' ? '' : 'none';
  if (!report) {
    badge.innerHTML = '<span class="badge badge-gray">Not Run</span>';
    grid.innerHTML =
      '<div class="detail-item" style="grid-column:1/-1"><div class="text-muted text-sm">Run preview QA to capture desktop/mobile screenshots and check for blank pages, overflow, console errors, and motion runtime problems.</div></div>';
    screensEl.innerHTML = '';
    issuesEl.innerHTML = '';
    return;
  }

  const issues = Array.isArray(report.issues) ? report.issues : [];
  const errorCount = issues.filter(i => i && i.severity === 'error').length;
  const warningCount = issues.filter(i => i && i.severity === 'warning').length;
  const status = String(report.status || (report.ok ? 'completed' : 'failed'));
  const runs = report.tool_runs || {};
  let badgeClass = 'badge-gray';
  let badgeText = 'Unknown';
  if (status === 'skipped') {
    badgeText = 'Skipped';
  } else if (!report.ok || report.passed === false) {
    badgeClass = 'badge-red';
    badgeText = 'Failed';
  } else if (warningCount) {
    badgeClass = 'badge-amber';
    badgeText = 'Passed with Warnings';
  } else {
    badgeClass = 'badge-green';
    badgeText = 'Passed';
  }
  badge.innerHTML = `<span class="badge ${badgeClass}">${esc(badgeText)}</span>`;

  const viewports = Array.isArray(report.viewports) ? report.viewports : [];
  const qaDisplayText = (value, fallback = '--') => {
    const text = String(value || fallback)
      .replace(/[\u0080-\uFFFF]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return text.length > 500 ? `${text.slice(0, 497)}...` : text;
  };
  grid.innerHTML =
    `<div class="detail-item"><div class="detail-label">Status</div><div class="detail-value">${esc(status.replace(/_/g, ' '))}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Created</div><div class="detail-value">${esc(wpFmtDate(report.created_at) || '--')}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Desktop/Mobile</div><div class="detail-value">${esc(viewports.length)} viewport${viewports.length === 1 ? '' : 's'}</div></div>` +
    `<div class="detail-item"><div class="detail-label">Issues</div><div class="detail-value">${esc(errorCount)} error${errorCount === 1 ? '' : 's'} &middot; ${esc(warningCount)} warning${warningCount === 1 ? '' : 's'}</div></div>` +
    `<div class="detail-item" style="grid-column:1/-1"><div class="detail-label">Playwright</div><div class="detail-value">${esc(qaDisplayText(runs.playwright))}</div></div>`;

  const shots = viewports
    .filter(v => v && v.screenshot)
    .map(v => {
      const metrics = v.metrics || {};
      const href = wpGeneratedFileUrl(v.screenshot);
      const overflow = metrics.horizontal_overflow_px ?? 0;
      const runtime = metrics.runtime_attr_count
        ? (metrics.runtime_loaded ? 'runtime loaded' : 'runtime not loaded')
        : 'no runtime attrs';
      return `<div class="wp-preview-qa-shot">
        <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">
          <img src="${esc(href)}" alt="${esc(v.name || 'viewport')} preview screenshot" loading="lazy">
        </a>
        <div class="wp-preview-qa-shot-meta">
          <div class="detail-label">${esc(v.name || 'Viewport')}</div>
          <div class="text-sm">${esc(v.width || metrics.viewport_width || '--')} &times; ${esc(v.height || metrics.viewport_height || '--')} &middot; overflow ${esc(overflow)}px &middot; ${esc(runtime)}</div>
        </div>
      </div>`;
    }).join('');
  screensEl.innerHTML = shots || '';

  if (!issues.length) {
    issuesEl.innerHTML = '<div class="text-muted text-sm">No issues reported.</div>';
    return;
  }
  const sevBadge = (sev) => ({
    error: 'badge-red',
    warning: 'badge-amber',
    info: 'badge-gray',
  }[sev] || 'badge-gray');
  const rows = issues.slice(0, 200).map(i => {
    const source = [i.source, i.rule].filter(Boolean).join('/');
    const viewport = i.viewport ? ` <span class="text-muted text-sm">${esc(i.viewport)}</span>` : '';
    return `<li class="text-sm" style="margin-bottom:4px">
      <span class="badge ${sevBadge(i.severity)}">${esc(i.severity || 'info')}</span>
      <span class="text-muted">${esc(source || 'preview_qa')}</span>${viewport}
      <div style="margin-left:0.5rem">${esc(qaDisplayText(i.message, ''))}</div>
    </li>`;
  }).join('');
  const extraCount = issues.length - Math.min(issues.length, 200);
  const extra = extraCount > 0
    ? `<div class="text-muted text-sm" style="margin-top:4px">(+${extraCount} more omitted)</div>`
    : '';
  issuesEl.innerHTML = `<div class="detail-label" style="margin-bottom:4px">Issues</div><ul style="margin:0;padding-left:1.25rem">${rows}</ul>${extra}`;
}

function wpSetEditBusy(editing) {
  const btn = document.getElementById('btnWpEditSection');
  const restoreBtn = document.getElementById('btnWpRestoreBackup');
  const sel = document.getElementById('wpEditSection');
  const versionSel = document.getElementById('wpVersionSelect');
  const colorSel = document.getElementById('wpEditColorMode');
  const ta = document.getElementById('wpEditInstruction');
  if (btn) {
    btn.disabled = !!editing || wpBusy;
    btn.innerHTML = editing
      ? '<span class="spinner"></span> Applying...'
      : 'Apply AI Edit';
  }
  if (restoreBtn) restoreBtn.disabled = !!editing || wpBusy || restoreBtn.dataset.hasBackup !== 'true';
  if (sel) sel.disabled = !!editing || wpBusy;
  if (versionSel) versionSel.disabled = !!editing || wpBusy || versionSel.options.length <= 1;
  if (colorSel) colorSel.disabled = !!editing || wpBusy;
  if (ta) ta.disabled = !!editing || wpBusy;
}

function wpPreviewUrl(sectionId) {
  const params = new URLSearchParams({ v: String(Date.now()) });
  if (sectionId) params.set('highlight', sectionId);
  return `/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/mockup?${params.toString()}`;
}

function wpGeneratedPreviewUrl(path) {
  const safePath = String(path || '')
    .split('/')
    .filter(Boolean)
    .map(part => encodeURIComponent(part))
    .join('/');
  if (!safePath) return wpPreviewUrl('');
  return `/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/files/${safePath}?v=${Date.now()}`;
}

function wpSelectedPreviewPath() {
  const sel = document.getElementById('wpPreviewPageSelect');
  return (sel && sel.value) || '';
}

function wpCurrentPreviewUrl() {
  const selectedPath = wpSelectedPreviewPath();
  if (selectedPath) return wpGeneratedPreviewUrl(selectedPath);
  return wpPreviewUrl(wpSelectedSectionId());
}

function wpMockupSourceUrl() {
  const params = new URLSearchParams({ v: String(Date.now()) });
  return `/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/mockup?${params.toString()}`;
}

function wpAdvancedSourceUrl() {
  const selectedPath = wpSelectedPreviewPath();
  return selectedPath ? wpGeneratedPreviewUrl(selectedPath) : wpMockupSourceUrl();
}

function wpSelectedSectionId() {
  const sel = document.getElementById('wpEditSection');
  return (sel && sel.value) || '';
}

function wpRefreshPreviewHighlight() {
  const frame = document.getElementById('wpPreviewFrame');
  const link = document.getElementById('wpOpenTab');
  const card = document.getElementById('wpPreviewCard');
  if (!frame || (card && card.style.display === 'none')) return;
  const url = wpCurrentPreviewUrl();
  frame.src = url;
  if (link) link.href = url;
}

function wpSelectPreviewPage() {
  wpRefreshPreviewHighlight();
  wpRenderSectionEditor(wpCurrentWebsitePackage);
  if (wpPackageView === 'html') {
    wpRefreshAdvancedHtml({ forceHidden: true });
  }
}

function wpExtractSectionsFromHtml(html) {
  const sections = [];
  const seen = new Set();
  const re = /data-summit-section\s*=\s*["']([^"']+)["'][^>]*(?:data-summit-label\s*=\s*["']([^"']+)["'])?/gi;
  let match;
  while ((match = re.exec(html || '')) !== null) {
    const id = (match[1] || '').trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    sections.push({ id, label: (match[2] || id).trim() });
  }
  return sections;
}

async function wpLoadSelectedPageSections(path) {
  if (!path) {
    wpSelectedPageSections = [];
    wpSelectedPageSectionsPath = '';
    wpSelectedPageSectionsLoading = false;
    return [];
  }
  if (wpSelectedPageSectionsPath === path && !wpSelectedPageSectionsLoading) {
    return wpSelectedPageSections;
  }
  wpSelectedPageSectionsLoading = true;
  wpSelectedPageSectionsPath = path;
  try {
    const response = await fetch(wpGeneratedPreviewUrl(path), {
      headers: { 'Accept': 'text/html' },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('Unable to load page source');
    const html = await response.text();
    wpSelectedPageSections = wpExtractSectionsFromHtml(html);
  } catch (err) {
    wpSelectedPageSections = [];
  } finally {
    wpSelectedPageSectionsLoading = false;
  }
  return wpSelectedPageSections;
}

function wpFindSectionOffset(html, sectionId) {
  if (!html || !sectionId) return -1;
  const escaped = sectionId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`\\bdata-summit-section\\s*=\\s*["']${escaped}["']`, 'i');
  const match = re.exec(html);
  return match ? match.index : -1;
}

function wpJumpAdvancedHtmlToSection(sectionId) {
  if (!wpAdvancedEditor || !sectionId) return false;
  const model = wpAdvancedEditor.getModel();
  if (!model) return false;
  const html = model.getValue();
  const offset = wpFindSectionOffset(html, sectionId);
  if (offset < 0) return false;

  const pos = model.getPositionAt(offset);
  const line = pos.lineNumber;
  const maxLine = model.getLineCount();
  const endLine = Math.min(maxLine, line + 10);
  const monaco = window.monaco;
  if (monaco && monaco.Range) {
    wpAdvancedDecorations = wpAdvancedEditor.deltaDecorations(
      wpAdvancedDecorations,
      [{
        range: new monaco.Range(line, 1, endLine, model.getLineMaxColumn(endLine)),
        options: {
          isWholeLine: true,
          className: 'wp-code-section-highlight',
          overviewRuler: {
            color: '#f59e0b',
            position: monaco.editor.OverviewRulerLane.Center,
          },
        },
      }]
    );
  }
  wpAdvancedEditor.revealLineInCenter(line);
  wpAdvancedEditor.setPosition(pos);
  wpAdvancedEditor.focus();
  return true;
}

function wpSyncSelectedSection(options = {}) {
  wpRefreshPreviewHighlight();
  const sectionId = wpSelectedSectionId();
  if (!sectionId) return;
  if (options.openHtml) wpSetPackageView('html');
  if (wpPackageView === 'html' || options.jump) {
    const jumped = wpJumpAdvancedHtmlToSection(sectionId);
    if (!jumped && !wpAdvancedEditorLoadedFor) {
      wpRefreshAdvancedHtml({ forceHidden: true }).then(() => {
        wpJumpAdvancedHtmlToSection(sectionId);
      });
    }
  }
}

function wpSetPackageView(view) {
  wpPackageView = view === 'html' ? 'html' : 'preview';
  const previewBtn = document.getElementById('wpPreviewTabBtn');
  const htmlBtn = document.getElementById('wpAdvancedHtmlTabBtn');
  const previewCard = document.getElementById('wpPreviewCard');
  const previewQaCard = document.getElementById('wpPreviewQaCard');
  const htmlCard = document.getElementById('wpAdvancedHtmlCard');
  if (previewBtn) previewBtn.classList.toggle('active', wpPackageView === 'preview');
  if (htmlBtn) htmlBtn.classList.toggle('active', wpPackageView === 'html');
  if (previewCard) previewCard.style.display = wpPackageView === 'preview' ? '' : 'none';
  if (previewQaCard) previewQaCard.style.display = wpPackageView === 'preview' ? '' : 'none';
  if (htmlCard) htmlCard.style.display = wpPackageView === 'html' ? '' : 'none';
  if (wpPackageView === 'html') {
    wpRefreshAdvancedHtml({ onlyIfEmpty: true });
    if (wpAdvancedEditor) {
      setTimeout(() => {
        wpAdvancedEditor.layout();
        wpJumpAdvancedHtmlToSection(wpSelectedSectionId());
      }, 0);
    }
  }
}

function wpSetAdvancedHtmlStatus(message, isError) {
  const status = document.getElementById('wpAdvancedHtmlStatus');
  if (!status) return;
  status.textContent = message || '';
  status.style.color = isError ? 'var(--danger)' : '';
}

function wpSetAdvancedHtmlDirty(dirty) {
  wpAdvancedDirty = !!dirty;
  const btn = document.getElementById('btnWpSaveHtml');
  if (btn) {
    btn.disabled = wpAdvancedSaving || wpBusy || !wpAdvancedDirty;
    btn.innerHTML = wpAdvancedSaving
      ? '<span class="spinner"></span> Saving...'
      : 'Save HTML';
  }
}

function wpCurrentAdvancedHtml() {
  if (wpAdvancedEditor) return wpAdvancedEditor.getValue();
  const fallback = document.getElementById('wpAdvancedHtmlFallback');
  return fallback ? fallback.value : '';
}

function wpExtractSectionIds(html) {
  const ids = [];
  const re = /\bdata-summit-section\s*=\s*["']([^"']+)["']/gi;
  let match;
  while ((match = re.exec(html || '')) !== null) {
    if (match[1] && !ids.includes(match[1])) ids.push(match[1]);
  }
  return ids;
}

function wpMissingKnownSectionIds(html) {
  const nextIds = wpExtractSectionIds(html);
  return wpKnownSectionIds.filter(id => !nextIds.includes(id));
}

function wpInstallDirtyGuard() {
  if (wpDirtyGuardInstalled) return;
  wpDirtyGuardInstalled = true;
  window.addEventListener('beforeunload', (event) => {
    if (!wpAdvancedDirty && !wpDesignBriefDirty) return;
    event.preventDefault();
    event.returnValue = '';
  });

  document.addEventListener('click', (event) => {
    const tab = event.target.closest && event.target.closest('#leadContent .tab-btn[data-tab]');
    if (!tab || (!wpAdvancedDirty && !wpDesignBriefDirty)) return;
    if (tab.dataset.tab === 'tabWebsitePackage') return;
    const ok = window.confirm('Leave Website Package with unsaved changes?');
    if (!ok) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
}

function wpSetAdvancedHtmlFallback(html) {
  const editorEl = document.getElementById('wpAdvancedHtmlEditor');
  const fallback = document.getElementById('wpAdvancedHtmlFallback');
  if (editorEl) editorEl.classList.add('is-hidden');
  if (fallback) {
    fallback.style.display = 'block';
    fallback.readOnly = false;
    fallback.value = html || '';
    fallback.oninput = () => wpSetAdvancedHtmlDirty(fallback.value !== wpAdvancedOriginalHtml);
  }
}

function wpLoadMonaco() {
  if (window.monaco && window.monaco.editor) return Promise.resolve(window.monaco);
  if (wpMonacoLoaderPromise) return wpMonacoLoaderPromise;

  wpMonacoLoaderPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-summit-monaco-loader="true"]');
    const finish = () => {
      if (!window.require) {
        reject(new Error('Monaco loader unavailable'));
        return;
      }
      window.require.config({
        paths: {
          vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.49.0/min/vs',
        },
      });
      window.require(['vs/editor/editor.main'], () => resolve(window.monaco), reject);
    };
    if (existing) {
      existing.addEventListener('load', finish, { once: true });
      existing.addEventListener('error', reject, { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.49.0/min/vs/loader.js';
    script.async = true;
    script.dataset.summitMonacoLoader = 'true';
    script.onload = finish;
    script.onerror = () => reject(new Error('Could not load Monaco'));
    document.head.appendChild(script);
  });
  return wpMonacoLoaderPromise;
}

async function wpSetAdvancedHtmlValue(html) {
  const editorEl = document.getElementById('wpAdvancedHtmlEditor');
  const fallback = document.getElementById('wpAdvancedHtmlFallback');
  if (!editorEl) return;

  try {
    const monaco = await wpLoadMonaco();
    editorEl.classList.remove('is-hidden');
    if (fallback) fallback.style.display = 'none';
    if (!wpAdvancedEditor) {
      wpAdvancedEditor = monaco.editor.create(editorEl, {
        value: html,
        language: 'html',
        theme: 'vs-dark',
        readOnly: false,
        automaticLayout: true,
        minimap: { enabled: wpAdvancedMinimap },
        scrollBeyondLastLine: false,
        wordWrap: wpAdvancedWordWrap ? 'on' : 'off',
        tabSize: 2,
      });
      wpAdvancedEditor.onDidChangeModelContent(() => {
        wpSetAdvancedHtmlDirty(wpAdvancedEditor.getValue() !== wpAdvancedOriginalHtml);
      });
    } else {
      wpAdvancedEditor.setValue(html);
      wpAdvancedEditor.layout();
    }
    wpUpdateAdvancedEditorToggles();
  } catch (err) {
    console.warn('Monaco load failed:', err);
    wpSetAdvancedHtmlFallback(html);
    wpSetAdvancedHtmlStatus('Monaco could not load, using fallback HTML editor.', true);
  }
}

function wpUpdateAdvancedEditorToggles() {
  const wrapBtn = document.getElementById('btnWpWrapHtml');
  const minimapBtn = document.getElementById('btnWpMinimapHtml');
  if (wrapBtn) {
    wrapBtn.textContent = wpAdvancedWordWrap ? 'Wrap On' : 'Wrap Off';
    wrapBtn.classList.toggle('btn-primary', wpAdvancedWordWrap);
    wrapBtn.classList.toggle('btn-secondary', !wpAdvancedWordWrap);
  }
  if (minimapBtn) {
    minimapBtn.textContent = wpAdvancedMinimap ? 'Minimap On' : 'Minimap Off';
    minimapBtn.classList.toggle('btn-primary', wpAdvancedMinimap);
    minimapBtn.classList.toggle('btn-secondary', !wpAdvancedMinimap);
  }
}

function wpToggleAdvancedWordWrap() {
  wpAdvancedWordWrap = !wpAdvancedWordWrap;
  if (wpAdvancedEditor) {
    wpAdvancedEditor.updateOptions({ wordWrap: wpAdvancedWordWrap ? 'on' : 'off' });
  }
  wpUpdateAdvancedEditorToggles();
}

function wpToggleAdvancedMinimap() {
  wpAdvancedMinimap = !wpAdvancedMinimap;
  if (wpAdvancedEditor) {
    wpAdvancedEditor.updateOptions({ minimap: { enabled: wpAdvancedMinimap } });
  }
  wpUpdateAdvancedEditorToggles();
}

function wpFindAdvancedHtml() {
  if (!wpAdvancedEditor) {
    wpSetPackageView('html');
    return;
  }
  wpAdvancedEditor.getAction('actions.find')?.run();
  wpAdvancedEditor.focus();
}

function wpFormatAdvancedHtml() {
  if (!wpAdvancedEditor) {
    toast('Open Advanced HTML first', 'error');
    return;
  }
  const action = wpAdvancedEditor.getAction('editor.action.formatDocument');
  if (!action) {
    toast('Formatter unavailable', 'error');
    return;
  }
  Promise.resolve(action.run()).then(() => {
    wpSetAdvancedHtmlStatus('Formatted HTML. Review and save when ready.', false);
  }).catch(() => {
    toast('Format failed', 'error');
  });
}

async function wpRefreshAdvancedHtml(options = {}) {
  const card = document.getElementById('wpAdvancedHtmlCard');
  if (options.onlyIfEmpty && wpAdvancedEditorLoadedFor) return;
  if (card && card.style.display === 'none' && !options.forceHidden) return;
  if (wpAdvancedDirty && !options.afterSave) {
    const ok = window.confirm('Discard unsaved HTML changes and reload the current site source?');
    if (!ok) return;
  }

  const btn = document.getElementById('btnWpRefreshHtml');
  const sourceUrl = wpAdvancedSourceUrl();
  const openLink = document.getElementById('wpOpenHtmlTab');
  if (openLink) openLink.href = sourceUrl;
  if (btn) btn.disabled = true;
  wpSetAdvancedHtmlStatus('Loading current site HTML...', false);
  try {
    const resp = await fetch(sourceUrl, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await resp.text();
    wpAdvancedOriginalHtml = html;
    await wpSetAdvancedHtmlValue(html);
    wpAdvancedEditorLoadedFor = sourceUrl;
    wpSetAdvancedHtmlDirty(false);
    wpSyncSelectedSection({ jump: true });
    const lineCount = html ? html.split(/\r\n|\r|\n/).length : 0;
    wpSetAdvancedHtmlStatus(`Source loaded (${lineCount} lines).`, false);
  } catch (err) {
    wpSetAdvancedHtmlStatus('Could not load site HTML. Generate a site first, then refresh.', true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function wpSaveAdvancedHtml() {
  if (wpBusy || wpAdvancedSaving) return;
  const html = wpCurrentAdvancedHtml();
  if (!html.trim()) {
    toast('HTML source is required', 'error');
    return;
  }
  const missingIds = wpMissingKnownSectionIds(html);
  if (missingIds.length) {
    const ok = window.confirm(
      `This save removes ${missingIds.length} editable section marker${missingIds.length === 1 ? '' : 's'}: ${missingIds.join(', ')}. AI section edits may stop working for those sections. Save anyway?`
    );
    if (!ok) return;
  }

  wpBusy = true;
  wpAdvancedSaving = true;
  wpSetAdvancedHtmlDirty(wpAdvancedDirty);
  wpSetAdvancedHtmlStatus('Saving HTML and running validation...', false);
  try {
    const result = await api('/api/ai/save-website-mockup', {
      method: 'POST',
      body: {
        lead_key: LEAD_KEY,
        html,
        target_path: wpSelectedPreviewPath(),
      },
    });
    if (result.ok) {
      wpAdvancedOriginalHtml = html;
      wpAdvancedEditorLoadedFor = '';
      wpSetAdvancedHtmlDirty(false);
      const passed = result.validation?.passed ? 'passed validation' : 'saved with validation warnings';
      const markerWarning = result.marker_warning ? ` ${result.marker_warning}` : '';
      toast(`HTML saved, ${passed}`, result.marker_warning ? 'info' : 'success');
      const validationBits = result.validation
        ? ` Validation: ${result.validation.error_count || 0} errors, ${result.validation.warning_count || 0} warnings.`
        : '';
      const savedStatus = `Saved backup ${result.backup_file || ''}.${validationBits}${markerWarning}`.trim();
      const savedStatusIsError = !!result.marker_warning || !result.validation?.passed;
      await loadWebsitePackage();
      wpRefreshPreviewHighlight();
      await wpRefreshAdvancedHtml({ afterSave: true });
      wpSetAdvancedHtmlStatus(savedStatus, savedStatusIsError);
    } else {
      toast(result.error || 'HTML save failed', 'error');
      wpSetAdvancedHtmlStatus(result.error || 'HTML save failed.', true);
    }
  } catch (err) {
    toast('HTML save failed', 'error');
    wpSetAdvancedHtmlStatus('HTML save failed.', true);
  } finally {
    wpAdvancedSaving = false;
    wpBusy = false;
    wpSetAdvancedHtmlDirty(wpAdvancedDirty);
  }
}

async function wpRenderSectionEditor(pkg) {
  const card = document.getElementById('wpEditCard');
  const sel = document.getElementById('wpEditSection');
  const restoreBtn = document.getElementById('btnWpRestoreBackup');
  const versionSel = document.getElementById('wpVersionSelect');
  const status = document.getElementById('wpEditStatus');
  if (!card || !sel) return;
  if (!pkg) {
    card.style.display = 'none';
    return;
  }

  const selectedPath = wpSelectedPreviewPath();
  const editingExportPage = !!selectedPath;
  const sections = editingExportPage
    ? await wpLoadSelectedPageSections(selectedPath)
    : ((pkg.edit_manifest && pkg.edit_manifest.sections) || []);
  const versions = pkg.versions || [];
  wpKnownSectionIds = sections.map(s => s.id).filter(Boolean);
  if (restoreBtn) restoreBtn.dataset.hasBackup = (!editingExportPage && versions.length) ? 'true' : 'false';
  if (versionSel) {
    versionSel.disabled = wpBusy || editingExportPage || !versions.length;
    versionSel.innerHTML = versions.length
      ? '<option value="">Latest backup</option>' + versions.slice().reverse().map(v => {
          const typeLabel = ({
            ai_section_edit: 'AI edit',
            manual_save: 'Manual save',
            restore_checkpoint: 'Restore checkpoint',
          }[v.edit_type] || '').trim();
          const labelParts = [v.file || 'backup'];
          if (typeLabel) labelParts.push(typeLabel);
          if (v.section_id) labelParts.push(v.section_id);
          if (v.reason) labelParts.push(v.reason);
          if (v.created_at) labelParts.push(wpFmtDate(v.created_at));
          return `<option value="${esc(v.file || '')}">${esc(labelParts.join(' - '))}</option>`;
        }).join('')
      : '<option value="">No backups</option>';
    versionSel.onchange = () => {
      const btn = document.getElementById('btnWpRestoreBackup');
      if (btn) btn.textContent = versionSel.value ? 'Restore Selected Backup' : 'Restore Last Backup';
    };
  }
  if (!pkg.generated) {
    card.style.display = 'none';
    return;
  }

  card.style.display = '';
  if (!sections.length) {
    sel.innerHTML = '';
    sel.disabled = true;
    const btn = document.getElementById('btnWpEditSection');
    if (btn) btn.disabled = true;
    if (restoreBtn) restoreBtn.disabled = wpBusy || restoreBtn.dataset.hasBackup !== 'true';
    if (versionSel) versionSel.disabled = wpBusy || editingExportPage || !versions.length;
    if (status) {
      status.textContent = editingExportPage
        ? 'No editable sections found on the selected page. Regenerate the site to add section markers.'
        : 'No editable sections found. Regenerate the site to add section markers.';
    }
    return;
  }

  const current = sel.value;
  sel.innerHTML = sections.map(s => {
    const label = s.label || s.id;
    return `<option value="${esc(s.id)}">${esc(label)}</option>`;
  }).join('');
  if (current && sections.some(s => s.id === current)) {
    sel.value = current;
  }
  sel.onchange = () => wpSyncSelectedSection({ jump: true });

  if (status) {
    const count = sections.length;
    const backupCount = versions.length;
    const targetLabel = editingExportPage ? ` on ${selectedPath.split('/').pop()}` : '';
    const backupLabel = (!editingExportPage && backupCount)
      ? ` - ${backupCount} saved backup${backupCount === 1 ? '' : 's'}`
      : '';
    status.textContent = `${count} editable section${count === 1 ? '' : 's'}${targetLabel}${backupLabel}`;
  }
  wpSetEditBusy(false);
}

function wpRenderPreview(pkg) {
  const tabs = document.getElementById('wpPackageTabs');
  const card = document.getElementById('wpPreviewCard');
  const frame = document.getElementById('wpPreviewFrame');
  const link = document.getElementById('wpOpenTab');
  const pageSelect = document.getElementById('wpPreviewPageSelect');
  if (!card || !frame || !link) return;

  if (!pkg.generated) {
    if (tabs) tabs.style.display = 'none';
    card.style.display = 'none';
    frame.src = 'about:blank';
    if (pageSelect) {
      pageSelect.innerHTML = '';
      pageSelect.style.display = 'none';
    }
    return;
  }
  if (tabs) tabs.style.display = '';
  card.style.display = wpPackageView === 'preview' ? '' : 'none';
  const exportInfo = ((pkg.generated_info || {}).multi_page_export || {});
  const exportManifest = exportInfo.manifest || {};
  const allExportFiles = exportInfo.files || [];
  const canonicalHomeFile = exportManifest.canonical_homepage
    ? allExportFiles.find(f => {
        const path = String((f && (f.path || f.filename)) || '').toLowerCase();
        return /(^|\/)index\.html$/.test(path);
      })
    : null;
  const exportFiles = allExportFiles.filter(f => {
    const path = String((f && (f.path || f.filename)) || '').toLowerCase();
    return !(exportManifest.canonical_homepage && /(^|\/)index\.html$/.test(path));
  });
  if (pageSelect) {
    const current = pageSelect.value;
    const options = [
      {
        filename: exportManifest.canonical_homepage
          ? 'Main preview / Home'
          : 'Main preview',
        path: canonicalHomeFile ? canonicalHomeFile.path : '',
      },
      ...exportFiles,
    ];
    pageSelect.innerHTML = options.map(f => (
      `<option value="${esc(f.path || '')}">${esc(f.filename || f.path || 'Main preview')}</option>`
    )).join('');
    if (current && options.some(f => f.path === current)) pageSelect.value = current;
    pageSelect.style.display = (exportFiles.length || canonicalHomeFile) ? '' : 'none';
  }
  const url = wpCurrentPreviewUrl();
  frame.src = url;
  link.href = url;
}

async function wpRunPreviewQa() {
  if (wpBusy || wpPreviewQaRunning) return;
  const btn = document.getElementById('btnWpPreviewQa');
  wpPreviewQaRunning = true;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Running QA...';
  }
  try {
    const result = await api(`/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}/preview-qa`, {
      method: 'POST',
    });
    wpRenderPreviewQa(result, true);
    if (result.status === 'skipped') {
      toast('Preview QA skipped: ' + ((result.tool_runs || {}).playwright || 'tool unavailable'), 'info');
    } else if (result.ok && result.passed !== false) {
      toast('Preview QA complete', 'success');
    } else {
      toast(result.error || 'Preview QA found blocking issues', 'error');
    }
  } catch (err) {
    toast('Preview QA failed', 'error');
  } finally {
    wpPreviewQaRunning = false;
    await loadWebsitePackage();
  }
}

function wpRenderAdvancedHtml(pkg) {
  const card = document.getElementById('wpAdvancedHtmlCard');
  const link = document.getElementById('wpOpenHtmlTab');
  const btn = document.getElementById('btnWpRefreshHtml');
  const fallback = document.getElementById('wpAdvancedHtmlFallback');
  if (!card) return;

  if (!pkg.generated) {
    card.style.display = 'none';
    wpAdvancedEditorLoadedFor = '';
    wpAdvancedEditorStamp = '';
    wpAdvancedOriginalHtml = '';
    wpSetAdvancedHtmlDirty(false);
    if (wpAdvancedEditor) wpAdvancedEditor.setValue('');
    if (fallback) fallback.value = '';
    if (btn) btn.disabled = true;
    if (link) link.href = '#';
    wpSetAdvancedHtmlStatus('Generate a site to inspect its main HTML source.', false);
    return;
  }

  card.style.display = wpPackageView === 'html' ? '' : 'none';
  const info = pkg.generated_info || {};
  const nextStamp = `${info.generated_at || ''}:${info.bytes || ''}`;
  if (nextStamp && wpAdvancedEditorStamp && nextStamp !== wpAdvancedEditorStamp) {
    wpAdvancedEditorLoadedFor = '';
  }
  if (nextStamp) wpAdvancedEditorStamp = nextStamp;
  const sourceUrl = wpMockupSourceUrl();
  if (link) link.href = sourceUrl;
  if (btn) btn.disabled = false;
  if (wpPackageView === 'html') {
    wpRefreshAdvancedHtml({ onlyIfEmpty: true });
  } else {
    wpSetAdvancedHtmlStatus(
      wpAdvancedEditorLoadedFor
        ? (wpAdvancedDirty ? 'Unsaved HTML changes.' : 'Source loaded.')
        : 'Open this tab to load the current site HTML.',
      false
    );
  }
}

async function loadWebsitePackage() {
  try {
    const pkg = await api(`/api/ai/website-package/${encodeURIComponent(LEAD_KEY)}`);
    if (!pkg.ok) {
      const panel = document.getElementById('wpStatusPanel');
      if (panel) panel.innerHTML = `<div class="text-sm" style="color:var(--danger)">${esc(pkg.error || 'Failed to load status')}</div>`;
      wpSetButtons({ hasScrape: false, hasMockup: false, hasReport: false });
      wpUpdateStudioLinks(null);
      wpRenderPreviewQa(null, false);
      return;
    }
    wpRenderStatus(pkg);
    wpUpdateStudioLinks(pkg);
    wpRenderScrapeReview(pkg);
    await wpLoadDesignBrief({ pkg, auto: true });
    wpRenderValidation(pkg.validation);
    wpRenderPreview(pkg);
    wpCurrentWebsitePackage = pkg;
    await wpRenderSectionEditor(pkg);
    wpRenderPreviewQa(pkg.preview_qa, !!pkg.generated);
    wpRenderAdvancedHtml(pkg);
    wpUpdateAdvancedEditorToggles();
    let report = null;
    try {
      report = await api(`/api/ai/report-package/${encodeURIComponent(LEAD_KEY)}`);
    } catch (e) {
      report = null;
    }
    wpRenderReport(report);
    wpSetButtons({
      scraping: false,
      generating: false,
      reporting: false,
      hasScrape: !!pkg.scraped,
      hasMockup: !!pkg.generated,
      hasReport: !!(report && report.ok && report.pdf_exists),
    });
  } catch (err) {
    const panel = document.getElementById('wpStatusPanel');
    if (panel) panel.innerHTML = '<div class="text-sm" style="color:var(--danger)">Failed to load website package.</div>';
    wpUpdateStudioLinks(null);
    wpRenderPreviewQa(null, false);
    wpCurrentWebsitePackage = null;
  }
}

async function wpEditSection() {
  if (wpBusy) return;
  const sel = document.getElementById('wpEditSection');
  const colorSel = document.getElementById('wpEditColorMode');
  const ta = document.getElementById('wpEditInstruction');
  const sectionId = (sel && sel.value) || '';
  const colorMode = (colorSel && colorSel.value) || 'preserve_current';
  const instruction = (ta && ta.value.trim()) || '';
  if (!sectionId) { toast('Choose a section', 'error'); return; }
  if (!instruction) { toast('Enter the change you want', 'error'); return; }

  wpBusy = true;
  wpSetEditBusy(true);
  try {
    const aiConfig = getSelectedAiConfig('OpenAI');
    const body = {
      lead_key: LEAD_KEY,
      section_id: sectionId,
      instruction,
      color_mode: colorMode,
      target_path: wpSelectedPreviewPath(),
      ...aiConfig,
    };
    const result = await api('/api/ai/edit-website-section', {
      method: 'POST',
      body,
    });
    if (result.ok) {
      const passed = result.validation?.passed ? 'passed validation' : 'saved with validation warnings';
      toast(`Section edited, ${passed}`, 'success');
      if (ta) ta.value = '';
    } else {
      toast(result.error || 'Section edit failed', 'error');
    }
  } catch (err) {
    toast('Section edit failed', 'error');
  } finally {
    wpBusy = false;
    wpSetEditBusy(false);
    await loadWebsitePackage();
  }
}

async function wpRestoreBackup() {
  if (wpBusy) return;
  const btn = document.getElementById('btnWpRestoreBackup');
  const versionSel = document.getElementById('wpVersionSelect');
  if (btn && btn.dataset.hasBackup !== 'true') {
    toast('No saved backup yet', 'error');
    return;
  }
  if (wpAdvancedDirty) {
    const ok = window.confirm('Restore backup and discard unsaved HTML changes?');
    if (!ok) return;
  }
  const versionFile = (versionSel && versionSel.value) || '';

  wpBusy = true;
  wpSetEditBusy(true);
  try {
    const result = await api('/api/ai/restore-website-backup', {
      method: 'POST',
      body: {
        lead_key: LEAD_KEY,
        version_file: versionFile,
      },
    });
    if (result.ok) {
      const passed = result.validation?.passed ? 'passed validation' : 'restored with validation warnings';
      toast(`Backup restored, ${passed}`, 'success');
      wpAdvancedEditorLoadedFor = '';
      wpAdvancedOriginalHtml = '';
      wpSetAdvancedHtmlDirty(false);
    } else {
      toast(result.error || 'Restore failed', 'error');
    }
  } catch (err) {
    toast('Restore failed', 'error');
  } finally {
    wpBusy = false;
    wpSetEditBusy(false);
    await loadWebsitePackage();
  }
}

function wpRenderReport(report) {
  const card = document.getElementById('wpReportCard');
  const metaEl = document.getElementById('wpReportMeta');
  const emailWrap = document.getElementById('wpEmailWrap');
  const emailText = document.getElementById('wpEmailText');
  const pdfLink = document.getElementById('wpDownloadPdf');
  const copyBtn = document.getElementById('wpCopyEmail');
  if (!card || !metaEl) return;
  card.style.display = '';

  const ok = !!(report && report.ok);
  const hasPdf = ok && !!report.pdf_exists;
  const hasEmail = ok && !!report.email_markdown;

  if (!ok) {
    metaEl.innerHTML = '<div class="text-muted text-sm">No report yet. Generate the site first, then click <b>Generate Report + Email</b>.</div>';
  } else {
    const m = report.meta || {};
    const parts = [];
    if (report.pdf_generated_at) parts.push('Generated ' + esc(wpFmtDate(report.pdf_generated_at)));
    if (m.email_model && m.email_model !== 'fallback') parts.push('Email drafted by ' + esc(m.email_model));
    if (m.email_model === 'fallback') parts.push('Email from template fallback');
    if (typeof m.old_screenshot_captured !== 'undefined') {
      parts.push('Old-site screenshot: ' + (m.old_screenshot_captured ? 'captured' : 'unavailable'));
    }
    metaEl.innerHTML = parts.length
      ? parts.map(p => `<span>${p}</span>`).join(' &middot; ')
      : '<span class="text-muted">Report ready.</span>';
  }

  if (pdfLink) {
    if (hasPdf) {
      pdfLink.style.display = '';
      pdfLink.href = `/api/ai/report-package/${encodeURIComponent(LEAD_KEY)}/pdf`;
    } else {
      pdfLink.style.display = 'none';
      pdfLink.href = '#';
    }
  }
  if (copyBtn) copyBtn.style.display = hasEmail ? '' : 'none';
  if (emailWrap) emailWrap.style.display = hasEmail ? '' : 'none';
  if (emailText) emailText.textContent = hasEmail ? report.email_markdown : '';
}

async function wpGenerateReport() {
  if (wpBusy) return;
  wpBusy = true;
  wpSetButtons({ reporting: true, hasScrape: true, hasMockup: true });
  try {
    const body = { lead_key: LEAD_KEY, ...getSelectedAiConfig('OpenAI') };
    const result = await api('/api/ai/generate-report-package', {
      method: 'POST',
      body,
    });
    if (result.ok) {
      toast('Report + email generated', 'success');
    } else {
      toast(result.error || 'Report generation failed', 'error');
    }
  } catch (err) {
    toast('Report generation failed', 'error');
  } finally {
    wpBusy = false;
    await loadWebsitePackage();
  }
}

async function wpCopyEmail() {
  const el = document.getElementById('wpEmailText');
  const text = (el && el.textContent) || '';
  if (!text) { toast('No email draft to copy', 'error'); return; }
  try {
    await navigator.clipboard.writeText(text);
    toast('Email copied', 'success');
  } catch (e) {
    toast('Copy failed', 'error');
  }
}

async function wpScrape() {
  if (wpBusy) return;
  wpBusy = true;
  wpSetButtons({ scraping: true, hasScrape: false, hasMockup: false });
  try {
    const result = await api('/api/ai/scrape-website', {
      method: 'POST',
      body: { lead_key: LEAD_KEY, mode: 'auto' },
    });
    if (result.ok) {
      const counts = result.counts || {};
      const parts = [
        `${counts.photos || 0} photos`,
        `${counts.services || 0} services`,
        `${counts.main_text_chars || 0} chars`,
      ];
      toast(`Website scraped: ${parts.join(', ')}`, 'success');
    } else {
      toast(result.error || 'Scrape failed', 'error');
    }
  } catch (err) {
    toast('Scrape failed', 'error');
  } finally {
    wpBusy = false;
    await loadWebsitePackage();
  }
}

async function wpGenerate() {
  if (wpGenerating) {
    await wpCancelGeneration();
    return;
  }
  if (wpBusy) return;
  if (
    wpDesignBriefLoaded &&
    document.getElementById('wpDesignBriefEditor') &&
    (!wpDesignBriefSaved || wpDesignBriefDirty)
  ) {
    const saved = await wpSaveDesignBrief({ silent: true });
    if (!saved) return;
  }
  wpBusy = true;
  wpGenerating = true;
  wpGenerationCanceling = false;
  wpSetButtons({ generating: true, hasScrape: true, hasMockup: false });
  try {
    const body = { lead_key: LEAD_KEY, ...getSelectedAiConfig('OpenAI') };
    const result = await api('/api/ai/generate-website-package', {
      method: 'POST',
      body,
    });
    if (result.cancelled) {
      toast('Website generation canceled', 'info');
    } else if (result.ok) {
      const retried = result.retried ? ' (retried)' : '';
      const passed = result.validation?.passed ? 'passed' : 'with warnings';
      toast(`Site generated ${passed}${retried}`, 'success');
    } else {
      toast(result.error || 'Generation failed', 'error');
    }
  } catch (err) {
    toast('Generation failed', 'error');
  } finally {
    wpGenerating = false;
    wpGenerationCanceling = false;
    wpBusy = false;
    await loadWebsitePackage();
  }
}

async function wpCancelGeneration() {
  if (!wpGenerating || wpGenerationCanceling) return;
  wpGenerationCanceling = true;
  wpSetButtons({ generating: true, hasScrape: true, hasMockup: !!(wpCurrentWebsitePackage && wpCurrentWebsitePackage.generated) });
  try {
    const result = await api('/api/ai/cancel-website-generation', {
      method: 'POST',
      body: { lead_key: LEAD_KEY },
    });
    if (result.ok) {
      toast('Cancel requested', 'info');
    } else {
      toast(result.error || 'Cancel failed', 'error');
      wpGenerationCanceling = false;
      wpSetButtons({
        generating: true,
        hasScrape: !!(wpCurrentWebsitePackage && wpCurrentWebsitePackage.scraped),
        hasMockup: !!(wpCurrentWebsitePackage && wpCurrentWebsitePackage.generated),
      });
    }
  } catch (err) {
    toast('Cancel failed', 'error');
    wpGenerationCanceling = false;
    wpSetButtons({
      generating: true,
      hasScrape: !!(wpCurrentWebsitePackage && wpCurrentWebsitePackage.scraped),
      hasMockup: !!(wpCurrentWebsitePackage && wpCurrentWebsitePackage.generated),
    });
  }
}
