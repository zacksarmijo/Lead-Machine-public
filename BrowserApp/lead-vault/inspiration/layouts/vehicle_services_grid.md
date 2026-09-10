# Vehicle Services Grid

Service categories for auto repair, body shops, tire shops, detailing.

**Section structure:**
- Eyebrow ("Services", "What We Fix", "Repairs & Maintenance")
- H2 (display, 30-38px) — sans-serif, industrial feel, not decorative
- Grid: 3 columns desktop, 2 tablet, 1 mobile
- Categories: each card is a broad service group (Brakes, Diagnostics, Transmission, Tires, Oil & Fluids, Electrical)

**Card anatomy:**
- Background: surface color with 1px border
- Top: large outlined SVG icon, 40px — brake disc, gear, battery, tire tread, spark plug, engine silhouette. Industrial/technical style, not cartoony.
- Service group name (H3, condensed sans, 20-24px, uppercase)
- 2-3 sub-service bullets using scraped data (e.g. "Brake pads · Rotors · Fluid flush")
- Optional "Starting at $X" price pill at bottom-right if scraped
- Entire card is clickable — links to a scroll anchor on a dedicated contact block or `tel:`

**Motion:**
- On scroll into viewport: cards slide up 12px, fade in, 100ms stagger
- Card hover: icon fills from outline → solid (stroke → fill transition, 220ms), border goes accent color, card lifts 3px
- "Starting at $X" pill pulses briefly on hover

**Rules:**
- Only show services the scrape returned. Do NOT auto-generate a "Transmission" card for a shop that doesn't mention transmission work.
- Price pills only when explicitly scraped — legal/consumer-protection territory.
- Use technical icons. No cartoon wrenches or smiling cars.
- Consider a second trust row below the grid: ASE-certified, AAA-approved, BBB-rated — only for badges the scrape confirms.
- Bonus: if scraped data has a vehicle-make specialization (e.g. "We specialize in European imports"), add it as a small banner above the grid.
