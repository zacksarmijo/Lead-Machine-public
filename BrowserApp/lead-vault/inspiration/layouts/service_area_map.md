# Service Area Map

"Do you serve my town?" objection killer for trades: plumbers, electricians, HVAC, roofers, landscapers.

**Section structure:**
- Two columns desktop (40/60), stacked mobile.

**Left (40%) — Area list:**
- Eyebrow ("Service Area", "Where We Work")
- H2 (28-36px, display font)
- One-line lede: "Serving {primary_city} and surrounding communities."
- Two-column bullet list of cities/zips the scrape returned, checkmark SVG icon before each
- Primary CTA: "Not on the list? Call us" → `tel:` link

**Right (60%) — Visual map:**
- Stylized SVG map tile — a simplified outline of the Colorado Front Range (or the state region relevant to scraped city) with dotted accent-colored markers for each served city
- Do NOT embed Google Maps — no API, licensing headaches. Hand-draw or use a generic silhouette.
- Alternative: a soft blueprint-style background (pale accent grid) with city name pins floating over it
- Rounded corners (12px), subtle border

**Motion:**
- On scroll into viewport: city pins drop in one-by-one from above (translateY -8px → 0, opacity 0 → 1), 120ms stagger
- Pin hover: scales 1.15x, shows a tooltip with city name in accent color
- List checkmarks: draw-on animation (stroke-dasharray trick) when section enters viewport, once only

**Rules:**
- Only list service areas the scrape explicitly returned. Never invent "and all surrounding areas" as a cover.
- If scraped data has zero service-area info, fall back to: "Serving {city_area} · Call to check availability" single line, skip the map, use a trust-badge row instead.
- Map is illustrative only — include a tiny footnote: "Map is illustrative, not to scale."
- Respect prefers-reduced-motion: disable the pin drop, show them static.
