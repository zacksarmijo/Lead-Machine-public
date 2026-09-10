# Case Results Strip

Credibility via concrete numbers. For law firms, consultancies, contractors — any business where "proof of past work" drives conversion.

**Section structure:**
- Full-width horizontal band, 260-320px tall desktop
- Background: near-black or dark brand primary color, creating visual gravitas
- Centered row of 3-5 metrics, equal columns

**Metric column anatomy:**
- Large number (display font, 56-72px, white or accent color, tabular-nums)
- Optional small prefix/suffix ($, +, M, years)
- Label below number (uppercase, tracking-wide, 12px, muted-white)
- Example pattern:
  - "$45M+ recovered for clients"
  - "500+ cases tried"
  - "25 years of practice"
  - "98% success rate"

**Motion:**
- On scroll into viewport: numbers count up from 0 to target value over 1200-1500ms, eased-out cubic
- Subtle number glow animation once the count settles (accent box-shadow pulse, 600ms single fade)
- Thin vertical divider lines between columns animate in from the center

**Rules:**
- Use ONLY numbers the scrape explicitly returned. Never invent metrics for a law firm — these can become the basis of bar-association discipline.
- If no hard numbers found, skip this section entirely. Do not show "Decades of experience" vague placeholder text in a results strip.
- Claims like "success rate" or "% recovery" are legally sensitive — include a small footnote on the strip: "Past results do not guarantee future outcomes." when any percentage or dollar amount is shown.
- Format numbers clean: `$45M` not `$45,000,000`. `500+` not `537`. Round to impress without deceiving.
- Respect prefers-reduced-motion: disable count-up animation, show final numbers statically.
