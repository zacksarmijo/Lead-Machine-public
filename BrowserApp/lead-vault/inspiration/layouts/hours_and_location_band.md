# Hours and Location Band

Two-column section blending visit info with a sense of place. For restaurants, salons, retail, brick-and-mortar service.

**Section structure:**
- Two columns desktop (50/50), stacked mobile. Surface background, not pure white.

**Left column — Info stack:**
- Eyebrow ("Visit", "Find Us", "Stop By")
- H2 (display font, 28-36px)
- Address block: street, city-state-zip, each on own line, large (18px), with a small pin SVG icon
- Hours table: day + hours, aligned in two columns inside the cell, zebra-stripe rows with subtle alternating surface tint
- "Today is open / closed" dynamic badge: green dot + "Open now" if current day/time matches, else amber "Closed · opens at X". Implement with a small inline `<script>` reading `navigator` locale, no external lib
- Phone link as `tel:` with phone SVG icon, accent color
- Small row of directional links: "Apple Maps · Google Maps · Get Directions" — each opens in `_blank` with `rel="noopener noreferrer"`

**Right column — Visual:**
- Static map image OR styled map embed placeholder (do NOT embed Google Maps iframe if no API key — use a stylized SVG map tile or a neighborhood illustration instead)
- Rounded corners (12px)
- Subtle drop shadow
- 4:3 or 1:1 aspect

**Motion:**
- On-load: left column slides in from left (16px), right column fades in
- "Open now" badge: soft pulse animation on the dot (scale 1 → 1.2 → 1, 2s loop) only if Open
- Hours row hover: row surface lifts to next tint

**Rules:**
- Only include days the scrape actually returned. Missing hours → render "Hours: call for current hours" single line, no fake fill-in.
- Address MUST be exactly what the scrape returned. Never hallucinate.
- Map visual must not claim a specific Google Maps license. Keep it stylized/illustrative if no API.
- Keep the "Open now" logic simple; if timezone is unknown, fall back to listing hours without the live badge.
