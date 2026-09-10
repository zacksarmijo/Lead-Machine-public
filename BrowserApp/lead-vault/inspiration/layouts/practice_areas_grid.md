# Practice Areas Grid

Legal specialties as an authoritative grid. For law firms and legal-adjacent consultancies.

**Section structure:**
- Eyebrow ("Practice Areas", "What We Handle", "How We Help")
- H2 (display serif, 36-44px)
- Optional lede: 1 sentence, 15-25 words, positioning statement
- Grid: 3 columns desktop, 2 tablet, 1 mobile
- Cards have stronger divider lines and more negative space than a typical service grid — legal work reads more serious

**Card anatomy:**
- Top: thin accent-colored line (2px, 40px wide) as visual anchor
- Icon: small inline SVG, outlined style (scales of justice, shield, document) at 28px, accent color
- Practice area name (H3, serif display, 20-22px)
- One-sentence scope description (14-16px, muted, 25-40 words)
- Secondary line: "Recent outcome:" + one sentence if scraped has a case result mention
- Tertiary link: "Learn more about {area}" in accent color with trailing arrow SVG
- Card sits on surface with a thin border (not shadow-heavy — too flashy for legal)

**Motion:**
- On scroll into viewport: cards fade+slide up, 100ms stagger, 380ms ease-out
- Hover on card: accent top-line extends from 40px → 100%, card surface shifts half a tint darker, icon rotates 3deg and back (slow 300ms)
- No bouncy spring animations — keep it measured

**Rules:**
- Only list practice areas the scrape returns. Law firms get sued for false specialization claims; do not invent "family law" expertise.
- Avoid overpromising language — never "guaranteed results", "no recovery no fee" unless scrape states it verbatim.
- 4-6 practice areas is the sweet spot. Fewer → 2 column grid, larger cards. More → pagination, never cram 9 into one view.
- Icons must be abstract, not literal courtroom props. No gavel clip art.
