/* ===== Shared utilities ===== */

function initTheme() {
  const allowed = new Set(['dark', 'light', 'orange']);
  const select = document.getElementById('themeSelect');
  const current = document.documentElement.dataset.theme || 'dark';
  if (select) {
    select.value = allowed.has(current) ? current : 'dark';
    select.addEventListener('change', () => {
      const next = allowed.has(select.value) ? select.value : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('summitTheme', next);
    });
  }
}

document.addEventListener('DOMContentLoaded', initTheme);

const _LEADS_ACTIVE_PATH_KEY = 'summitLeadsActivePath';

function initLeadNavigationMemory() {
  const path = window.location.pathname;
  const leadsLinks = document.querySelectorAll('a[href="/leads"]');
  if (/^\/leads\/.+/.test(path)) {
    sessionStorage.setItem(_LEADS_ACTIVE_PATH_KEY, `${path}${window.location.search || ''}`);
  } else if (path === '/leads') {
    sessionStorage.removeItem(_LEADS_ACTIVE_PATH_KEY);
  }

  const activePath = sessionStorage.getItem(_LEADS_ACTIVE_PATH_KEY);
  if (activePath && /^\/leads\/.+/.test(activePath)) {
    leadsLinks.forEach(link => { link.href = activePath; });
  }
}

document.addEventListener('DOMContentLoaded', initLeadNavigationMemory);

async function api(url, options = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  if (options.body && typeof options.body === 'object') {
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(url, { ...defaults, ...options });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

function toast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.remove(); }, 4000);
}

function scoreClass(score) {
  if (score >= 60) return 'score-high';
  if (score >= 40) return 'score-mid';
  return 'score-low';
}

function pipelineBadge(status) {
  const map = {
    'Needs review': 'badge-amber',
    'Approved': 'badge-blue',
    'Outreach-ready': 'badge-green',
    'Contacted': 'badge-purple',
    'Responded': 'badge-green',
    'Do not contact': 'badge-red',
    'Archived': 'badge-gray',
  };
  return map[status] || 'badge-gray';
}

function reviewBadge(review) {
  const map = {
    'Hot lead': 'badge-hot',
    'High confidence': 'badge-green',
    'Promising': 'badge-blue',
    'Needs review': 'badge-amber',
    'Low priority': 'badge-gray',
    'Low quality': 'badge-red',
    'No contact': 'badge-red',
  };
  return map[review] || 'badge-gray';
}

function freshnessBadge(freshness) {
  if (!freshness) return 'badge-gray';
  const lower = freshness.toLowerCase();
  if (lower.includes('verified this run') || lower.includes('recently verified') || lower.includes('newly found')) return 'badge-green';
  if (lower.includes('stale') || lower.includes('outdated')) return 'badge-red';
  return 'badge-amber';
}

function webBucketBadge(bucket) {
  const map = {
    'No website': 'badge-red',
    'Broken site': 'badge-red',
    'Weak live site': 'badge-amber',
    'Basic live site': 'badge-amber',
    'Social-only presence': 'badge-purple',
    'Directory-only presence': 'badge-gray',
    'Established website': 'badge-green',
  };
  return map[bucket] || 'badge-gray';
}

function techStackBadge(signal) {
  const lower = String(signal || '').toLowerCase();
  if (!lower) return 'badge-gray';
  if (lower.includes('weak') || lower.includes('outdated')) return 'badge-red';
  if (lower.includes('missing') || lower.includes('light')) return 'badge-amber';
  if (lower.includes('modern')) return 'badge-green';
  return 'badge-gray';
}

function esc(str) {
  if (str == null) return '';
  // Used in both text and quoted attributes. textContent/innerHTML alone does
  // not encode quotes, allowing scraped values to break out of attributes.
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function initTabs(containerSelector) {
  const container = document.querySelector(containerSelector);
  if (!container) return;
  const btns = container.querySelectorAll('.tab-btn');
  const panels = container.querySelectorAll('.tab-panel');
  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      btns.forEach(b => b.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = container.querySelector(`#${btn.dataset.tab}`);
      if (panel) panel.classList.add('active');
    });
  });
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function getPayload(lead) {
  let data = lead.data || lead.data_json || {};
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { data = {}; }
  }
  return data;
}
