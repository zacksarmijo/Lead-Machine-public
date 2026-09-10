/* ===== Visual Website Grading ===== */

/**
 * Website grading display engine.
 * Official top-line scores come from BACKEND (source of truth).
 * Category breakdowns are indicative visual helpers only.
 */

// ── Grade mapping (backend 5-tier scale) ────────
// Prefer displaying backend_grade directly. This is for
// category visual breakdowns only.

function numericToGrade(score) {
  if (score >= 80) return 'A';
  if (score >= 60) return 'B';
  if (score >= 40) return 'C';
  if (score >= 20) return 'D';
  return 'F';
}

function gradeColor(grade) {
  if (!grade) return 'gray';
  const letter = grade.charAt(0);
  if (letter === 'A') return 'green';
  if (letter === 'B') return 'blue';
  if (letter === 'C') return 'amber';
  if (letter === 'D') return 'amber';
  return 'red';
}

function gradeBadgeClass(grade) {
  return `badge-${gradeColor(grade)}`;
}

// ── Evidence extraction helpers ──────────────────

function _str(val) {
  if (val == null || val === '') return '';
  return String(val).trim();
}

function _has(val) {
  const s = _str(val).toLowerCase();
  return s !== '' && s !== '--' && s !== 'none' && s !== 'none found' && s !== 'n/a'
    && !s.startsWith('could not') && !s.startsWith('not evaluated');
}

function _positive(val) {
  const s = _str(val).toLowerCase();
  return s.includes('found') || s.includes('good') || s.includes('strong')
    || s.includes('yes') || s.includes('present') || s.includes('detected')
    || s.includes('clear') || s.includes('healthy') || s.includes('modern');
}

function _negative(val) {
  const s = _str(val).toLowerCase();
  return s.includes('not found') || s.includes('missing') || s.includes('weak')
    || s.includes('poor') || s.includes('no ') || s.includes('none')
    || s.includes('fail') || s.includes('broken') || s.includes('needs work');
}

function _hasTerms(val) {
  const s = _str(val);
  return s !== '' && s.toLowerCase() !== 'none' && s.toLowerCase() !== 'none found';
}

// ── Category scorers (INDICATIVE VISUAL ONLY) ───
// These do NOT drive official top-line scores.
// Each returns { score: 0-100, reasons: string[] }

function scoreDesign(audit, data) {
  let score = 50;
  const reasons = [];

  const bucket = _str(audit.website_bucket || data['Website Bucket']);
  if (bucket === 'Established website') { score += 25; reasons.push('Classified as established website'); }
  else if (bucket === 'Basic live site') { score += 10; reasons.push('Basic but functional live site'); }
  else if (bucket === 'Weak live site') { score -= 10; reasons.push('Classified as weak live site'); }
  else if (bucket === 'Broken site' || bucket === 'No website') { score -= 30; reasons.push('Site is broken or missing'); }

  const imgCount = parseInt(audit.image_count || data['Image Count']) || 0;
  if (imgCount >= 5) { score += 10; reasons.push(`${imgCount} images suggest visual content`); }
  else if (imgCount === 0) { score -= 5; reasons.push('No images detected'); }

  const imgQuality = _str(audit.image_quality_signal || data['Image Quality Signal']);
  if (_positive(imgQuality)) { score += 5; }
  else if (_negative(imgQuality)) { score -= 5; reasons.push('Image quality signal is weak'); }

  const navQuality = _str(audit.navigation_quality || data['Navigation Quality']);
  if (_positive(navQuality)) { score += 5; }

  const wordCount = parseInt(audit.word_count || data['Word Count']) || 0;
  if (wordCount >= 200) { score += 5; }
  else if (wordCount > 0 && wordCount < 50) { score -= 5; reasons.push('Very thin page content'); }

  if (reasons.length === 0) reasons.push('Insufficient evidence to assess design');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreMobile(audit, data) {
  let score = 50;
  const reasons = [];

  const mobile = _str(audit.mobile_readiness || data['Mobile Readiness']);
  const viewport = _str(audit.viewport_meta || data['Viewport Meta']);

  if (mobile.toLowerCase().includes('found') || viewport.toLowerCase().includes('found')) {
    score += 30;
    reasons.push('Mobile viewport meta tag detected');
  } else if (mobile.toLowerCase().includes('not found') || viewport.toLowerCase().includes('not found')) {
    score -= 20;
    reasons.push('No mobile viewport meta tag found');
  } else if (_has(mobile)) {
    if (_negative(mobile)) { score -= 10; reasons.push('Mobile readiness needs work'); }
    else { score += 15; reasons.push('Some mobile readiness signals present'); }
  } else {
    reasons.push('Mobile readiness could not be fully evaluated');
  }

  const fetchTime = parseInt(audit.fetch_time_ms || data['Fetch Time Ms']) || 0;
  if (fetchTime > 0 && fetchTime < 2000) { score += 10; reasons.push(`Fast page load (${fetchTime}ms)`); }
  else if (fetchTime >= 5000) { score -= 10; reasons.push(`Slow page load (${fetchTime}ms)`); }

  if (reasons.length === 0) reasons.push('No mobile evidence available');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreTrust(audit, data) {
  let score = 50;
  const reasons = [];

  const phones = _str(audit.on_page_phones || data['On-Page Phones']);
  const emails = _str(audit.on_page_emails || data['On-Page Emails']);

  if (_hasTerms(phones)) { score += 15; reasons.push('Phone number visible on page'); }
  if (_hasTerms(emails)) { score += 10; reasons.push('Email address visible on page'); }
  if (!_hasTerms(phones) && !_hasTerms(emails)) {
    score -= 15;
    reasons.push('No visible contact information on page');
  }

  const ssl = _str(audit.ssl_status || data['SSL Status']);
  if (ssl.toLowerCase().includes('valid') || ssl.toLowerCase().includes('https') || _positive(ssl)) {
    score += 10;
  } else if (_negative(ssl) || ssl.toLowerCase().includes('fail') || ssl.toLowerCase().includes('invalid')) {
    score -= 15;
    reasons.push('SSL/security issues detected');
  }

  const imgCount = parseInt(audit.image_count || data['Image Count']) || 0;
  if (imgCount >= 3) { score += 5; }
  else { reasons.push('Few visible trust elements or proof signals'); }

  if (reasons.length === 0) reasons.push('Trust signals appear adequate');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreCTA(audit, data) {
  let score = 40;
  const reasons = [];

  const ctaStrength = _str(audit.cta_strength || data['CTA Strength']);
  const ctaTerms = _str(audit.cta_terms || data['CTA Terms']);

  if (_hasTerms(ctaTerms)) {
    const terms = ctaTerms.split(/[,;]+/).filter(t => t.trim());
    if (terms.length >= 3) { score += 30; reasons.push(`Strong CTA presence (${terms.length} action terms found)`); }
    else if (terms.length >= 1) { score += 15; reasons.push(`CTA terms detected: ${terms.slice(0, 3).join(', ')}`); }
  } else {
    score -= 10;
    reasons.push('No clear call-to-action terms detected');
  }

  if (_positive(ctaStrength)) { score += 15; }
  else if (_negative(ctaStrength)) { score -= 10; reasons.push('CTA strength rated as weak'); }

  const formCount = parseInt(audit.form_count || data['Form Count']) || 0;
  if (formCount >= 1) { score += 10; reasons.push('At least one form available for conversion'); }
  else { reasons.push('No forms detected on page'); }

  if (reasons.length === 0) reasons.push('CTA evidence is limited');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreContact(audit, data) {
  let score = 40;
  const reasons = [];

  const contactForm = _str(audit.contact_form_status || data['Contact Form Status']);
  if (_positive(contactForm) || contactForm.toLowerCase().includes('found')) {
    score += 20;
    reasons.push('Contact form or path detected');
  } else if (_negative(contactForm)) {
    score -= 10;
    reasons.push('Contact form is weak or missing');
  }

  const bookingFlow = _str(audit.booking_flow_status || data['Booking Flow Status']);
  const bookingTerms = _str(audit.booking_terms || data['Booking Terms']);
  if (_hasTerms(bookingTerms) || _positive(bookingFlow)) {
    score += 20;
    reasons.push('Booking or quote flow detected');
  }

  const phones = _str(audit.on_page_phones || data['On-Page Phones']);
  const emails = _str(audit.on_page_emails || data['On-Page Emails']);
  if (_hasTerms(phones)) { score += 10; }
  if (_hasTerms(emails)) { score += 5; }
  if (!_hasTerms(phones) && !_hasTerms(emails) && !_positive(contactForm)) {
    reasons.push('No clear contact path for visitors');
  }

  const formCount = parseInt(audit.form_count || data['Form Count']) || 0;
  if (formCount >= 2) { score += 5; reasons.push(`${formCount} forms provide multiple contact paths`); }

  if (reasons.length === 0) reasons.push('Contact flow evidence is limited');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreSEO(audit, data) {
  let score = 50;
  const reasons = [];

  const pageTitle = _str(audit.page_title || data['Page Title']);
  if (pageTitle && pageTitle.length > 10) { score += 15; reasons.push('Page title is present and descriptive'); }
  else if (pageTitle) { score += 5; reasons.push('Page title is short or generic'); }
  else { score -= 10; reasons.push('No page title detected'); }

  const metaDesc = _str(audit.meta_description || data['Meta Description']);
  if (metaDesc && metaDesc.length > 30) { score += 15; }
  else if (!metaDesc) { score -= 10; reasons.push('No meta description found'); }

  const seoBasics = _str(audit.seo_basics || data['SEO Basics']);
  if (_positive(seoBasics)) { score += 10; }
  else if (_negative(seoBasics)) { score -= 10; reasons.push('SEO basics are lacking'); }

  const wordCount = parseInt(audit.word_count || data['Word Count']) || 0;
  if (wordCount >= 300) { score += 5; }
  else if (wordCount > 0 && wordCount < 100) { score -= 5; reasons.push('Very thin content for SEO'); }

  const linkCount = parseInt(audit.internal_link_count || data['Internal Link Count']) || 0;
  if (linkCount >= 5) { score += 5; }

  if (reasons.length === 0) reasons.push('SEO fundamentals appear adequate');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

function scoreTechnical(audit, data) {
  let score = 60;
  const reasons = [];

  const ssl = _str(audit.ssl_status || data['SSL Status']);
  if (_positive(ssl) || ssl.toLowerCase().includes('valid') || ssl.toLowerCase().includes('https')) {
    score += 15;
    reasons.push('SSL certificate is valid');
  } else if (_negative(ssl)) {
    score -= 20;
    reasons.push('SSL/security issues present');
  }

  const httpStatus = parseInt(audit.http_status || data['HTTP Status']) || 0;
  if (httpStatus === 200) { score += 10; }
  else if (httpStatus >= 400) { score -= 20; reasons.push(`HTTP ${httpStatus} error response`); }

  const fetchTime = parseInt(audit.fetch_time_ms || data['Fetch Time Ms']) || 0;
  if (fetchTime > 0 && fetchTime < 1500) { score += 10; reasons.push(`Good response time (${fetchTime}ms)`); }
  else if (fetchTime >= 3000) { score -= 10; reasons.push(`Slow response time (${fetchTime}ms)`); }

  const pageSpeed = _str(audit.page_speed_signal || data['Page Speed Signal']);
  if (_positive(pageSpeed)) { score += 5; }
  else if (_negative(pageSpeed)) { score -= 5; }

  const bucket = _str(audit.website_bucket || data['Website Bucket']);
  if (bucket === 'Broken site') { score -= 25; reasons.push('Site classified as broken'); }

  if (reasons.length === 0) reasons.push('Technical health could not be fully assessed');
  return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 2) };
}

// ── Verdict badge class ─────────────────────────

function verdictBadgeClass(verdict) {
  if (!verdict) return 'badge-gray';
  const v = verdict.toLowerCase();
  if (v.includes('high opportunity') || v === 'hot lead' || v === 'high confidence') return 'badge-green';
  if (v.includes('good opportunity') || v === 'promising') return 'badge-green';
  if (v.includes('moderate')) return 'badge-amber';
  if (v.includes('low opportunity')) return 'badge-blue';
  if (v.includes('needs review') || v.includes('manual review')) return 'badge-purple';
  return 'badge-gray';
}

// ── Main grading function ────────────────────────
// Official scores come from backend. Categories are visual only.

function computeWebsiteGrading(lead) {
  const audit = lead.latest_audit || {};
  const data = getPayload(lead);

  // ── Backend truth (source of truth) ──
  const backendQuality = lead.website_quality_score ?? data['Website Quality Score'] ?? null;
  const backendGrade = lead.website_grade || data['Website Grade'] || '';
  const backendOpp = lead.opportunity_score ?? data['Opportunity Score'] ?? null;
  const backendLabel = lead.opportunity_label || data['Opportunity Label'] || '';
  const backendConfidence = lead.audit_confidence || data['Audit Confidence'] || '';
  const backendConfidenceScore = lead.audit_confidence_score ?? data['Audit Confidence Score'] ?? null;
  const backendReviewBucket = lead.review_bucket || data['Review Bucket'] || '';
  const backendSuppressed = lead.suppressed === true || (typeof lead.suppressed === 'undefined' &&
    (backendLabel.toLowerCase().includes('strong site') ||
     (data['Opportunity Breakdown'] || '').toLowerCase().includes('suppressor')));
  const backendDisqualified = lead.disqualified === true || (typeof lead.disqualified === 'undefined' &&
    (data['Opportunity Breakdown'] || '').includes('DISQUALIFIED'));

  // ── Category breakdown (indicative visual only) ──
  const categories = {
    design: scoreDesign(audit, data),
    mobile: scoreMobile(audit, data),
    trust: scoreTrust(audit, data),
    cta: scoreCTA(audit, data),
    contact: scoreContact(audit, data),
    seo: scoreSEO(audit, data),
    technical: scoreTechnical(audit, data),
  };

  for (const cat of Object.values(categories)) {
    cat.grade = numericToGrade(cat.score);
  }

  // ── Use backend values for official top-line ──
  const siteQuality = (backendQuality != null && backendQuality > 0) ? backendQuality : 0;
  const siteQualityGrade = backendGrade || numericToGrade(siteQuality);
  const opportunity = (backendOpp != null) ? backendOpp : 0;
  const opportunityGrade = numericToGrade(opportunity);
  const confidence = backendConfidence || 'Low';
  const suppressed = backendSuppressed;
  const disqualified = backendDisqualified;

  // Verdict: use backend label, fall back to review bucket
  let verdict = backendLabel || backendReviewBucket || 'Needs review';

  // Gather strengths & improvement areas (from indicative categories)
  const strengths = [];
  const improvements = [];
  const categoryMeta = {
    design: 'Design / Professionalism',
    mobile: 'Mobile Experience',
    trust: 'Trust / Credibility',
    cta: 'CTA / Conversion Strength',
    contact: 'Contact / Booking Flow',
    seo: 'SEO / Discoverability',
    technical: 'Technical Health / Performance',
  };

  const sorted = Object.entries(categories).sort((a, b) => b[1].score - a[1].score);
  for (const [key, cat] of sorted) {
    if (cat.score >= 70) {
      strengths.push(categoryMeta[key]);
    } else if (cat.score < 60) {
      improvements.push(categoryMeta[key]);
    }
  }
  if (improvements.length === 0) {
    for (const [key, cat] of sorted.reverse()) {
      if (cat.score < 70 && !improvements.includes(categoryMeta[key])) {
        improvements.push(categoryMeta[key]);
        if (improvements.length >= 2) break;
      }
    }
  }

  // Freshness
  const freshness = _str(audit.data_freshness || data['Data Freshness'] || audit.audited_at || '');

  return {
    siteQuality,
    siteQualityGrade,
    opportunity,
    opportunityGrade,
    confidence,
    confidenceScore: backendConfidenceScore,
    verdict,
    suppressed,
    disqualified,
    freshness,
    categories,
    categoryMeta,
    strengths: strengths.slice(0, 4),
    improvements: improvements.slice(0, 4),
  };
}

// ── UI Renderer ──────────────────────────────────

function renderWebsiteGrading(containerId, lead) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const bucket = _str((lead.latest_audit || {}).website_bucket || getPayload(lead)['Website Bucket']);
  if (!bucket || bucket === 'No website' || bucket === 'Social-only presence' || bucket === 'Directory-only presence') {
    container.innerHTML = `
      <div class="card">
        <div class="card-body" style="text-align:center;padding:40px;color:var(--text-muted)">
          <div style="font-size:24px;margin-bottom:8px">N/A</div>
          <div>Website grading is not available for leads without a live website.</div>
          <div style="margin-top:4px">Classification: <strong>${esc(bucket || 'Unknown')}</strong></div>
        </div>
      </div>`;
    return;
  }

  const g = computeWebsiteGrading(lead);

  // Top grades row
  const topRow = `
    <div class="grading-top-row">
      <div class="grade-card grade-card-primary">
        <div class="grade-card-label">Site Quality</div>
        <div class="grade-card-value ${gradeBadgeClass(g.siteQualityGrade)}-text">${esc(g.siteQualityGrade)}</div>
        <div class="grade-card-sub">${g.siteQuality}/100</div>
      </div>
      <div class="grade-card grade-card-primary">
        <div class="grade-card-label">Opportunity</div>
        <div class="grade-card-value ${gradeBadgeClass(g.opportunityGrade)}-text">${esc(g.opportunityGrade)}</div>
        <div class="grade-card-sub">${g.opportunity}/100</div>
      </div>
      <div class="grade-card">
        <div class="grade-card-label">Confidence</div>
        <div class="grade-card-value grade-card-value-sm">${esc(g.confidence)}</div>
        <div class="grade-card-sub">${g.confidenceScore != null ? g.confidenceScore + '/100 evidence coverage' : (g.confidence === 'High' ? 'Strong evidence' : g.confidence === 'Medium' ? 'Partial evidence' : 'Limited evidence')}</div>
      </div>
      <div class="grade-card">
        <div class="grade-card-label">Verdict</div>
        <div class="grade-card-verdict"><span class="badge ${verdictBadgeClass(g.verdict)}">${esc(g.verdict)}</span></div>
        ${g.disqualified ? '<div class="grade-card-sub" style="color:var(--badge-red)">Disqualified — already-strong site</div>' : ''}
        ${g.suppressed && !g.disqualified ? '<div class="grade-card-sub" style="color:var(--badge-amber)">Suppressed — site already strong</div>' : ''}
      </div>
    </div>`;

  // Category rows (indicative visual breakdown)
  const catRows = Object.entries(g.categories).map(([key, cat]) => {
    const name = g.categoryMeta[key];
    const color = gradeColor(cat.grade);
    const reasonsHtml = cat.reasons.map(r => `<li>${esc(r)}</li>`).join('');
    return `
      <div class="grading-cat-row">
        <div class="grading-cat-name">${esc(name)}</div>
        <div class="grading-cat-grade">
          <span class="grading-grade-pill badge-${color}">${esc(cat.grade)}</span>
        </div>
        <div class="grading-cat-bar-wrap">
          <div class="grading-cat-bar grading-bar-${color}" style="width:${cat.score}%"></div>
        </div>
        <div class="grading-cat-reasons"><ul>${reasonsHtml}</ul></div>
      </div>`;
  }).join('');

  // Strengths & improvements
  const strengthsList = g.strengths.length
    ? g.strengths.map(s => `<li class="grading-strength-item">${esc(s)}</li>`).join('')
    : '<li class="text-muted">No strong categories identified</li>';
  const improvementsList = g.improvements.length
    ? g.improvements.map(s => `<li class="grading-improvement-item">${esc(s)}</li>`).join('')
    : '<li class="text-muted">No major improvement areas identified</li>';

  container.innerHTML = `
    <div class="card mb-md">
      <div class="card-header">Website Grade Overview</div>
      <div class="card-body">
        ${topRow}
      </div>
    </div>
    <div class="card mb-md">
      <div class="card-header">Category Breakdown <span style="font-weight:normal;font-size:12px;color:var(--text-muted)">(indicative)</span></div>
      <div class="card-body grading-cat-container">
        ${catRows}
      </div>
    </div>
    <div class="card">
      <div class="card-header">Summary</div>
      <div class="card-body">
        <div class="grading-summary-grid">
          <div>
            <div class="grading-summary-title" style="color:var(--badge-green)">Strengths</div>
            <ul class="grading-summary-list">${strengthsList}</ul>
          </div>
          <div>
            <div class="grading-summary-title" style="color:var(--badge-amber)">Improvement Areas</div>
            <ul class="grading-summary-list">${improvementsList}</ul>
          </div>
        </div>
      </div>
    </div>`;
}
