let allLeads = [];
let selectedKeys = new Set();
let pinnedKeys = new Set();
let searchTimer = null;
let pendingScrollY = null;
let scrollSaveTimer = null;

// Sort state
let sortCol = null;   // 'name' | 'city' | 'score' | 'opportunity' | 'review' | 'webStatus' | 'techStack' | 'confidence' | 'freshness' | 'pipeline' | 'contact'
let sortDir = null;   // 'asc' | 'desc' | null

// Column filter state
let colFilters = { review: null, webStatus: null, techStack: null, freshness: null, pipeline: null, contact: null };

// ── Persist filter state across navigation ──────────────
const _FILTER_STORAGE_KEY = 'summitFilters';
const _LEADS_CACHE_KEY = 'summitLeadsCache';
const _LEADS_CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000;

function leadsPageLoadedByRefresh() {
  const nav = performance.getEntriesByType?.('navigation')?.[0];
  return nav && nav.type === 'reload';
}

function currentLeadQueryKey() {
  const search = document.getElementById('searchInput')?.value || '';
  const runId = document.getElementById('scanFilter')?.value || '';
  const viewFilter = document.getElementById('viewFilter')?.value || '';
  const pool = document.getElementById('poolFilter')?.value || '';
  return JSON.stringify({ search, runId, viewFilter, pool, pinnedListId: window._pinnedListId || '' });
}

function saveFilterState() {
  // Serialize colFilters (Set → Array for JSON)
  const serializedColFilters = {};
  for (const col of Object.keys(colFilters)) {
    serializedColFilters[col] = colFilters[col] ? [...colFilters[col]] : null;
  }
  const state = {
    scan: document.getElementById('scanFilter').value,
    view: document.getElementById('viewFilter').value,
    pool: document.getElementById('poolFilter').value,
    search: document.getElementById('searchInput').value,
    sortCol,
    sortDir,
    colFilters: serializedColFilters,
    scrollY: window.scrollY,
    ts: Date.now(),
  };
  sessionStorage.setItem(_FILTER_STORAGE_KEY, JSON.stringify(state));
}

function scheduleSaveLeadState() {
  clearTimeout(scrollSaveTimer);
  scrollSaveTimer = setTimeout(saveFilterState, 120);
}

function readLeadsCache() {
  const raw = sessionStorage.getItem(_LEADS_CACHE_KEY);
  if (!raw) return null;
  try {
    const cache = JSON.parse(raw);
    if (Date.now() - (cache.ts || 0) > _LEADS_CACHE_MAX_AGE_MS) {
      sessionStorage.removeItem(_LEADS_CACHE_KEY);
      return null;
    }
    return cache;
  } catch {
    sessionStorage.removeItem(_LEADS_CACHE_KEY);
    return null;
  }
}

function writeLeadsCache(queryKey, leads) {
  try {
    sessionStorage.setItem(_LEADS_CACHE_KEY, JSON.stringify({
      queryKey,
      leads,
      ts: Date.now(),
    }));
  } catch {
    // Storage quota is non-fatal; navigation still works without cache.
  }
}

function clearLeadsCache() {
  sessionStorage.removeItem(_LEADS_CACHE_KEY);
}

function restoreLeadsFromCache({ restoreScroll = false } = {}) {
  const cache = readLeadsCache();
  if (!cache || !Array.isArray(cache.leads)) return false;
  allLeads = cache.leads;
  renderTable();
  if (restoreScroll) restorePendingScroll();
  return true;
}

function restorePendingScroll() {
  if (pendingScrollY == null) return;
  const y = Math.max(0, Number(pendingScrollY) || 0);
  pendingScrollY = null;
  requestAnimationFrame(() => {
    window.scrollTo(0, y);
    requestAnimationFrame(() => window.scrollTo(0, y));
  });
}

function restoreFilterState() {
  const raw = sessionStorage.getItem(_FILTER_STORAGE_KEY);
  if (!raw) return null;
  try {
    const state = JSON.parse(raw);
    if (Date.now() - (state.ts || 0) > _LEADS_CACHE_MAX_AGE_MS) {
      sessionStorage.removeItem(_FILTER_STORAGE_KEY);
      return null;
    }
    return state;
  } catch { return null; }
}

function applyRestoredState(state) {
  if (!state) return;
  const scanSel = document.getElementById('scanFilter');
  if (state.scan) {
    // Only restore if the option still exists in the dropdown
    for (const opt of scanSel.options) {
      if (opt.value === state.scan) { scanSel.value = state.scan; break; }
    }
  }
  if (state.view) document.getElementById('viewFilter').value = state.view;
  if (state.pool) document.getElementById('poolFilter').value = state.pool;
  if (state.search) document.getElementById('searchInput').value = state.search;
  if (state.sortCol) { sortCol = state.sortCol; sortDir = state.sortDir || 'asc'; updateSortHeaders(); }
  // Restore column filters (Array → Set)
  if (state.colFilters) {
    for (const col of Object.keys(colFilters)) {
      colFilters[col] = state.colFilters[col] ? new Set(state.colFilters[col]) : null;
    }
    updateFilterBtnState();
  }
  updateDeleteScanBtn();
  updateClearFiltersBtn();
}

// ── Clear All Filters ──────────────────────────────
function hasActiveFilters() {
  if (document.getElementById('scanFilter').value) return true;
  if (document.getElementById('viewFilter').value !== 'All leads') return true;
  if (document.getElementById('poolFilter').value) return true;
  if (document.getElementById('searchInput').value) return true;
  if (sortCol) return true;
  for (const col of Object.keys(colFilters)) { if (colFilters[col]) return true; }
  return false;
}

function updateClearFiltersBtn() {
  const btn = document.getElementById('clearFiltersBtn');
  if (btn) btn.style.display = hasActiveFilters() ? '' : 'none';
}

function clearAllFilters() {
  document.getElementById('scanFilter').value = '';
  document.getElementById('viewFilter').value = 'All leads';
  document.getElementById('poolFilter').value = '';
  document.getElementById('searchInput').value = '';
  sortCol = null;
  sortDir = null;
  updateSortHeaders();
  for (const col of Object.keys(colFilters)) colFilters[col] = null;
  updateFilterBtnState();
  updateDeleteScanBtn();
  updateClearFiltersBtn();
  sessionStorage.removeItem(_FILTER_STORAGE_KEY);
  clearLeadsCache();
  loadLeads({ useCache: false, resetScroll: true });
}

if (!window._leadsInitDone) {
  window._leadsInitDone = true;
  document.addEventListener('DOMContentLoaded', async () => {
    if (leadsPageLoadedByRefresh()) {
      clearLeadsCache();
    }

    const saved = restoreFilterState();
    applyRestoredState(saved);
    pendingScrollY = saved && saved.scrollY ? saved.scrollY : null;
    const restoredFromCache = restoreLeadsFromCache({ restoreScroll: true });

    await Promise.all([loadPinnedKeys(), loadScans()]);
    applyRestoredState(saved);
    if (restoredFromCache) {
      renderTable();
      restorePendingScroll();
    } else {
      await loadLeads({ useCache: false, restoreScroll: true });
    }

    document.getElementById('searchInput').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { clearLeadsCache(); loadLeads({ useCache: false, resetScroll: true }); updateClearFiltersBtn(); }, 300);
    });
    document.getElementById('scanFilter').addEventListener('change', () => {
      updateDeleteScanBtn();
      updateClearFiltersBtn();
      clearLeadsCache();
      loadLeads({ useCache: false, resetScroll: true });
    });
    document.getElementById('viewFilter').addEventListener('change', () => { updateClearFiltersBtn(); clearLeadsCache(); loadLeads({ useCache: false, resetScroll: true }); });
    document.getElementById('poolFilter').addEventListener('change', () => { updateClearFiltersBtn(); clearLeadsCache(); loadLeads({ useCache: false, resetScroll: true }); });
    document.getElementById('selectAll').addEventListener('change', toggleSelectAll);

    window.addEventListener('scroll', scheduleSaveLeadState, { passive: true });
    window.addEventListener('pagehide', saveFilterState);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') saveFilterState();
    });

    document.querySelectorAll('a[href]').forEach(link => {
      link.addEventListener('click', () => saveFilterState());
    });

    // Close column filter dropdown on outside click
    document.addEventListener('click', (e) => {
      const dd = document.getElementById('colFilterDropdown');
      if (dd.classList.contains('open') && !dd.contains(e.target) && !e.target.classList.contains('col-filter-btn')) {
        dd.classList.remove('open');
      }
    });
  });
}

async function loadScans() {
  try {
    const scans = await api('/api/leads/scans');
    const sel = document.getElementById('scanFilter');
    // Clear existing options except the first "All scans" option
    while (sel.options.length > 1) sel.remove(1);
    scans.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.run_id || s.id;
      const label = s.label || `Run ${s.run_id || s.id}`;
      const date = s.started_at ? ` (${formatDate(s.started_at)})` : '';
      opt.textContent = `${label}${date} - ${s.lead_count || 0} leads`;
      sel.appendChild(opt);
    });
  } catch (e) { console.error('Load scans error:', e); }
}

async function loadPinnedKeys() {
  try {
    const res = await api('/api/leads/pinned-keys');
    pinnedKeys = new Set(res.pinned_keys || []);
    const btn = document.getElementById('recheckPinnedBtn');
    if (btn) btn.style.display = pinnedKeys.size > 0 ? '' : 'none';
  } catch (e) { console.error('Load pinned keys error:', e); }
}

async function loadLeads(options = {}) {
  const {
    useCache = false,
    restoreScroll = false,
    resetScroll = false,
    background = false,
    preserveScroll = false,
  } = options;
  const search = document.getElementById('searchInput').value;
  const runId = document.getElementById('scanFilter').value;
  const viewFilter = document.getElementById('viewFilter').value;
  const pool = document.getElementById('poolFilter').value;

  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (runId) params.set('run_id', runId);
  if (viewFilter) params.set('view_filter', viewFilter);
  if (pool === 'pinned') {
    // Use the pinned list id — fetch it from the lists endpoint or use a dedicated param
    // The API supports lead_list_id; we'll fetch the list id once
    if (!window._pinnedListId) {
      try {
        const lists = await api('/api/leads/lists');
        const pinList = lists.find(l => l.name === 'Pinned Leads');
        if (pinList) window._pinnedListId = pinList.list_id;
      } catch (e) { /* ignore */ }
    }
    if (window._pinnedListId) params.set('lead_list_id', window._pinnedListId);
  }

  const queryKey = currentLeadQueryKey();
  const cache = useCache ? readLeadsCache() : null;
  if (cache && cache.queryKey === queryKey && Array.isArray(cache.leads)) {
    allLeads = cache.leads;
    renderTable();
    if (restoreScroll) restorePendingScroll();
    return;
  }

  if (!background && resetScroll) {
    pendingScrollY = 0;
  }

  try {
    allLeads = await api(`/api/leads?${params}`);
    writeLeadsCache(queryKey, allLeads);
    const scrollBeforeRefresh = background && preserveScroll ? window.scrollY : null;
    renderTable();
    if (scrollBeforeRefresh != null) {
      requestAnimationFrame(() => window.scrollTo(0, scrollBeforeRefresh));
    }
    if (restoreScroll || resetScroll) restorePendingScroll();
  } catch (err) {
    console.error('Load leads error:', err);
    if (!background) {
      document.getElementById('leadsBody').innerHTML =
        '<tr><td colspan="15" class="text-muted" style="text-align:center;padding:24px;">Failed to load leads</td></tr>';
    }
  }
}

// ── Sorting ────────────────────────────────────

function toggleSort(col) {
  if (sortCol === col) {
    sortDir = sortDir === 'asc' ? 'desc' : sortDir === 'desc' ? null : 'asc';
    if (sortDir === null) sortCol = null;
  } else {
    sortCol = col;
    sortDir = 'asc';
  }
  updateSortHeaders();
  updateClearFiltersBtn();
  renderTable();
}

function updateSortHeaders() {
  document.querySelectorAll('#leadsTable thead th.sortable').forEach(th => {
    const col = th.dataset.col;
    const arrow = th.querySelector('.sort-arrow');
    th.classList.toggle('sort-active', col === sortCol);
    if (col === sortCol && sortDir === 'asc') arrow.textContent = '▲';
    else if (col === sortCol && sortDir === 'desc') arrow.textContent = '▼';
    else arrow.textContent = '';
  });
}

function getLeadField(lead, col) {
  const data = getPayload(lead);
  switch (col) {
    case 'name': return (lead.business_name || data['Business Name'] || '').toLowerCase();
    case 'city': return (lead.city_area || data['City/Area'] || '').toLowerCase();
    case 'score': return +(lead.last_lead_score ?? data['Lead Score'] ?? -1);
    case 'opportunity': return +(lead.last_opportunity_score ?? lead['Opportunity Score'] ?? data['Opportunity Score'] ?? -1);
    case 'review': return (lead.review_bucket || lead['Review Bucket'] || data['Review Bucket'] || '').toLowerCase();
    case 'webStatus': return (lead.website_bucket || lead['Website Bucket'] || data['Website Bucket'] || lead.last_web_presence_status || data['Web Presence Status'] || '').toLowerCase();
    case 'techStack': return (lead.tech_stack_signal || lead['Tech Stack Signal'] || data['Tech Stack Signal'] || '').toLowerCase();
    case 'confidence': return (lead.confidence_summary || lead['Web Presence Confidence'] || data['Web Presence Confidence'] || '').toLowerCase();
    case 'freshness': return (lead.freshness_status || lead['Data Freshness'] || data['Data Freshness'] || '').toLowerCase();
    case 'pipeline': return (lead.pipeline_status || 'Needs review').toLowerCase();
    case 'contact': {
      const phone = data['Phone'] || '';
      const email = data['Email'] || '';
      return [phone ? 'Phone' : '', email ? 'Email' : ''].filter(Boolean).join(', ').toLowerCase() || 'none';
    }
    default: return '';
  }
}

function getSortedLeads() {
  let leads = [...allLeads];

  // Apply column filters
  leads = leads.filter(lead => {
    for (const col of ['review', 'webStatus', 'techStack', 'freshness', 'pipeline', 'contact']) {
      if (colFilters[col]) {
        const val = getLeadField(lead, col);
        if (!colFilters[col].has(val)) return false;
      }
    }
    return true;
  });

  if (!sortCol || !sortDir) return leads;

  leads.sort((a, b) => {
    const va = getLeadField(a, sortCol);
    const vb = getLeadField(b, sortCol);
    let cmp;
    if (sortCol === 'score' || sortCol === 'opportunity') {
      cmp = va - vb;
    } else {
      cmp = va < vb ? -1 : va > vb ? 1 : 0;
    }
    return sortDir === 'desc' ? -cmp : cmp;
  });
  return leads;
}

// ── Column Filters ─────────────────────────────

function toggleColFilter(col, btnEl) {
  const dd = document.getElementById('colFilterDropdown');

  // If already open for this column, close it
  if (dd.classList.contains('open') && dd.dataset.col === col) {
    dd.classList.remove('open');
    return;
  }

  // Collect unique values for this column
  const values = new Set();
  allLeads.forEach(lead => {
    const val = getLeadField(lead, col);
    if (val) values.add(val);
  });
  const sorted = [...values].sort();

  // Build dropdown content
  dd.innerHTML = `<div class="col-filter-option" style="font-weight:600;border-bottom:1px solid var(--border-light);margin-bottom:4px;">
    <label style="cursor:pointer;display:flex;align-items:center;gap:8px;width:100%">
      <input type="checkbox" ${!colFilters[col] ? 'checked' : ''} onchange="clearColFilter('${col}')"> All
    </label>
  </div>` + sorted.map(v => {
    const checked = !colFilters[col] || colFilters[col].has(v) ? 'checked' : '';
    const display = v.charAt(0).toUpperCase() + v.slice(1);
    return `<div class="col-filter-option">
      <label style="cursor:pointer;display:flex;align-items:center;gap:8px;width:100%">
        <input type="checkbox" ${checked} onchange="setColFilterValue('${col}', '${v.replace(/'/g, "\\'")}', this.checked)"> ${esc(display)}
      </label>
    </div>`;
  }).join('');

  dd.dataset.col = col;

  // Position below the button
  const rect = btnEl.getBoundingClientRect();
  dd.style.top = (rect.bottom + 4) + 'px';
  dd.style.left = Math.min(rect.left, window.innerWidth - 200) + 'px';
  dd.classList.add('open');
}

function clearColFilter(col) {
  colFilters[col] = null;
  updateFilterBtnState();
  updateClearFiltersBtn();
  renderTable();
  document.getElementById('colFilterDropdown').classList.remove('open');
}

function setColFilterValue(col, value, checked) {
  // Initialize filter set from all values if not yet active
  if (!colFilters[col]) {
    colFilters[col] = new Set();
    allLeads.forEach(lead => {
      const val = getLeadField(lead, col);
      if (val) colFilters[col].add(val);
    });
  }

  if (checked) colFilters[col].add(value);
  else colFilters[col].delete(value);

  // If all values are selected, clear the filter
  const allVals = new Set();
  allLeads.forEach(lead => { const v = getLeadField(lead, col); if (v) allVals.add(v); });
  if (colFilters[col].size >= allVals.size) colFilters[col] = null;

  updateFilterBtnState();
  updateClearFiltersBtn();
  renderTable();
}

function updateFilterBtnState() {
  ['review', 'webStatus', 'techStack', 'freshness', 'pipeline', 'contact'].forEach(col => {
    const th = document.querySelector(`th[data-col="${col}"]`);
    if (!th) return;
    const btn = th.querySelector('.col-filter-btn');
    if (btn) btn.classList.toggle('active', !!colFilters[col]);
  });
}

// ── Delete Scan ────────────────────────────────

function updateDeleteScanBtn() {
  const btn = document.getElementById('deleteScanBtn');
  const runId = document.getElementById('scanFilter').value;
  btn.style.display = runId ? '' : 'none';
}

function deleteScan() {
  const runId = document.getElementById('scanFilter').value;
  if (!runId) return;
  const sel = document.getElementById('scanFilter');
  const label = sel.options[sel.selectedIndex].textContent;
  document.getElementById('deleteModalText').textContent =
    `Are you sure you want to delete this entire scan?\n\n"${label}"\n\nAll leads unique to this scan will be removed. This cannot be undone.`;
  document.getElementById('deleteModal').dataset.mode = 'scan';
  document.getElementById('deleteModal').classList.add('open');
}

// ── Delete ──────────────────────────────────────

function deleteSelected() {
  if (!selectedKeys.size) return;
  const count = selectedKeys.size;
  document.getElementById('deleteModalText').textContent =
    `Are you sure you want to delete ${count} lead${count !== 1 ? 's' : ''}? This cannot be undone.`;
  document.getElementById('deleteModal').classList.add('open');
}

function closeDeleteModal() {
  const modal = document.getElementById('deleteModal');
  modal.classList.remove('open');
  delete modal.dataset.mode;
}

async function confirmDelete() {
  const modal = document.getElementById('deleteModal');
  const mode = modal.dataset.mode || 'leads';
  closeDeleteModal();

  if (mode === 'scan') {
    const runId = document.getElementById('scanFilter').value;
    if (!runId) return;
    try {
      await api(`/api/leads/scans/${runId}`, { method: 'DELETE' });
      toast('Scan deleted', 'success');
      document.getElementById('scanFilter').value = '';
      updateDeleteScanBtn();
      clearLeadsCache();
      await loadScans();
      await loadLeads({ useCache: false, resetScroll: true });
    } catch (err) {
      toast('Delete scan failed', 'error');
    }
    return;
  }

  const runId = document.getElementById('scanFilter').value;
  try {
    await api('/api/leads/bulk/delete', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys], run_id: runId || null }
    });
    toast(`Deleted ${selectedKeys.size} lead${selectedKeys.size !== 1 ? 's' : ''}`, 'success');
    clearSelection();
    clearLeadsCache();
    await loadLeads({ useCache: false });
  } catch (err) {
    toast('Delete failed', 'error');
  }
}

// ── Render ──────────────────────────────────────

function renderTable() {
  const tbody = document.getElementById('leadsBody');
  const displayLeads = getSortedLeads();
  document.getElementById('leadCount').textContent = `${displayLeads.length} lead${displayLeads.length !== 1 ? 's' : ''}${allLeads.length !== displayLeads.length ? ` (of ${allLeads.length})` : ''}`;

  if (!displayLeads.length) {
    tbody.innerHTML = '<tr><td colspan="16"><div class="empty-state"><div class="empty-state-icon">&#9776;</div><div class="empty-state-title">No leads found</div><div class="empty-state-text">Adjust your filters or run a new discovery scan.</div></div></td></tr>';
    return;
  }

  tbody.innerHTML = displayLeads.map(lead => {
    const data = getPayload(lead);
    const key = lead.lead_key || '';
    const name = lead.business_name || data['Business Name'] || '';
    const city = lead.city_area || data['City/Area'] || '';
    const oppScore = lead.last_opportunity_score ?? lead['Opportunity Score'] ?? data['Opportunity Score'] ?? '';
    const score = lead.last_lead_score ?? data['Lead Score'] ?? '';
    const review = lead.review_bucket || lead['Review Bucket'] || data['Review Bucket'] || '';
    const webBucket = lead.website_bucket || lead['Website Bucket'] || data['Website Bucket'] || lead.last_web_presence_status || data['Web Presence Status'] || '';
    const techStack = lead.tech_stack_signal || lead['Tech Stack Signal'] || data['Tech Stack Signal'] || '';
    const techScore = lead.tech_stack_score ?? lead['Tech Stack Score'] ?? data['Tech Stack Score'] ?? '';
    const techScoreText = techStack && techScore !== '' ? ` (${esc(techScore)})` : '';
    const confidence = lead.confidence_summary || lead['Web Presence Confidence'] || data['Web Presence Confidence'] || '';
    const freshness = lead.evidence_freshness || lead.freshness_status || lead['Evidence Freshness'] || lead['Data Freshness'] || data['Evidence Freshness'] || data['Data Freshness'] || '';
    const sourcesChecked = lead.sources_checked || lead['Sources Checked'] || data['Sources Checked'] || '';
    const whySurfaced = lead.why_surfaced || lead['Why Surfaced'] || data['Why Surfaced'] || '';
    const whySuppressed = lead.why_suppressed || lead['Why Suppressed'] || data['Why Suppressed'] || '';
    const nextBestAction = lead.next_best_action || lead['Next Best Action'] || data['Next Best Action'] || '';
    const pipeline = lead.pipeline_status || 'Needs review';
    const phone = lead.phone || lead['Phone'] || data['Phone'] || '';
    const email = lead.email || lead['Email'] || data['Email'] || '';
    const contact = [phone ? 'Phone' : '', email ? 'Email' : ''].filter(Boolean).join(', ') || 'None';
    const checked = selectedKeys.has(key) ? 'checked' : '';
    const selClass = selectedKeys.has(key) ? 'selected' : '';

    return `<tr class="${selClass}" data-key="${esc(key)}">
      <td class="col-checkbox"><input type="checkbox" class="row-check" data-key="${esc(key)}" ${checked}></td>
      <td><a href="/leads/${encodeURIComponent(key)}" style="font-weight:600;color:var(--text-primary)">${pinnedKeys.has(key) ? '\u{1F4CC} ' : ''}${esc(name)}</a></td>
      <td>${esc(city)}</td>
      <td><span class="score ${scoreClass(+oppScore)}">${esc(oppScore !== '' ? oppScore : '--')}</span></td>
      <td><span class="score ${scoreClass(+score)}">${esc(score !== '' ? score : '--')}</span></td>
      <td><span class="badge ${reviewBadge(review)}">${esc(review || 'Unknown')}</span></td>
      <td><span class="badge ${webBucketBadge(webBucket)}">${esc(webBucket || 'Unknown')}</span></td>
      <td><span class="badge ${techStackBadge(techStack)}">${esc(techStack || '--')}${techScoreText}</span></td>
      <td class="text-sm">${esc(confidence || '--')}</td>
      <td><span class="badge ${freshnessBadge(freshness)}">${esc(freshness || '--')}</span></td>
      <td class="text-sm col-decision">${esc(sourcesChecked || '--')}</td>
      <td class="text-sm col-decision">${esc(whySurfaced || '--')}</td>
      <td class="text-sm col-decision">${esc(whySuppressed || '--')}</td>
      <td class="text-sm col-decision">${esc(nextBestAction || '--')}</td>
      <td><span class="badge ${pipelineBadge(pipeline)}">${esc(pipeline)}</span></td>
      <td class="text-sm">${esc(contact)}</td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('.row-check').forEach(cb => {
    cb.addEventListener('change', e => {
      e.stopPropagation();
      const key = cb.dataset.key;
      if (cb.checked) selectedKeys.add(key); else selectedKeys.delete(key);
      updateBulkBar();
      cb.closest('tr').classList.toggle('selected', cb.checked);
    });
  });

  tbody.querySelectorAll('tr').forEach(tr => {
    tr.addEventListener('click', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'A') return;
      const key = tr.dataset.key;
      if (key) { saveFilterState(); window.location.href = `/leads/${encodeURIComponent(key)}`; }
    });
  });

  // Save filter state when clicking lead name links too
  tbody.querySelectorAll('a[href^="/leads/"]').forEach(a => {
    a.addEventListener('click', () => saveFilterState());
  });
}

function toggleSelectAll(e) {
  const checked = e.target.checked;
  selectedKeys.clear();
  if (checked) {
    const displayLeads = getSortedLeads();
    displayLeads.forEach(l => selectedKeys.add(l.lead_key));
  }
  renderTable();
  document.getElementById('selectAll').checked = checked;
  updateBulkBar();
}

function updateBulkBar() {
  const bar = document.getElementById('bulkBar');
  const count = selectedKeys.size;
  document.getElementById('bulkCount').textContent = `${count} selected`;
  bar.classList.toggle('visible', count > 0);
}

function clearSelection() {
  selectedKeys.clear();
  document.getElementById('selectAll').checked = false;
  updateBulkBar();
  renderTable();
}

async function applyBulkPipeline() {
  const status = document.getElementById('bulkPipeline').value;
  if (!status || !selectedKeys.size) return;
  try {
    await api('/api/leads/bulk/pipeline-status', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys], pipeline_status: status }
    });
    toast(`Updated ${selectedKeys.size} leads to ${status}`, 'success');
    clearSelection();
    clearLeadsCache();
    await loadLeads({ useCache: false });
  } catch (err) { toast('Bulk update failed', 'error'); }
}

async function applyBulkSignal() {
  const signal = document.getElementById('bulkSignal').value;
  if (!signal || !selectedKeys.size) return;
  try {
    await api('/api/leads/bulk/lead-signal', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys], lead_signal: signal }
    });
    toast(`Set signal for ${selectedKeys.size} leads`, 'success');
    clearSelection();
    clearLeadsCache();
    await loadLeads({ useCache: false });
  } catch (err) { toast('Bulk update failed', 'error'); }
}

async function batchAgentReviewSelected() {
  if (!selectedKeys.size) return;
  const count = selectedKeys.size;
  toast(`Running agent review for ${count} selected lead${count !== 1 ? 's' : ''}...`, 'info');
  try {
    const result = await api('/api/ai/agent-review/batch', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys], limit: Math.min(count, 50), force: false }
    });
    if (result.ok || result.requested) {
      toast(`Agent review: ${result.completed || 0} completed, ${result.cached || 0} cached, ${result.skipped || 0} skipped, ${result.error || 0} errors`, result.error ? 'error' : 'success');
      clearSelection();
      clearLeadsCache();
      await loadLeads({ useCache: false, preserveScroll: true });
    } else {
      toast(result.error || 'Agent review failed', 'error');
    }
  } catch (err) {
    toast('Agent review failed', 'error');
  }
}

function exportLeads() {
  const search = document.getElementById('searchInput').value;
  const runId = document.getElementById('scanFilter').value;
  const viewFilter = document.getElementById('viewFilter').value;
  const params = new URLSearchParams({ format: 'csv' });
  if (search) params.set('search', search);
  if (runId) params.set('run_id', runId);
  if (viewFilter) params.set('view_filter', viewFilter);
  window.location.href = `/api/leads/export?${params}`;
}

async function createTodayShortlist() {
  const runId = document.getElementById('scanFilter').value;
  const viewFilter = document.getElementById('viewFilter').value || 'High confidence';
  const explicit = selectedKeys.size ? [...selectedKeys] : [];
  try {
    const result = await api('/api/leads/shortlists/today', {
      method: 'POST',
      body: {
        run_id: runId || null,
        view_filter: viewFilter === 'All leads' ? 'High confidence' : viewFilter,
        lead_keys: explicit,
        limit: explicit.length || 25,
      }
    });
    if (result.ok) {
      toast(`Added ${result.added} lead${result.added !== 1 ? 's' : ''} to ${result.list_name}`, 'success');
      clearSelection();
      clearLeadsCache();
      await loadLeads({ useCache: false, preserveScroll: true });
    } else {
      toast(result.error || 'No shortlist created', 'info');
    }
  } catch (err) {
    toast('Shortlist failed', 'error');
  }
}

// ── Pinned Leads ──────────────────────────────────

async function pinSelected() {
  if (!selectedKeys.size) return;
  try {
    const res = await api('/api/leads/pin', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys] }
    });
    toast(`Pinned ${res.pinned} lead${res.pinned !== 1 ? 's' : ''}`, 'success');
    await loadPinnedKeys();
    clearSelection();
    clearLeadsCache();
    await loadLeads({ useCache: false });
  } catch (err) { toast('Pin failed', 'error'); }
}

async function unpinSelected() {
  if (!selectedKeys.size) return;
  try {
    const res = await api('/api/leads/unpin', {
      method: 'POST',
      body: { lead_keys: [...selectedKeys] }
    });
    toast(`Unpinned ${res.unpinned} lead${res.unpinned !== 1 ? 's' : ''}`, 'success');
    await loadPinnedKeys();
    clearSelection();
    clearLeadsCache();
    await loadLeads({ useCache: false });
  } catch (err) { toast('Unpin failed', 'error'); }
}

async function recheckPinned() {
  try {
    const res = await api('/api/discovery/recheck-pinned', { method: 'POST' });
    if (res.ok) {
      toast(`Started recheck scan for ${res.lead_count} pinned lead${res.lead_count !== 1 ? 's' : ''}`, 'success');
    } else {
      toast(res.error || 'Could not start recheck', 'error');
    }
  } catch (err) { toast('Recheck failed', 'error'); }
}
