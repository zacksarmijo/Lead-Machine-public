# Insurance Accepted Band

Horizontal strip that removes the #1 objection for dental, chiro, medical: "do you take my insurance?"

**Section structure:**
- Full-width, short — 180-240px tall desktop, auto mobile
- Background: surface color, subtle border-top + border-bottom
- Centered content:
  - Small eyebrow ("Insurance & Payment")
  - H3 ("Most major insurance accepted" — or exact scraped wording if present, never invent)
  - Horizontal scroll-snap row of insurance carrier name pills (NOT logos — legal risk with trademarked logos)
  - Each pill: rounded-full, surface bg, 1px border, 14px text, 12px vertical + 20px horizontal padding
  - If 4+ scraped carriers: make it a scroll-snap horizontal strip on mobile
  - Small line below: "Don't see yours? Call us — we file all PPO claims." (only if scraped site mentions PPO handling)

**Motion:**
- On-load: pills fade in one at a time, 60ms stagger, capped at 8 pills
- On hover: pill border goes to accent, text darkens a half-step
- Horizontal scroll on mobile: subtle inertia, no snap-back animation

**Rules:**
- Only list insurance names found in the scrape. If none, render "We accept most major insurance plans. Call {phone} to verify yours." as a single-line message instead.
- Do NOT show insurance company logos — use text pills. Logos are trademarked and you don't have the rights.
- Never make up "in-network" status. If scraped data says "accepts X" not "in-network with X", keep the softer wording.
- Skip this section entirely if scraped text has zero insurance signal.
