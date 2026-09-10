# Agent Card Grid

Meet-the-team block optimized for realtors, mortgage brokers, insurance agents — anywhere trust is transferred to a person, not a brand.

**Section structure:**
- Eyebrow ("Your Agent", "Meet the Team", "Who You'll Work With")
- H2 (display, 32-40px)
- Single agent: one large featured card, center-stage (max-width 760px)
- 2-4 agents: grid of equal cards, 2-col desktop, 1-col mobile
- Larger teams: 3-col grid with pagination (Alpine `x-data` toggling visible page), never list more than 6 on one view

**Agent card anatomy:**
- Portrait: 4:5 aspect, real scraped photo if present — else initials monogram on gradient surface
- Rounded corners (16px)
- Overlay bottom gradient with name + title on the image for featured card; separate text block below image for grid cards
- Name (H3, display font, 22-26px)
- Title/role (14px, muted, tracking-wide uppercase)
- Short bio: 2 sentences, 35-50 words. Must use only scraped bio text.
- Designations row: small pills for SRES, CAPS, CRS, GRI — only if scraped text mentions them
- Contact row: `tel:` phone icon link + `mailto:` envelope icon link + LinkedIn SVG if scraped
- Primary CTA: "Start a Conversation" → `mailto:` or contact form anchor

**Motion:**
- On scroll into viewport: cards fade+slide up with 120ms stagger
- Hover on card: card lifts 6px, portrait image scales 1.03 inside fixed frame (overflow hidden), accent border appears
- Portrait has a subtle parallax: on scroll past the card, image shifts 4% down inside its frame (scroll-linked, via passive listener)

**Rules:**
- Never use stock agent headshots. If no real photo, use a tasteful monogram — not an avatar-maker cartoon.
- Bio copy comes from scraped content. If bio is empty, write one line: "Licensed real estate professional serving {city_area}." — nothing invented.
- Do NOT include personal cell numbers unless the scrape confirms they are public-facing.
- No starburst "Top Agent 2024!" graphics unless the scrape has a specific, verifiable award.
