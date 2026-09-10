let eventSource = null;
let logLineCount = 0;  // tracks how many lines we've received so far
let AREA_PRESETS = {};
const CUSTOM_AREA_VALUE = '__custom__';
let SCAN_PROFILE_PRESETS = {};
let TARGETING_PRESETS = {};
let OPPORTUNITY_FOCUS_PRESETS = {};
let AUTOMATION_INTENSITY_PRESETS = {};

document.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  await checkRunStatus();
});

async function loadConfig() {
  try {
    const s = await api('/api/settings');
    document.getElementById('cfgSeedMode').value = s.seed_mode || 'Hybrid';
    document.getElementById('cfgGridSize').value = s.tile_grid_size || '3';
    document.getElementById('cfgMinRating').value = s.min_rating || '4.0';
    document.getElementById('cfgMinReviews').value = s.min_reviews || '10';
    document.getElementById('cfgMinAge').value = s.min_business_age_days || '90';
    document.getElementById('cfgFastTest').checked = !!s.fast_test_mode;
    document.getElementById('cfgSkipEmail').checked = !!s.skip_email_lookup;
    document.getElementById('cfgBuiltWithChecks').checked = !!s.enable_builtwith_checks;
    document.getElementById('cfgBuiltWithRunCap').value = s.builtwith_run_cap || '10';
    document.getElementById('cfgClientName').value = s.client_name || '';
    loadTargetingControls(s);
    const areas = s.search_areas || [];
    document.getElementById('cfgAreas').value = areas.join('\n');
    loadAreaPresets(s.search_area_presets || {}, areas);
  } catch (e) { console.error('Load config error:', e); }
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

async function checkRunStatus() {
  try {
    const status = await api('/api/discovery/runs/status');
    if (status.status === 'running' || status.status === 'stopping') {
      setRunning(true);
      // Resume from where we left off (server tracks total log count)
      connectSSE(logLineCount);
    } else if (status.status === 'completed' || status.status === 'failed') {
      // Run finished while we were away — fetch any remaining logs
      if (status.log_count && status.log_count > logLineCount) {
        connectSSE(logLineCount);
      }
      setRunning(false);
      updateBadge(status.status === 'completed' ? 'Completed' : 'Failed',
                  status.status === 'completed' ? 'badge-green' : 'badge-red');
    }
  } catch (e) { /* idle */ }
}

async function startRun() {
  const areas = readSearchAreas();
  if (!areas.length) {
    toast('Add at least one search area', 'error');
    return;
  }
  document.getElementById('cfgAreas').value = areas.join('\n');

  const config = {
    seed_mode: document.getElementById('cfgSeedMode').value,
    tile_grid_size: document.getElementById('cfgGridSize').value,
    min_rating: document.getElementById('cfgMinRating').value,
    min_reviews: document.getElementById('cfgMinReviews').value,
    min_business_age_days: document.getElementById('cfgMinAge').value,
    fast_test_mode: document.getElementById('cfgFastTest').checked,
    skip_email_lookup: document.getElementById('cfgSkipEmail').checked,
    enable_builtwith_checks: document.getElementById('cfgBuiltWithChecks').checked,
    builtwith_run_cap: document.getElementById('cfgBuiltWithRunCap').value,
    search_areas: areas,
    client_name: document.getElementById('cfgClientName').value,
    scan_profile_name: document.getElementById('cfgScanProfile').value,
    target_profile_name: document.getElementById('cfgTargetProfile').value,
    target_category_keywords: readTargetKeywords(),
    opportunity_focus: document.getElementById('cfgOpportunityFocus').value,
    automation_intensity: document.getElementById('cfgAutomationIntensity').value,
  };

  try {
    const result = await api('/api/discovery/runs', { method: 'POST', body: config });
    if (result.ok) {
      document.getElementById('logViewer').textContent = '';
      logLineCount = 0;  // reset for new run
      setRunning(true);
      connectSSE(0);
      toast('Run started', 'success');
    } else {
      toast(result.error || 'Failed to start run', 'error');
    }
  } catch (err) {
    toast('Failed to start run', 'error');
  }
}

async function stopRun() {
  try {
    await api('/api/discovery/runs/stop', { method: 'POST' });
    toast('Stopping run...', 'info');
    updateBadge('Stopping', 'badge-amber');
  } catch (err) {
    toast('Failed to stop run', 'error');
  }
}

function setRunning(running) {
  document.getElementById('btnStartRun').disabled = running;
  document.getElementById('btnStopRun').disabled = !running;
  updateBadge(running ? 'Running' : 'Idle', running ? 'badge-blue' : 'badge-gray');
}

function updateBadge(text, cls) {
  const badge = document.getElementById('runStatusBadge');
  badge.textContent = text;
  badge.className = `badge ${cls}`;
}

function connectSSE(fromIndex) {
  if (eventSource) { eventSource.close(); eventSource = null; }

  const url = `/api/discovery/runs/logs?from_index=${fromIndex || 0}`;
  eventSource = new EventSource(url);
  const viewer = document.getElementById('logViewer');

  eventSource.onmessage = (e) => {
    viewer.textContent += e.data + '\n';
    viewer.scrollTop = viewer.scrollHeight;
    logLineCount++;
  };

  eventSource.addEventListener('done', (e) => {
    viewer.textContent += '\n' + e.data + '\n';
    viewer.scrollTop = viewer.scrollHeight;
    eventSource.close();
    eventSource = null;
    setRunning(false);

    if (e.data.includes('completed')) {
      updateBadge('Completed', 'badge-green');
      toast('Run completed successfully', 'success');
    } else {
      updateBadge('Failed', 'badge-red');
      toast('Run failed', 'error');
    }
  });

  eventSource.onerror = () => {
    // Connection dropped (navigation, network, etc.) — don't panic.
    // Close cleanly; checkRunStatus on next page load will reconnect.
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    // Don't set running=false here — the run continues in the background.
    // Only update badge to show we lost the live connection.
    updateBadge('Reconnecting...', 'badge-amber');
    // Try to reconnect after a short delay
    setTimeout(async () => {
      try {
        const status = await api('/api/discovery/runs/status');
        if (status.status === 'running' || status.status === 'stopping') {
          setRunning(true);
          connectSSE(logLineCount);
        } else {
          // Run finished while we were disconnected
          if (status.log_count && status.log_count > logLineCount) {
            connectSSE(logLineCount);
          } else {
            setRunning(false);
            updateBadge(status.status === 'completed' ? 'Completed' : status.status === 'failed' ? 'Failed' : 'Idle',
                        status.status === 'completed' ? 'badge-green' : status.status === 'failed' ? 'badge-red' : 'badge-gray');
          }
        }
      } catch (e) {
        setRunning(false);
        updateBadge('Disconnected', 'badge-red');
      }
    }, 2000);
  };
}
