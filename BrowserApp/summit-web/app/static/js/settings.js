const AI_MODELS = {
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

let _savedModel = '';
let AREA_PRESETS = {};
const CUSTOM_AREA_VALUE = '__custom__';
let SCAN_PROFILE_PRESETS = {};
let TARGETING_PRESETS = {};
let OPPORTUNITY_FOCUS_PRESETS = {};
let AUTOMATION_INTENSITY_PRESETS = {};

document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
});

function setSecretInput(id, isSet) {
  const input = document.getElementById(id);
  if (!input) return;
  input.value = '';
  input.placeholder = isSet ? 'Saved key hidden' : '';
}

function updateModelDropdown(selectedModel) {
  const provider = document.getElementById('cfgAiProvider').value;
  const sel = document.getElementById('cfgAiModel');
  const models = AI_MODELS[provider] || [];
  sel.innerHTML = models.map(m =>
    `<option value="${m.value}">${m.label}</option>`
  ).join('');
  // Set to the passed model, or the saved model if it matches this provider, or the first option
  const target = selectedModel || _savedModel || '';
  const hasMatch = models.some(m => m.value === target);
  if (hasMatch) {
    sel.value = target;
  } else {
    sel.selectedIndex = 0;
  }
}

async function loadSettings() {
  try {
    const s = await api('/api/settings');

    // Lead Machine
    document.getElementById('cfgGoogleKey').value = s.google_maps_api_key || '';
    document.getElementById('cfgHunterKey').value = s.hunter_api_key || '';
    document.getElementById('cfgDataForSeoLogin').value = s.dataforseo_login || '';
    document.getElementById('cfgDataForSeoPassword').value = s.dataforseo_password || '';
    document.getElementById('cfgYelpKey').value = s.yelp_api_key || '';
    document.getElementById('cfgCaliforniaSosKey').value = s.california_sos_api_key || '';
    document.getElementById('cfgPageSpeedKey').value = s.pagespeed_api_key || '';
    document.getElementById('cfgBuiltWithKey').value = s.builtwith_api_key || '';
    document.getElementById('cfgOutputFolder').value = s.output_folder || '';
    document.getElementById('cfgSeedMode').value = s.seed_mode || 'Hybrid';
    document.getElementById('cfgGridSize').value = s.tile_grid_size || '3';
    document.getElementById('cfgMinRating').value = s.min_rating || '4.0';
    document.getElementById('cfgMinReviews').value = s.min_reviews || '10';
    document.getElementById('cfgMinAge').value = s.min_business_age_days || '90';
    document.getElementById('cfgFastLimit').value = s.fast_test_lead_limit || '75';
    document.getElementById('cfgFastCap').value = s.fast_test_total_run_cap || '';
    document.getElementById('cfgFastTest').checked = !!s.fast_test_mode;
    document.getElementById('cfgSkipEmail').checked = !!s.skip_email_lookup;
    document.getElementById('cfgBrowserFallback').checked = s.enable_browser_fallback !== false;
    document.getElementById('cfgDomainChecks').checked = s.enable_domain_checks !== false;
    document.getElementById('cfgRdapChecks').checked = !!s.enable_rdap_checks;
    document.getElementById('cfgPageSpeedChecks').checked = !!s.enable_pagespeed_checks;
    document.getElementById('cfgPageSpeedStrategy').value = s.pagespeed_strategy || 'mobile';
    document.getElementById('cfgPageSpeedRunCap').value = s.pagespeed_run_cap || '10';
    document.getElementById('cfgBuiltWithChecks').checked = !!s.enable_builtwith_checks;
    document.getElementById('cfgBuiltWithRunCap').value = s.builtwith_run_cap || '10';
    document.getElementById('cfgClientName').value = s.client_name || '';
    document.getElementById('cfgAutomationAgentReviewLimit').value = s.automation_agent_review_limit || '10';
    loadTargetingControls(s);
    const areas = s.search_areas || [];
    document.getElementById('cfgAreas').value = areas.join('\n');
    loadAreaPresets(s.search_area_presets || {}, areas);
    setSecretInput('cfgGoogleKey', !!s.google_maps_api_key_set);
    setSecretInput('cfgHunterKey', !!s.hunter_api_key_set);
    setSecretInput('cfgDataForSeoPassword', !!s.dataforseo_password_set);
    setSecretInput('cfgYelpKey', !!s.yelp_api_key_set);
    setSecretInput('cfgCaliforniaSosKey', !!s.california_sos_api_key_set);
    setSecretInput('cfgPageSpeedKey', !!s.pagespeed_api_key_set);
    setSecretInput('cfgBuiltWithKey', !!s.builtwith_api_key_set);

    // Lead Vault / AI
    document.getElementById('cfgDbPath').value = s.db_path || '';
    document.getElementById('cfgAiProvider').value = s.ai_provider || 'OpenAI';
    _savedModel = s.ai_model || '';
    updateModelDropdown(_savedModel);
    setSecretInput('cfgOpenaiKey', !!s.openai_api_key_set);
    setSecretInput('cfgAnthropicKey', !!s.anthropic_api_key_set);
    document.getElementById('cfgAgencyName').value = s.agency_name || '';
    document.getElementById('cfgOfferPos').value = s.offer_positioning || '';
  } catch (e) {
    console.error('Load settings error:', e);
    toast('Failed to load settings', 'error');
  }
}

function loadOptionSelect(selectId, options, selectedValue, fallbackValue) {
  const select = document.getElementById(selectId);
  if (!select) return;
  select.innerHTML = '';
  Object.entries(options || {}).forEach(([value, label]) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = typeof label === 'string' ? label : value;
    select.appendChild(option);
  });
  select.value = selectedValue || fallbackValue || select.options[0]?.value || '';
}

function loadTargetingControls(settings) {
  SCAN_PROFILE_PRESETS = settings.scan_profile_presets || {};
  TARGETING_PRESETS = settings.targeting_category_presets || {};
  OPPORTUNITY_FOCUS_PRESETS = settings.opportunity_focus_presets || {};
  AUTOMATION_INTENSITY_PRESETS = settings.automation_intensity_presets || {};
  const targetOptions = {};
  Object.keys(TARGETING_PRESETS).forEach((name) => { targetOptions[name] = name; });
  const scanOptions = {};
  Object.keys(SCAN_PROFILE_PRESETS).forEach((name) => { scanOptions[name] = name; });
  loadOptionSelect('cfgScanProfile', scanOptions, settings.scan_profile_name || 'Custom', 'Custom');
  loadOptionSelect('cfgTargetProfile', targetOptions, settings.target_profile_name || 'All supported', 'All supported');
  loadOptionSelect('cfgOpportunityFocus', OPPORTUNITY_FOCUS_PRESETS, settings.opportunity_focus || 'any', 'any');
  loadOptionSelect('cfgAutomationIntensity', AUTOMATION_INTENSITY_PRESETS, settings.automation_intensity || 'normal', 'normal');
  document.getElementById('cfgTargetKeywords').value = (settings.target_category_keywords || []).join('\n');
  const scanSelect = document.getElementById('cfgScanProfile');
  if (scanSelect) {
    scanSelect.onchange = () => applyScanProfileDefaults(true);
  }
  const intensitySelect = document.getElementById('cfgAutomationIntensity');
  if (intensitySelect) {
    intensitySelect.onchange = applyAutomationIntensityDefaults;
  }
}

function applyScanProfileDefaults(showToast = false) {
  const profileName = document.getElementById('cfgScanProfile')?.value || 'Custom';
  const profile = SCAN_PROFILE_PRESETS[profileName] || {};
  if (!profile || profileName === 'Custom') return;
  if (profile.client_name !== undefined) document.getElementById('cfgClientName').value = profile.client_name;
  if (profile.target_profile_name) document.getElementById('cfgTargetProfile').value = profile.target_profile_name;
  if (Array.isArray(profile.target_category_keywords)) {
    document.getElementById('cfgTargetKeywords').value = normalizeAreaList(profile.target_category_keywords).join('\n');
  }
  if (profile.opportunity_focus) document.getElementById('cfgOpportunityFocus').value = profile.opportunity_focus;
  if (profile.min_rating !== undefined) document.getElementById('cfgMinRating').value = profile.min_rating;
  if (profile.min_reviews !== undefined) document.getElementById('cfgMinReviews').value = profile.min_reviews;
  if (profile.min_business_age_days !== undefined) document.getElementById('cfgMinAge').value = profile.min_business_age_days;
  if (profile.tile_grid_size !== undefined) document.getElementById('cfgGridSize').value = profile.tile_grid_size;
  if (profile.fast_test_lead_limit !== undefined && document.getElementById('cfgFastLimit')) {
    document.getElementById('cfgFastLimit').value = profile.fast_test_lead_limit;
  }
  if (profile.fast_test_total_run_cap !== undefined && document.getElementById('cfgFastCap')) {
    document.getElementById('cfgFastCap').value = profile.fast_test_total_run_cap;
  }
  if (profile.fast_test_mode !== undefined) document.getElementById('cfgFastTest').checked = !!profile.fast_test_mode;
  if (profile.skip_email_lookup !== undefined) document.getElementById('cfgSkipEmail').checked = !!profile.skip_email_lookup;
  applyAutomationIntensityDefaults();
  if (showToast) toast(`${profileName} scan profile applied`, 'success');
}

function loadAreaPresets(presets, currentAreas) {
  AREA_PRESETS = presets || {};
  const select = document.getElementById('cfgAreaPreset');
  if (!select) return;
  select.innerHTML = '';
  const customOption = document.createElement('option');
  customOption.value = CUSTOM_AREA_VALUE;
  customOption.textContent = 'Custom areas';
  select.appendChild(customOption);
  Object.keys(AREA_PRESETS).forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  select.onchange = () => applyAreaPreset(true);
  const textarea = document.getElementById('cfgAreas');
  if (textarea) {
    textarea.oninput = syncAreaPresetFromTextarea;
  }
  syncAreaPresetFromAreas(currentAreas || []);
  syncAreaPresetFromTextarea();
}

function normalizeArea(value) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function normalizeAreaList(areas) {
  const normalized = [];
  const seen = new Set();
  (areas || []).forEach((area) => {
    const clean = normalizeArea(area);
    const key = clean.toLowerCase();
    if (clean && !seen.has(key)) {
      seen.add(key);
      normalized.push(clean);
    }
  });
  return normalized;
}

function readSearchAreas() {
  const textarea = document.getElementById('cfgAreas');
  return normalizeAreaList((textarea?.value || '').split('\n'));
}

function readTargetKeywords() {
  const textarea = document.getElementById('cfgTargetKeywords');
  return normalizeAreaList((textarea?.value || '').split('\n'));
}

function applyAutomationIntensityDefaults() {
  const intensity = document.getElementById('cfgAutomationIntensity')?.value || 'normal';
  if (intensity !== 'heavy_week') return;
  document.getElementById('cfgFastTest').checked = false;
  document.getElementById('cfgSkipEmail').checked = false;
  const grid = document.getElementById('cfgGridSize');
  grid.value = String(Math.max(Number(grid.value || 3), 4));
}

function sameAreaList(left, right) {
  return normalizeAreaList(left).join('\n').toLowerCase() === normalizeAreaList(right).join('\n').toLowerCase();
}

function findMatchingPreset(areas) {
  return Object.entries(AREA_PRESETS).find(([, presetAreas]) => sameAreaList(presetAreas, areas));
}

function updateAreaSummary(areas, presetName) {
  const summary = document.getElementById('cfgAreaSummary');
  if (!summary) return;
  const count = normalizeAreaList(areas).length;
  const areaText = count === 1 ? 'area' : 'areas';
  summary.textContent = presetName ? `${presetName}: ${count} ${areaText}` : `${count} custom ${areaText}`;
}

function syncAreaPresetFromAreas(areas) {
  const select = document.getElementById('cfgAreaPreset');
  if (!select) return;
  const matchedPreset = findMatchingPreset(areas);
  select.value = matchedPreset ? matchedPreset[0] : CUSTOM_AREA_VALUE;
}

function syncAreaPresetFromTextarea() {
  const select = document.getElementById('cfgAreaPreset');
  const areas = readSearchAreas();
  syncAreaPresetFromAreas(areas);
  updateAreaSummary(areas, select && select.value !== CUSTOM_AREA_VALUE ? select.value : '');
}

function applyAreaPreset(showToast = false) {
  const select = document.getElementById('cfgAreaPreset');
  const textarea = document.getElementById('cfgAreas');
  if (!select || !textarea) return;
  if (select.value === CUSTOM_AREA_VALUE) {
    updateAreaSummary(readSearchAreas(), '');
    return;
  }
  const areas = AREA_PRESETS[select.value] || [];
  if (!areas.length) {
    toast('No areas found for that preset', 'error');
    return;
  }
  const normalizedAreas = normalizeAreaList(areas);
  textarea.value = normalizedAreas.join('\n');
  updateAreaSummary(normalizedAreas, select.value);
  if (showToast) {
    toast(`${select.value} areas loaded`, 'success');
  }
}

async function saveSettings() {
  const areas = readSearchAreas();
  document.getElementById('cfgAreas').value = areas.join('\n');

  const data = {
    // Lead Machine
    google_maps_api_key: document.getElementById('cfgGoogleKey').value,
    hunter_api_key: document.getElementById('cfgHunterKey').value,
    dataforseo_login: document.getElementById('cfgDataForSeoLogin').value,
    dataforseo_password: document.getElementById('cfgDataForSeoPassword').value,
    yelp_api_key: document.getElementById('cfgYelpKey').value,
    california_sos_api_key: document.getElementById('cfgCaliforniaSosKey').value,
    pagespeed_api_key: document.getElementById('cfgPageSpeedKey').value,
    builtwith_api_key: document.getElementById('cfgBuiltWithKey').value,
    output_folder: document.getElementById('cfgOutputFolder').value,
    seed_mode: document.getElementById('cfgSeedMode').value,
    tile_grid_size: document.getElementById('cfgGridSize').value,
    min_rating: document.getElementById('cfgMinRating').value,
    min_reviews: document.getElementById('cfgMinReviews').value,
    min_business_age_days: document.getElementById('cfgMinAge').value,
    fast_test_lead_limit: document.getElementById('cfgFastLimit').value,
    fast_test_total_run_cap: document.getElementById('cfgFastCap').value,
    fast_test_mode: document.getElementById('cfgFastTest').checked,
    skip_email_lookup: document.getElementById('cfgSkipEmail').checked,
    enable_browser_fallback: document.getElementById('cfgBrowserFallback').checked,
    enable_domain_checks: document.getElementById('cfgDomainChecks').checked,
    enable_rdap_checks: document.getElementById('cfgRdapChecks').checked,
    enable_pagespeed_checks: document.getElementById('cfgPageSpeedChecks').checked,
    pagespeed_strategy: document.getElementById('cfgPageSpeedStrategy').value,
    pagespeed_run_cap: document.getElementById('cfgPageSpeedRunCap').value,
    enable_builtwith_checks: document.getElementById('cfgBuiltWithChecks').checked,
    builtwith_run_cap: document.getElementById('cfgBuiltWithRunCap').value,
    search_areas: areas,
    client_name: document.getElementById('cfgClientName').value,
    scan_profile_name: document.getElementById('cfgScanProfile').value,
    target_profile_name: document.getElementById('cfgTargetProfile').value,
    target_category_keywords: readTargetKeywords(),
    opportunity_focus: document.getElementById('cfgOpportunityFocus').value,
    automation_intensity: document.getElementById('cfgAutomationIntensity').value,
    automation_agent_review_limit: document.getElementById('cfgAutomationAgentReviewLimit').value,

    // Lead Vault / AI
    db_path: document.getElementById('cfgDbPath').value,
    ai_provider: document.getElementById('cfgAiProvider').value,
    ai_model: document.getElementById('cfgAiModel').value,
    openai_api_key: document.getElementById('cfgOpenaiKey').value,
    anthropic_api_key: document.getElementById('cfgAnthropicKey').value,
    agency_name: document.getElementById('cfgAgencyName').value,
    offer_positioning: document.getElementById('cfgOfferPos').value,
  };

  try {
    await api('/api/settings', { method: 'PUT', body: data });
    _savedModel = data.ai_model;
    toast('Settings saved', 'success');
    document.getElementById('saveStatus').textContent = 'Saved just now';
  } catch (err) {
    toast('Failed to save settings', 'error');
  }
}
