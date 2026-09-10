# Storm Damage Band

High-urgency rapid-response section for roofers in hail/wind country (Colorado Front Range is prime territory).

**Section structure:**
- Full-width, high-contrast band — 35-45vh
- Background: darkened stormy-sky visual — either a scraped photo with dark gradient OR a CSS gradient (slate-900 → slate-700 with a subtle noise texture)
- Top-left corner: animated SVG lightning or raindrop accent, muted
- Content stack, centered, max-width 800px:
  - Eyebrow in warning-orange ("Storm Damage")
  - H2 (display, 36-44px, white): "Hail just came through. We're already dispatching inspections."
  - Subhead (18px, muted-white, 20-30 words): "{business_name} handles insurance claim documentation start to finish. Free roof inspection within 48 hours of any qualifying storm."
  - Two CTAs side-by-side: primary filled "Request Free Inspection" → form or booking URL, secondary outline "Call Now: {phone}"
  - Small trust line: "Licensed · Insured · Xactimate-certified estimates" (only include items the scrape confirms)

**Motion:**
- On-load: lightning SVG briefly flashes opacity 0 → 1 → 0.3, repeats every ~6s with a slight random jitter
- Content block: slides up from 20px, fades in, 500ms
- Hover on primary CTA: filled button shifts half-shade darker, shadow deepens
- Subtle rain-line overlay: thin diagonal lines translating slowly via CSS `@keyframes` (only on desktop, disabled on mobile for perf)

**Rules:**
- Include this section ONLY when scraped data mentions storm / hail / insurance / claim / emergency — never add to a straight "new roof install" roofer.
- Never invent dispatch timelines. "48 hours" is fine as industry-standard language. "Next-day guaranteed" is a contract — don't write that unless scrape confirms.
- Respect prefers-reduced-motion: disable lightning flash and rain overlay — keep static dark bg with content.
- Accessibility: ensure text contrast ≥ 4.5:1 on the dark bg. Test warning-orange eyebrow against slate.
