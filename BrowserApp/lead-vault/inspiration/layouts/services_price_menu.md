# Services Price Menu

Transparent service list with prices. For salons, barbers, medspas, auto shops — any business where "what does it cost?" is a pre-purchase blocker.

**Section structure:**
- Eyebrow ("Services & Pricing", "The Menu", "Our Services")
- H2 (display, 32-40px)
- Optional lede: "Transparent pricing. No hidden fees."
- Category tabs if services span multiple types (Hair / Color / Treatments — or — Oil Change / Brakes / Diagnostics): Alpine `x-data` tab switcher with underline indicator
- Price list: one line per service, 2-column layout on desktop

**Row anatomy (flex row):**
- Left: service name (H4, 18px, body font, bold)
- Middle: dotted leader line (subtle border-bottom) filling remaining space
- Right: price (tabular-nums, accent color, 18px)
- Below name, optional 1-line description (14px, muted, 10-18 words)
- Duration pill if scraped: "45 min", "1 hr" in a small rounded tag

**Motion:**
- On scroll into viewport: rows fade in one-by-one, 50ms stagger (cap at 12)
- Row hover: name goes accent color, surface tint fills behind the whole row
- Tab switch: cross-fade the list container, 180ms
- Prices on hover: subtle scale 1.04 and weight shift to bold (micro-delight without being gimmicky)

**Rules:**
- Only prices the scrape explicitly returned. Never invent "$45 cut" if the scrape says nothing.
- If no prices found, render as a service list without prices and add a line: "Call {phone} for current pricing."
- Use "Starting at $X" wording if the scraped site uses it. Never drop the "starting at" qualifier — it's legally protective.
- Format: `$65`, not `$65.00`. Keep prices clean.
- No strike-through "was $80 now $60" unless the scrape explicitly shows a current promo.
