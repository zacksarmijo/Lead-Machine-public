(() => {
  'use strict';

  const API_ROOT = '/api/website-monitor';
  const SELECTED_SITE_KEY = 'summitWebsiteMonitorSelectedSite';
  const POLL_DELAY_MS = 2500;

  const state = {
    summary: {},
    sites: [],
    selectedId: null,
    detail: null,
    scanningIds: new Set(),
    pollTimer: null,
    polling: false,
    lastScanMessage: '',
    modalReturnFocus: null,
  };

  const el = id => document.getElementById(id);

  document.addEventListener('DOMContentLoaded', () => {
    if (!el('websiteMonitor')) return;
    bindEvents();
    initializeMonitor();
  });

  function bindEvents() {
    el('wmAddWebsiteBtn').addEventListener('click', () => openSiteModal('add'));
    el('wmEditWebsiteBtn').addEventListener('click', () => openSiteModal('edit'));
    el('wmDeleteWebsiteBtn').addEventListener('click', openDeleteModal);
    el('wmRunScanBtn').addEventListener('click', runSelectedScan);
    el('wmRefreshBtn').addEventListener('click', refreshMonitor);
    el('wmSiteSearch').addEventListener('input', renderSiteList);
    el('wmSiteTypeFilter').addEventListener('change', renderSiteList);
    el('wmSiteType').addEventListener('change', renderTypeExplainer);
    el('wmSiteUrl').addEventListener('input', event => event.target.setCustomValidity(''));
    el('wmSiteForm').addEventListener('submit', saveWebsite);
    el('wmConfirmDeleteBtn').addEventListener('click', deleteSelectedWebsite);

    el('wmSiteList').addEventListener('click', event => {
      const addButton = event.target.closest('[data-wm-add]');
      if (addButton) {
        openSiteModal('add');
        return;
      }
      const siteButton = event.target.closest('[data-site-id]');
      if (siteButton) selectSite(siteButton.dataset.siteId);
    });

    document.querySelectorAll('[data-wm-close="site"]').forEach(button => {
      button.addEventListener('click', () => closeModal('site'));
    });
    document.querySelectorAll('[data-wm-close="delete"]').forEach(button => {
      button.addEventListener('click', () => closeModal('delete'));
    });

    el('wmSiteModal').addEventListener('mousedown', event => {
      if (event.target === el('wmSiteModal')) closeModal('site');
    });
    el('wmDeleteModal').addEventListener('mousedown', event => {
      if (event.target === el('wmDeleteModal')) closeModal('delete');
    });

    document.addEventListener('keydown', handleModalKeyboard);
    window.addEventListener('beforeunload', () => clearTimeout(state.pollTimer));
  }

  async function initializeMonitor() {
    const results = await Promise.allSettled([
      request(`${API_ROOT}/summary`),
      request(`${API_ROOT}/sites`),
      request(`${API_ROOT}/scans/status`),
    ]);

    const summaryResult = results[0];
    const sitesResult = results[1];
    const statusResult = results[2];

    if (summaryResult.status === 'fulfilled') {
      state.summary = summaryResult.value || {};
    }

    if (sitesResult.status === 'fulfilled') {
      state.sites = normalizeSiteCollection(sitesResult.value);
    } else if (summaryResult.status === 'fulfilled') {
      state.sites = normalizeSiteCollection(state.summary.sites || []);
    }

    if (summaryResult.status === 'rejected' && sitesResult.status === 'rejected') {
      showSiteListError('Website Monitor could not be loaded.');
      showNoSelection('Unable to load websites', 'Check the server connection, then refresh this page.');
      notify('Failed to load Website Monitor', 'error');
      return;
    }

    syncScanningFromSummary();
    if (statusResult.status === 'fulfilled') applyScanStatus(statusResult.value, false);

    renderProviderNotice();
    renderOverview();
    renderSiteList();

    const requestedId = new URLSearchParams(window.location.search).get('site');
    const rememberedId = localStorage.getItem(SELECTED_SITE_KEY);
    const initialId = [requestedId, rememberedId]
      .filter(Boolean)
      .find(id => state.sites.some(site => sameId(site.id, id)));

    if (initialId || state.sites.length) {
      await selectSite(initialId || state.sites[0].id);
    } else {
      showNoSelection('No websites tracked yet', 'Add any website you own or want to observe, then run its first public scan.', true);
    }

    if (state.scanningIds.size) schedulePoll(0);
  }

  async function request(url, options = {}) {
    const config = { ...options };
    config.headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (config.body && typeof config.body === 'object') {
      config.headers['Content-Type'] = 'application/json';
      config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);
    const raw = response.status === 204 ? '' : await response.text();
    let data = null;
    if (raw) {
      try { data = JSON.parse(raw); } catch { data = raw; }
    }

    if (!response.ok) {
      const message = data && typeof data === 'object'
        ? data.detail || data.message || data.error
        : data;
      throw new Error(message || `Request failed (${response.status})`);
    }
    return data;
  }

  function normalizeSiteCollection(payload) {
    const collection = Array.isArray(payload)
      ? payload
      : asArray(payload && (payload.sites || payload.results || payload.items));
    return collection.map(normalizeSite).filter(site => site.id !== null && site.id !== undefined);
  }

  function normalizeSite(raw = {}) {
    const sitePayload = raw.site && typeof raw.site === 'object' ? raw.site : {};
    const site = { ...raw, ...sitePayload };
    const latestRun = raw.latest_run || raw.latest_scan || raw.last_run || site.latest_run || site.latest_scan || {};
    return {
      ...site,
      id: firstValue(site.id, site.site_id, raw.id, raw.site_id),
      name: firstValue(site.name, site.label, site.title, hostFromUrl(site.url), 'Untitled website'),
      url: firstValue(site.url, site.website_url, site.domain, ''),
      site_type: normalizeSiteType(firstValue(site.site_type, site.type, 'observed')),
      device: String(firstValue(site.device, 'mobile')).toLowerCase(),
      location: firstValue(site.location, site.search_location, ''),
      notes: firstValue(site.notes, ''),
      keywords: asStringList(site.keywords || site.target_keywords),
      latest_run: latestRun || {},
    };
  }

  function normalizeDetail(payload = {}) {
    const siteSource = payload.site && typeof payload.site === 'object'
      ? { ...payload, ...payload.site }
      : payload;
    const site = normalizeSite(siteSource);
    const latestRun = payload.latest_run || payload.latest_scan || payload.last_run || site.latest_run || {};
    return {
      site,
      latestRun: latestRun || {},
      rankings: asArray(payload.rankings || payload.latest_rankings || latestRun.rankings || payload.keyword_rankings),
      issues: [
        ...asArray(payload.issues || latestRun.issues || payload.open_issues),
        ...asArray(payload.resolved_issues),
      ],
      history: asArray(payload.history || payload.run_history || payload.scans || payload.runs),
    };
  }

  function firstValue(...values) {
    return values.find(value => value !== undefined && value !== null && value !== '');
  }

  function asArray(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null || value === '') return [];
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [parsed];
      } catch {
        return [value];
      }
    }
    return typeof value === 'object' ? Object.values(value) : [value];
  }

  function asStringList(value) {
    if (Array.isArray(value)) return uniqueStrings(value);
    if (value === undefined || value === null || value === '') return [];
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) return [];
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) return uniqueStrings(parsed);
      } catch { /* Plain text list. */ }
      return uniqueStrings(trimmed.split(/[\n,]+/));
    }
    return uniqueStrings([value]);
  }

  function uniqueStrings(values) {
    const seen = new Set();
    return values.map(value => String(value || '').trim()).filter(value => {
      const key = value.toLowerCase();
      if (!value || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function normalizeSiteType(value) {
    return String(value || '').toLowerCase() === 'owned' ? 'owned' : 'observed';
  }

  function latestFor(site) {
    return site.latest_run || site.latest_scan || site.last_run || {};
  }

  function renderProviderNotice() {
    const notice = el('wmProviderNotice');
    const providers = state.summary && state.summary.providers;
    if (!providers || typeof providers !== 'object') {
      notice.hidden = true;
      notice.innerHTML = '';
      return;
    }

    const hasDataForSeo = Object.prototype.hasOwnProperty.call(providers, 'dataforseo_configured')
      || Object.prototype.hasOwnProperty.call(providers, 'dataforseo');
    const hasPageSpeed = Object.prototype.hasOwnProperty.call(providers, 'pagespeed_configured')
      || Object.prototype.hasOwnProperty.call(providers, 'pagespeed');
    if (!hasDataForSeo && !hasPageSpeed) {
      notice.hidden = true;
      return;
    }

    const dataForSeoReady = Boolean(firstValue(providers.dataforseo_configured, providers.dataforseo, false));
    const pageSpeedReady = Boolean(firstValue(providers.pagespeed_configured, providers.pagespeed, false));
    notice.innerHTML = `
      <div class="wm-provider-copy">
        <strong>Scan readiness</strong>
        <span>Keyword rankings require DataForSEO. Public technical checks can still run, while PageSpeed adds performance metrics.</span>
      </div>
      <div class="wm-provider-badges">
        <span class="badge ${dataForSeoReady ? 'badge-green' : 'badge-amber'}">DataForSEO: ${dataForSeoReady ? 'Ready' : 'Setup needed'}</span>
        <span class="badge ${pageSpeedReady ? 'badge-green' : 'badge-amber'}">PageSpeed: ${pageSpeedReady ? 'Ready' : 'Setup needed'}</span>
      </div>`;
    notice.hidden = false;
  }

  function renderOverview() {
    const summary = state.summary || {};
    const activeSites = state.sites.filter(site => site.active !== false);
    const siteCount = numberOrNull(summary.site_count) ?? numberOrNull(summary.total_sites) ?? activeSites.length;
    const ownedCount = numberOrNull(firstValue(summary.owned_count, summary.owned_site_count))
      ?? activeSites.filter(site => site.site_type === 'owned').length;
    const observedCount = numberOrNull(firstValue(summary.observed_count, summary.observed_site_count))
      ?? activeSites.filter(site => site.site_type === 'observed').length;

    const healthValues = activeSites
      .map(site => metricValue(site, 'health_score'))
      .filter(value => value !== null);
    const computedHealth = healthValues.length
      ? healthValues.reduce((total, value) => total + value, 0) / healthValues.length
      : null;
    const averageHealth = numberOrNull(firstValue(summary.average_health, summary.average_health_score)) ?? computedHealth;

    const computedIssues = activeSites.reduce((total, site) => {
      return total + (numberOrNull(firstValue(site.open_issue_count, site.open_issues, latestFor(site).open_issue_count)) || 0);
    }, 0);
    const openIssues = numberOrNull(firstValue(summary.open_issue_count, summary.open_issues)) ?? computedIssues;

    el('wmSiteCount').textContent = formatInteger(siteCount);
    el('wmOwnedCount').textContent = formatInteger(ownedCount);
    el('wmObservedCount').textContent = formatInteger(observedCount);
    setScoreText(el('wmAverageHealth'), averageHealth);
    el('wmOpenIssues').textContent = formatInteger(openIssues);

    const scanCount = state.scanningIds.size;
    el('wmScanSummary').textContent = scanCount
      ? `${scanCount} scan${scanCount === 1 ? '' : 's'} running`
      : 'No scans running';
  }

  function syncScanningFromSummary() {
    const ids = asArray(state.summary && state.summary.scanning_site_ids);
    ids.forEach(id => state.scanningIds.add(String(id)));
  }

  function renderSiteList() {
    const list = el('wmSiteList');
    const search = el('wmSiteSearch').value.trim().toLowerCase();
    const typeFilter = el('wmSiteTypeFilter').value;
    const filtered = state.sites.filter(site => {
      if (typeFilter !== 'all' && site.site_type !== typeFilter) return false;
      if (!search) return true;
      return [site.name, site.url, site.location]
        .some(value => String(value || '').toLowerCase().includes(search));
    });

    if (!state.sites.length) {
      list.innerHTML = `
        <div class="wm-site-list-empty">
          <strong>No websites yet</strong>
          <span>Add a website to begin tracking public SEO and performance.</span>
          <button class="btn btn-primary btn-sm" type="button" data-wm-add>Add Website</button>
        </div>`;
      return;
    }

    if (!filtered.length) {
      list.innerHTML = '<div class="wm-site-list-empty"><strong>No matches</strong><span>Try a different website name or filter.</span></div>';
      return;
    }

    list.innerHTML = filtered.map(site => {
      const latest = latestFor(site);
      const health = metricValue(site, 'health_score');
      const averageRank = metricValue(site, 'average_rank');
      const issueCount = numberOrNull(firstValue(site.open_issue_count, site.open_issues, latest.open_issue_count));
      const scanning = state.scanningIds.has(String(site.id));
      const selected = sameId(site.id, state.selectedId);
      const typeLabel = site.site_type === 'owned' ? 'Owned' : 'Observed';
      return `
        <button class="wm-site-item${selected ? ' selected' : ''}" type="button" data-site-id="${h(site.id)}" aria-pressed="${selected ? 'true' : 'false'}">
          <span class="wm-site-item-top">
            <span class="wm-site-name">${h(site.name)}</span>
            ${scanning ? '<span class="spinner wm-site-spinner" aria-label="Scan running"></span>' : scorePill(health)}
          </span>
          <span class="wm-site-domain">${h(hostFromUrl(site.url) || site.url || 'No URL')}</span>
          <span class="wm-site-item-meta">
            <span class="badge ${site.site_type === 'owned' ? 'badge-blue' : 'badge-purple'}">${typeLabel}</span>
            ${averageRank !== null ? `<span>Avg. rank ${h(formatDecimal(averageRank))}</span>` : '<span>Not scanned</span>'}
            ${issueCount !== null ? `<span>${h(formatInteger(issueCount))} open</span>` : ''}
          </span>
        </button>`;
    }).join('');
  }

  async function selectSite(id) {
    if (id === undefined || id === null || id === '') return;
    state.selectedId = String(id);
    state.detail = null;
    localStorage.setItem(SELECTED_SITE_KEY, state.selectedId);
    renderSiteList();

    const summarySite = state.sites.find(site => sameId(site.id, id));
    showDetailLoading(summarySite);

    try {
      const payload = await request(`${API_ROOT}/sites/${encodeURIComponent(id)}`);
      if (!sameId(state.selectedId, id)) return;
      state.detail = normalizeDetail(payload || {});
      renderDetail();
    } catch (error) {
      if (!sameId(state.selectedId, id)) return;
      showNoSelection('Could not load this website', error.message || 'Try refreshing Website Monitor.');
      notify('Failed to load website details', 'error');
    }
  }

  function showDetailLoading(site) {
    el('wmDetail').hidden = true;
    const empty = el('wmDetailEmpty');
    empty.hidden = false;
    empty.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> Loading ${h(site && site.name ? site.name : 'website')}...</div>`;
  }

  function showNoSelection(title, text, includeAdd = false) {
    el('wmDetail').hidden = true;
    const empty = el('wmDetailEmpty');
    empty.hidden = false;
    empty.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon" aria-hidden="true">&#9673;</div>
        <div class="empty-state-title">${h(title)}</div>
        <p class="empty-state-text">${h(text)}</p>
        ${includeAdd ? '<button class="btn btn-primary wm-empty-add" type="button" data-wm-add-detail>Add Website</button>' : ''}
      </div>`;
    const addButton = empty.querySelector('[data-wm-add-detail]');
    if (addButton) addButton.addEventListener('click', () => openSiteModal('add'));
  }

  function showSiteListError(message) {
    el('wmSiteList').innerHTML = `<div class="wm-site-list-empty"><strong>Unable to load</strong><span>${h(message)}</span></div>`;
  }

  function renderDetail() {
    if (!state.detail) return;
    const { site, latestRun, rankings, issues, history } = state.detail;
    el('wmDetailEmpty').hidden = true;
    el('wmDetail').hidden = false;

    el('wmDetailName').textContent = site.name;
    const typeBadge = el('wmDetailType');
    typeBadge.textContent = site.site_type === 'owned' ? 'Owned' : 'Observed';
    typeBadge.className = `badge ${site.site_type === 'owned' ? 'badge-blue' : 'badge-purple'}`;

    const safeUrl = safeHttpUrl(site.url);
    const urlLink = el('wmDetailUrl');
    urlLink.textContent = site.url || 'No URL configured';
    urlLink.href = safeUrl || '#';
    if (safeUrl) {
      urlLink.removeAttribute('aria-disabled');
      urlLink.removeAttribute('tabindex');
    } else {
      urlLink.setAttribute('aria-disabled', 'true');
      urlLink.setAttribute('tabindex', '-1');
    }

    const finishedAt = firstValue(latestRun.finished_at, latestRun.completed_at, latestRun.started_at, site.last_scanned_at);
    const meta = [
      site.location ? `Location: ${site.location}` : 'Location: Broad search',
      `Device: ${capitalize(site.device || 'mobile')}`,
      finishedAt ? `Last scan: ${formatDateSafe(finishedAt)}` : 'No completed scan',
    ];
    el('wmDetailMeta').innerHTML = meta.map(value => `<span>${h(value)}</span>`).join('');

    const scanning = state.scanningIds.has(String(site.id));
    renderScanState(scanning, latestRun);

    const health = metricFromRun(latestRun, site, 'health_score');
    const technical = metricFromRun(latestRun, site, 'technical_score');
    const performance = metricFromRun(latestRun, site, 'performance_score');
    const seo = metricFromRun(latestRun, site, 'seo_score');
    const averageRank = metricFromRun(latestRun, site, 'average_rank') ?? averageRankFromRows(rankings);
    const topTen = metricFromRun(latestRun, site, 'top_10') ?? rankings.filter(row => {
      const rank = rankNumber(firstValue(row.current_rank, row.position, row.rank, row.rank_absolute));
      return rank !== null && rank <= 10;
    }).length;
    const rankedKeywords = metricFromRun(latestRun, site, 'ranked_keywords') ?? rankings.filter(row => {
      return rankNumber(firstValue(row.current_rank, row.position, row.rank, row.rank_absolute)) !== null;
    }).length;
    const totalKeywords = metricFromRun(latestRun, site, 'total_keywords') ?? (rankings.length || site.keywords.length);

    paintScore('wmHealthScore', 'wmHealthTrack', 'wmHealthBar', health);
    paintScore('wmPerformanceScore', 'wmPerformanceTrack', 'wmPerformanceBar', performance);
    setSmallScore('wmTechnicalScore', technical);
    setSmallScore('wmSeoScore', seo);
    el('wmAverageRank').textContent = averageRank === null ? '--' : formatDecimal(averageRank);
    el('wmTopTen').textContent = topTen === null ? '--' : formatInteger(topTen);
    el('wmRankedKeywords').textContent = rankedKeywords === null ? '--' : formatInteger(rankedKeywords);
    el('wmTotalKeywords').textContent = formatInteger(totalKeywords || 0);

    el('wmPerformanceCaption').textContent = performance === null
      ? 'Performance was not available in the latest public scan.'
      : `${scoreDescription(performance)} public performance score on ${capitalize(site.device || 'mobile')}.`;
    el('wmVisibilityCaption').textContent = site.location
      ? `Public keyword results for ${site.location} on ${site.device || 'mobile'}.`
      : `Public keyword results on ${site.device || 'mobile'} without a local market.`;
    el('wmRankingSubtitle').textContent = site.keywords.length
      ? `${site.keywords.length} tracked keyword${site.keywords.length === 1 ? '' : 's'} · ${site.location || 'Broad location'} · ${capitalize(site.device || 'mobile')}`
      : 'Add target keywords to begin public search position tracking';

    renderRankings(rankings, site);
    renderIssues(issues);
    renderHistory(history, latestRun);
    renderTrackingConfiguration(site);
  }

  function renderScanState(scanning, latestRun) {
    const button = el('wmRunScanBtn');
    const status = el('wmScanStatus');
    button.disabled = scanning;
    button.setAttribute('aria-busy', scanning ? 'true' : 'false');
    button.innerHTML = scanning
      ? '<span class="spinner wm-button-spinner"></span> Scanning'
      : 'Run Scan';

    if (scanning) {
      status.className = 'wm-scan-status running';
      status.innerHTML = '<span class="spinner wm-status-spinner"></span><span>Checking public site health, performance, and search visibility...</span>';
      return;
    }

    const runStatus = String(firstValue(latestRun.status, '')).toLowerCase();
    if (runStatus === 'failed' || runStatus === 'error') {
      status.className = 'wm-scan-status failed';
      status.textContent = firstValue(latestRun.error, latestRun.message, 'The latest scan did not finish. You can run it again.');
    } else {
      status.className = 'wm-scan-status';
      status.textContent = '';
    }
  }

  function paintScore(valueId, trackId, barId, value) {
    const valueElement = el(valueId);
    const track = el(trackId);
    const bar = el(barId);
    const numeric = clampScore(value);
    valueElement.textContent = numeric === null ? '--' : formatInteger(numeric);
    valueElement.className = `wm-metric-value ${scoreTone(numeric)}`;
    bar.style.width = `${numeric === null ? 0 : numeric}%`;
    bar.className = scoreTone(numeric);
    track.setAttribute('aria-valuenow', numeric === null ? '0' : String(Math.round(numeric)));
    track.setAttribute('aria-valuetext', numeric === null ? 'Not measured' : `${Math.round(numeric)} out of 100`);
  }

  function setSmallScore(id, value) {
    const target = el(id);
    const numeric = clampScore(value);
    target.textContent = numeric === null ? '--' : formatInteger(numeric);
    target.className = scoreTone(numeric);
  }

  function setScoreText(target, value) {
    const numeric = clampScore(value);
    target.textContent = numeric === null ? '--' : formatInteger(numeric);
    target.className = `stat-value ${scoreTone(numeric)}`;
  }

  function scorePill(value) {
    const numeric = clampScore(value);
    if (numeric === null) return '<span class="wm-score-pill empty">--</span>';
    return `<span class="wm-score-pill ${scoreTone(numeric)}">${h(formatInteger(numeric))}</span>`;
  }

  function scoreTone(value) {
    if (value === null || value === undefined) return 'wm-score-empty';
    if (value >= 80) return 'wm-score-good';
    if (value >= 50) return 'wm-score-warning';
    return 'wm-score-bad';
  }

  function scoreDescription(value) {
    if (value >= 80) return 'Strong';
    if (value >= 50) return 'Needs attention';
    return 'Poor';
  }

  function renderRankings(rankings, site) {
    const body = el('wmRankingsBody');
    if (!rankings.length) {
      const message = site.keywords.length
        ? 'No ranking results yet. Run a scan to check these keywords.'
        : 'No keywords are configured. Edit this website to add search terms.';
      body.innerHTML = `<tr><td colspan="6"><div class="wm-table-empty">${h(message)}</div></td></tr>`;
      return;
    }

    const sorted = [...rankings].sort((a, b) => {
      const aRank = rankNumber(firstValue(a.current_rank, a.position, a.rank, a.rank_absolute));
      const bRank = rankNumber(firstValue(b.current_rank, b.position, b.rank, b.rank_absolute));
      return (aRank ?? 9999) - (bRank ?? 9999);
    });

    body.innerHTML = sorted.map(row => {
      const current = rankNumber(firstValue(row.current_rank, row.position, row.rank, row.rank_absolute));
      const previous = rankNumber(firstValue(row.previous_rank, row.previous_position, row.previous_rank_absolute));
      const explicitChange = numberOrNull(firstValue(row.change, row.rank_change));
      const change = explicitChange ?? (current !== null && previous !== null ? previous - current : null);
      const pageUrl = safeHttpUrl(firstValue(row.ranking_url, row.url, row.page_url));
      const competitors = asArray(row.competitors || row.top_competitors).map(competitor => {
        if (competitor && typeof competitor === 'object') {
          return firstValue(competitor.domain, competitor.name, competitor.url, competitor.title, '');
        }
        return competitor;
      }).filter(Boolean);
      return `
        <tr>
          <td class="wm-keyword-cell">${h(firstValue(row.keyword, row.query, 'Unknown keyword'))}</td>
          <td>${rankBadge(current)}</td>
          <td>${previous === null ? '<span class="text-muted">--</span>' : h(formatInteger(previous))}</td>
          <td>${changeMarkup(change)}</td>
          <td>${pageUrl ? `<a class="wm-ranking-link" href="${h(pageUrl)}" target="_blank" rel="noopener noreferrer" title="${h(pageUrl)}">${h(shortUrl(pageUrl))}</a>` : '<span class="text-muted">Not ranking</span>'}</td>
          <td><span class="wm-competitors" title="${h(competitors.join(', '))}">${competitors.length ? h(competitors.slice(0, 3).join(', ')) : '<span class="text-muted">--</span>'}</span></td>
        </tr>`;
    }).join('');
  }

  function rankBadge(rank) {
    if (rank === null) return '<span class="badge badge-gray">100+</span>';
    const badgeClass = rank <= 3 ? 'badge-green' : rank <= 10 ? 'badge-blue' : rank <= 20 ? 'badge-amber' : 'badge-gray';
    return `<span class="badge ${badgeClass}">${h(formatInteger(rank))}</span>`;
  }

  function changeMarkup(change) {
    if (change === null || change === undefined) return '<span class="text-muted">--</span>';
    const numeric = Number(change);
    if (!Number.isFinite(numeric) || numeric === 0) return '<span class="wm-rank-change neutral">0</span>';
    const improved = numeric > 0;
    return `<span class="wm-rank-change ${improved ? 'up' : 'down'}"><span aria-hidden="true">${improved ? '&#8593;' : '&#8595;'}</span> ${h(Math.abs(numeric))}<span class="wm-visually-hidden"> position${Math.abs(numeric) === 1 ? '' : 's'} ${improved ? 'improved' : 'declined'}</span></span>`;
  }

  function renderIssues(issues) {
    const severityOrder = { critical: 0, high: 1, medium: 2, warning: 2, low: 3, info: 4 };
    const sorted = [...issues].sort((a, b) => {
      const aOpen = issueIsOpen(a) ? 0 : 1;
      const bOpen = issueIsOpen(b) ? 0 : 1;
      if (aOpen !== bOpen) return aOpen - bOpen;
      return (severityOrder[String(a.severity || '').toLowerCase()] ?? 5)
        - (severityOrder[String(b.severity || '').toLowerCase()] ?? 5);
    });
    const openCount = sorted.filter(issueIsOpen).length;
    const countBadge = el('wmIssueCount');
    countBadge.textContent = `${openCount} open`;
    countBadge.className = `badge ${openCount ? 'badge-amber' : 'badge-green'}`;

    if (!sorted.length) {
      el('wmIssuesList').innerHTML = `
        <div class="wm-section-empty wm-section-empty-success">
          <strong>No issues found</strong>
          <span>Run scans regularly to catch new public SEO or performance problems.</span>
        </div>`;
      return;
    }

    el('wmIssuesList').innerHTML = sorted.map(issue => {
      const severity = String(firstValue(issue.severity, 'info')).toLowerCase();
      const open = issueIsOpen(issue);
      const message = firstValue(issue.message, issue.title, issue.issue, 'Website issue');
      const recommendation = firstValue(issue.recommendation, issue.fix, issue.action, '');
      return `
        <article class="wm-issue-item${open ? '' : ' resolved'}">
          <div class="wm-issue-topline">
            <span class="badge ${severityBadge(severity)}">${h(capitalize(severity))}</span>
            <span class="wm-issue-category">${h(firstValue(issue.category, 'General'))}</span>
            ${open ? '' : '<span class="badge badge-green">Resolved</span>'}
          </div>
          <h3>${h(message)}</h3>
          ${recommendation ? `<p><strong>Next step:</strong> ${h(recommendation)}</p>` : ''}
        </article>`;
    }).join('');
  }

  function issueIsOpen(issue) {
    const status = String(firstValue(issue.status, 'open')).toLowerCase();
    return !['resolved', 'closed', 'fixed', 'dismissed'].includes(status);
  }

  function severityBadge(severity) {
    if (severity === 'critical' || severity === 'high') return 'badge-red';
    if (severity === 'medium' || severity === 'warning') return 'badge-amber';
    if (severity === 'low') return 'badge-blue';
    return 'badge-gray';
  }

  function renderHistory(history, latestRun) {
    let runs = [...history];
    if (!runs.length && latestRun && Object.keys(latestRun).length) runs = [latestRun];
    runs.sort((a, b) => {
      const aTime = new Date(firstValue(a.finished_at, a.started_at, 0)).getTime() || 0;
      const bTime = new Date(firstValue(b.finished_at, b.started_at, 0)).getTime() || 0;
      return bTime - aTime;
    });

    if (!runs.length) {
      el('wmHistoryBody').innerHTML = '<tr><td colspan="6"><div class="wm-table-empty">No scans have been run yet.</div></td></tr>';
      return;
    }

    el('wmHistoryBody').innerHTML = runs.map(run => {
      const status = String(firstValue(run.status, 'completed')).toLowerCase();
      const ranked = numberOrNull(run.ranked_keywords);
      const total = numberOrNull(run.total_keywords);
      return `
        <tr>
          <td>${h(formatDateSafe(firstValue(run.finished_at, run.started_at, run.created_at)))}</td>
          <td><span class="badge ${runStatusBadge(status)}">${h(capitalize(status))}</span></td>
          <td>${scoreCell(run.health_score)}</td>
          <td>${scoreCell(run.performance_score)}</td>
          <td>${rankNumber(run.average_rank) === null ? '<span class="text-muted">--</span>' : h(formatDecimal(run.average_rank))}</td>
          <td>${ranked === null ? '<span class="text-muted">--</span>' : `${h(formatInteger(ranked))}${total !== null ? ` / ${h(formatInteger(total))}` : ''}`}</td>
        </tr>`;
    }).join('');
  }

  function runStatusBadge(status) {
    if (status === 'completed' || status === 'success') return 'badge-green';
    if (status === 'completed_with_errors') return 'badge-amber';
    if (status === 'running' || status === 'accepted' || status === 'queued') return 'badge-blue';
    if (status === 'failed' || status === 'error') return 'badge-red';
    return 'badge-gray';
  }

  function scoreCell(value) {
    const numeric = clampScore(value);
    if (numeric === null) return '<span class="text-muted">--</span>';
    return `<span class="wm-inline-score ${scoreTone(numeric)}">${h(formatInteger(numeric))}</span>`;
  }

  function renderTrackingConfiguration(site) {
    el('wmKeywordList').innerHTML = site.keywords.length
      ? site.keywords.map(keyword => `<span class="wm-keyword-tag">${h(keyword)}</span>`).join('')
      : '<span class="text-muted">No keywords configured. Edit this website to add them.</span>';
    el('wmSiteNotes').textContent = site.notes || 'No notes added.';
  }

  function renderTypeExplainer() {
    const type = el('wmSiteType').value;
    el('wmTypeExplainer').innerHTML = type === 'owned'
      ? '<strong>Owned website</strong><span>Marks the site as yours for organization. Monitoring still uses public website and search data.</span>'
      : '<strong>Observed website</strong><span>Track a competitor or any other website using the same publicly visible signals.</span>';
  }

  function openSiteModal(mode) {
    const editing = mode === 'edit' && state.detail;
    const site = editing ? state.detail.site : null;
    const form = el('wmSiteForm');
    form.reset();
    form.dataset.mode = editing ? 'edit' : 'add';
    form.dataset.siteId = editing ? String(site.id) : '';
    el('wmSiteModalTitle').textContent = editing ? 'Edit Website' : 'Add Website';
    el('wmSaveSiteBtn').textContent = editing ? 'Save Changes' : 'Save Website';
    el('wmSiteFormError').hidden = true;
    el('wmSiteFormError').textContent = '';
    el('wmSiteUrl').setCustomValidity('');

    if (editing) {
      el('wmSiteName').value = site.name || '';
      el('wmSiteUrl').value = site.url || '';
      el('wmSiteType').value = normalizeSiteType(site.site_type);
      el('wmSiteLocation').value = site.location || '';
      el('wmSiteDevice').value = site.device === 'desktop' ? 'desktop' : 'mobile';
      el('wmSiteKeywords').value = asStringList(site.keywords).join('\n');
      el('wmSiteNotesInput').value = site.notes || '';
    } else {
      el('wmSiteType').value = 'owned';
      el('wmSiteDevice').value = 'mobile';
    }

    renderTypeExplainer();
    openModal(el('wmSiteModal'), el('wmSiteName'));
  }

  function openDeleteModal() {
    if (!state.detail) return;
    el('wmDeleteSiteName').textContent = state.detail.site.name;
    openModal(el('wmDeleteModal'), el('wmConfirmDeleteBtn'));
  }

  function openModal(modal, focusTarget) {
    state.modalReturnFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add('wm-modal-open');
    window.setTimeout(() => focusTarget && focusTarget.focus(), 0);
  }

  function closeModal(kind) {
    const modal = kind === 'delete' ? el('wmDeleteModal') : el('wmSiteModal');
    modal.hidden = true;
    if (el('wmDeleteModal').hidden && el('wmSiteModal').hidden) {
      document.body.classList.remove('wm-modal-open');
    }
    if (state.modalReturnFocus && typeof state.modalReturnFocus.focus === 'function') {
      state.modalReturnFocus.focus();
    }
    state.modalReturnFocus = null;
  }

  function handleModalKeyboard(event) {
    const modal = !el('wmDeleteModal').hidden
      ? el('wmDeleteModal')
      : !el('wmSiteModal').hidden ? el('wmSiteModal') : null;
    if (!modal) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      closeModal(modal.id === 'wmDeleteModal' ? 'delete' : 'site');
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]')]
      .filter(node => node.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function saveWebsite(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const urlInput = el('wmSiteUrl');
    const normalizedUrl = normalizeHttpUrl(urlInput.value);
    if (normalizedUrl) urlInput.value = normalizedUrl;
    urlInput.setCustomValidity(normalizedUrl ? '' : 'Enter a valid HTTP or HTTPS website URL.');

    if (!form.reportValidity()) return;

    const payload = {
      name: el('wmSiteName').value.trim(),
      url: normalizedUrl,
      site_type: normalizeSiteType(el('wmSiteType').value),
      location: el('wmSiteLocation').value.trim(),
      device: el('wmSiteDevice').value === 'desktop' ? 'desktop' : 'mobile',
      notes: el('wmSiteNotesInput').value.trim(),
      keywords: asStringList(el('wmSiteKeywords').value),
    };
    const editing = form.dataset.mode === 'edit';
    const siteId = form.dataset.siteId;
    const saveButton = el('wmSaveSiteBtn');
    const originalText = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = editing ? 'Saving Changes...' : 'Adding Website...';
    el('wmSiteFormError').hidden = true;

    try {
      const response = await request(
        editing ? `${API_ROOT}/sites/${encodeURIComponent(siteId)}` : `${API_ROOT}/sites`,
        { method: editing ? 'PUT' : 'POST', body: payload },
      );
      const returnedSite = response && response.site ? response.site : response;
      const savedId = firstValue(returnedSite && returnedSite.id, returnedSite && returnedSite.site_id, siteId);
      closeModal('site');
      notify(editing ? 'Website tracking updated' : 'Website added to monitoring', 'success');
      await reloadOverviewAndSites();
      if (savedId !== undefined && savedId !== null && savedId !== '') {
        await selectSite(savedId);
      } else if (state.sites.length) {
        await selectSite(state.sites[0].id);
      }
    } catch (error) {
      const errorBox = el('wmSiteFormError');
      errorBox.textContent = error.message || 'The website could not be saved.';
      errorBox.hidden = false;
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = originalText;
    }
  }

  async function deleteSelectedWebsite() {
    if (!state.detail) return;
    const siteId = state.detail.site.id;
    const button = el('wmConfirmDeleteBtn');
    button.disabled = true;
    button.textContent = 'Deleting...';
    try {
      await request(`${API_ROOT}/sites/${encodeURIComponent(siteId)}`, { method: 'DELETE' });
      closeModal('delete');
      state.scanningIds.delete(String(siteId));
      state.selectedId = null;
      state.detail = null;
      localStorage.removeItem(SELECTED_SITE_KEY);
      notify('Website removed from monitoring', 'success');
      await reloadOverviewAndSites();
      if (state.sites.length) {
        await selectSite(state.sites[0].id);
      } else {
        showNoSelection('No websites tracked yet', 'Add any website you own or want to observe, then run its first public scan.', true);
      }
    } catch (error) {
      notify(error.message || 'Website could not be deleted', 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Delete Website';
    }
  }

  async function runSelectedScan() {
    if (!state.detail) return;
    const siteId = state.detail.site.id;
    if (state.scanningIds.has(String(siteId))) return;
    const button = el('wmRunScanBtn');
    button.disabled = true;

    try {
      const response = await request(`${API_ROOT}/sites/${encodeURIComponent(siteId)}/scan`, { method: 'POST' });
      if (response && response.accepted === false) {
        throw new Error(firstValue(response.error, response.message, 'The scan could not be started.'));
      }
      state.scanningIds.add(String(siteId));
      renderOverview();
      renderSiteList();
      renderScanState(true, state.detail.latestRun || {});
      notify('Public website scan started', 'info');

      const status = String(response && response.status || '').toLowerCase();
      if (['completed', 'success'].includes(status)) {
        state.scanningIds.delete(String(siteId));
        await refreshMonitor();
      } else {
        schedulePoll(500);
      }
    } catch (error) {
      notify(error.message || 'Scan could not be started', 'error');
      button.disabled = false;
    }
  }

  function schedulePoll(delay = POLL_DELAY_MS) {
    clearTimeout(state.pollTimer);
    state.pollTimer = window.setTimeout(pollScanStatus, delay);
  }

  async function pollScanStatus() {
    if (state.polling) return;
    state.polling = true;
    try {
      const payload = await request(`${API_ROOT}/scans/status`);
      const wasRunning = state.scanningIds.size > 0;
      const isRunning = applyScanStatus(payload, true);
      renderOverview();
      renderSiteList();
      if (state.detail) renderScanState(state.scanningIds.has(String(state.detail.site.id)), state.detail.latestRun || {});

      if (isRunning || state.scanningIds.size) {
        schedulePoll();
      } else if (wasRunning) {
        await reloadOverviewAndSites();
        if (state.selectedId && state.sites.some(site => sameId(site.id, state.selectedId))) {
          await selectSite(state.selectedId);
        }
      }
    } catch (error) {
      if (state.scanningIds.size) schedulePoll(5000);
    } finally {
      state.polling = false;
    }
  }

  function applyScanStatus(payload, showMessages) {
    const statuses = Array.isArray(payload)
      ? payload
      : Array.isArray(payload && payload.scans) ? payload.scans : [payload || {}];
    const runningIds = new Set();
    let anyRunning = false;

    statuses.forEach(status => {
      const running = Boolean(status && status.running);
      const siteId = firstValue(status && status.site_id, status && status.siteId);
      if (running) {
        anyRunning = true;
        if (siteId !== undefined && siteId !== null) runningIds.add(String(siteId));
      }
      if (showMessages && !running && status && status.error) {
        const key = `${siteId || 'scan'}:${status.error}`;
        if (state.lastScanMessage !== key) {
          notify(String(status.error), 'error');
          state.lastScanMessage = key;
        }
      }
    });

    if (anyRunning) {
      if (runningIds.size) runningIds.forEach(id => state.scanningIds.add(id));
    } else {
      state.scanningIds.clear();
    }
    return anyRunning;
  }

  async function refreshMonitor() {
    const button = el('wmRefreshBtn');
    button.disabled = true;
    button.textContent = 'Refreshing...';
    try {
      await reloadOverviewAndSites();
      if (state.selectedId && state.sites.some(site => sameId(site.id, state.selectedId))) {
        await selectSite(state.selectedId);
      } else if (state.sites.length) {
        await selectSite(state.sites[0].id);
      } else {
        showNoSelection('No websites tracked yet', 'Add any website you own or want to observe, then run its first public scan.', true);
      }
    } catch (error) {
      notify(error.message || 'Website Monitor could not be refreshed', 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Refresh';
    }
  }

  async function reloadOverviewAndSites() {
    const [summaryResult, sitesResult] = await Promise.allSettled([
      request(`${API_ROOT}/summary`),
      request(`${API_ROOT}/sites`),
    ]);
    if (summaryResult.status === 'rejected' && sitesResult.status === 'rejected') {
      throw summaryResult.reason || sitesResult.reason || new Error('Unable to refresh websites.');
    }
    if (summaryResult.status === 'fulfilled') state.summary = summaryResult.value || {};
    if (sitesResult.status === 'fulfilled') {
      state.sites = normalizeSiteCollection(sitesResult.value);
    } else if (summaryResult.status === 'fulfilled') {
      state.sites = normalizeSiteCollection(state.summary.sites || []);
    }
    syncScanningFromSummary();
    renderProviderNotice();
    renderOverview();
    renderSiteList();
  }

  function metricValue(site, key) {
    const run = latestFor(site);
    const alias = key === 'health_score' ? 'overall_score' : key;
    return numberOrNull(firstValue(
      site[key], site[alias], run[key], run[alias], site[`latest_${key}`], site[`latest_${alias}`],
    ));
  }

  function metricFromRun(run, site, key) {
    const alias = key === 'health_score' ? 'overall_score' : key;
    const summary = run && run.summary && typeof run.summary === 'object' ? run.summary : {};
    const rankingSummary = summary.rankings && typeof summary.rankings === 'object' ? summary.rankings : {};
    const scoreSummary = summary.scores && typeof summary.scores === 'object' ? summary.scores : {};
    const rankingAliases = {
      average_rank: 'average_rank',
      top_10: 'top_10',
      ranked_keywords: 'ranking',
      total_keywords: 'tracked',
    };
    const scoreAliases = {
      health_score: 'overall',
      technical_score: 'technical',
      performance_score: 'performance',
      seo_score: 'seo',
      visibility_score: 'visibility',
    };
    return numberOrNull(firstValue(
      run && run[key], run && run[alias],
      site && site[key], site && site[alias],
      site && site[`latest_${key}`], site && site[`latest_${alias}`],
      rankingSummary[rankingAliases[key]], scoreSummary[scoreAliases[key]],
    ));
  }

  function averageRankFromRows(rows) {
    const values = rows
      .map(row => rankNumber(firstValue(row.current_rank, row.position, row.rank, row.rank_absolute)))
      .filter(value => value !== null);
    if (!values.length) return null;
    return values.reduce((total, value) => total + value, 0) / values.length;
  }

  function numberOrNull(value) {
    if (value === undefined || value === null || value === '') return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function rankNumber(value) {
    const numeric = numberOrNull(value);
    return numeric !== null && numeric > 0 ? numeric : null;
  }

  function clampScore(value) {
    const numeric = numberOrNull(value);
    return numeric === null ? null : Math.max(0, Math.min(100, numeric));
  }

  function formatInteger(value) {
    const numeric = numberOrNull(value);
    return numeric === null ? '--' : Math.round(numeric).toLocaleString();
  }

  function formatDecimal(value) {
    const numeric = numberOrNull(value);
    if (numeric === null) return '--';
    return numeric.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }

  function formatDateSafe(value) {
    if (!value) return 'Unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], {
      year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  }

  function capitalize(value) {
    const text = String(value || '');
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
  }

  function normalizeHttpUrl(value) {
    let candidate = String(value || '').trim();
    if (!candidate) return '';
    if (!/^https?:\/\//i.test(candidate)) candidate = `https://${candidate}`;
    try {
      const parsed = new URL(candidate);
      return ['http:', 'https:'].includes(parsed.protocol) && parsed.hostname ? parsed.href : '';
    } catch {
      return '';
    }
  }

  function safeHttpUrl(value) {
    return normalizeHttpUrl(value) || null;
  }

  function hostFromUrl(value) {
    const normalized = normalizeHttpUrl(value);
    if (!normalized) return String(value || '').replace(/^https?:\/\//i, '').split('/')[0];
    try { return new URL(normalized).hostname.replace(/^www\./i, ''); } catch { return ''; }
  }

  function shortUrl(value) {
    try {
      const parsed = new URL(value);
      const path = parsed.pathname === '/' ? '' : parsed.pathname;
      const result = `${parsed.hostname.replace(/^www\./i, '')}${path}`;
      return result.length > 42 ? `${result.slice(0, 39)}...` : result;
    } catch {
      return String(value || '');
    }
  }

  function sameId(left, right) {
    return String(left) === String(right);
  }

  function h(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function notify(message, type) {
    if (typeof toast === 'function') toast(message, type);
  }
})();
