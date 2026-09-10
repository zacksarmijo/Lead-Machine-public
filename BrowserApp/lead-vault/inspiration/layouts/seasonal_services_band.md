# Seasonal Services Band

Time-of-year urgency band. For HVAC, landscapers, roofers — any biz whose demand cycles.

**Section structure:**
- Full-width band, 30-40vh
- Background: seasonal gradient — warm oranges for fall, cool blues for winter, greens for spring, gold for summer. Determine from current month. Fallback to accent gradient.
- Content: 3-column strip desktop, 1-column mobile
  - Each column: large season icon (SVG — sun, snowflake, leaf, bud), season label, 1-line service ("Snow Removal", "Spring Cleanup", "AC Tune-Up", "Fall Aeration")
  - Below the 3 columns: centered primary CTA "Book Seasonal Service" linking to scraped booking URL or `tel:`

**Motion:**
- On scroll into viewport: 3 columns fade+slide up with 150ms stagger
- Active-season column (matching current month) has a soft glow animation on its icon (box-shadow pulse, 3s loop)
- Hover on a column: column lifts 4px, icon rotates 8deg and back (220ms ease-out)

**Rules:**
- Only list seasonal services the scrape actually surfaces. Do not invent "snow removal" for a business that doesn't mention it.
- Current-season determination uses a tiny inline script. Northern hemisphere assumption is fine for Colorado leads.
- Keep it visual, not crowded. Max 4 seasonal services.
- If scrape has zero seasonal signal, skip this section entirely.
- Respect prefers-reduced-motion: disable glow and hover rotate.
