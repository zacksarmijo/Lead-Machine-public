document.addEventListener('DOMContentLoaded', async () => {
  try {
    const data = await api('/api/dashboard/stats');
    document.getElementById('statTotal').textContent = data.total_leads.toLocaleString();
    document.getElementById('statActionable').textContent = data.actionable.toLocaleString();

    const pipelineKeys = Object.keys(data.pipeline || {});
    document.getElementById('statPipeline').textContent = pipelineKeys.length;
    const bucketKeys = Object.keys(data.web_buckets || {});
    document.getElementById('statBuckets').textContent = bucketKeys.length;

    // Pipeline list
    const plEl = document.getElementById('pipelineList');
    if (pipelineKeys.length) {
      plEl.innerHTML = pipelineKeys.map(k =>
        `<div class="flex justify-between items-center mb-sm">
          <span><span class="badge ${pipelineBadge(k)}">${esc(k)}</span></span>
          <span class="text-muted">${data.pipeline[k]}</span>
        </div>`
      ).join('');
    } else {
      plEl.innerHTML = '<div class="text-muted">No pipeline data yet</div>';
    }

    // Bucket list
    const bkEl = document.getElementById('bucketList');
    if (bucketKeys.length) {
      bkEl.innerHTML = bucketKeys.map(k =>
        `<div class="flex justify-between items-center mb-sm">
          <span><span class="badge ${webBucketBadge(k)}">${esc(k)}</span></span>
          <span class="text-muted">${data.web_buckets[k]}</span>
        </div>`
      ).join('');
    } else {
      bkEl.innerHTML = '<div class="text-muted">No web bucket data yet</div>';
    }

    // Recent runs
    const tbody = document.getElementById('runsBody');
    if (data.recent_runs && data.recent_runs.length) {
      tbody.innerHTML = data.recent_runs.map(r =>
        `<tr>
          <td>${esc(formatDate(r.started_at))}</td>
          <td>${esc(r.seed_mode)}</td>
          <td><span class="badge ${r.status === 'completed' ? 'badge-green' : r.status === 'running' ? 'badge-blue' : 'badge-red'}">${esc(r.status)}</span></td>
          <td>${r.lead_count || 0}</td>
        </tr>`
      ).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="4" class="text-muted" style="text-align:center;padding:24px;">No runs yet. Go to Discovery to start your first scan.</td></tr>';
    }
  } catch (err) {
    console.error('Dashboard load error:', err);
    toast('Failed to load dashboard data', 'error');
  }
});
