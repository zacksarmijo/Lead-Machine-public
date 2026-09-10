# Menu Showcase

Primary menu browsing block for restaurants, cafes, bars. The visual centerpiece after the hero — shows the food is the brand.

**Section structure:**
- Eyebrow + H2 ("The Menu", "Our Kitchen", "What We Serve")
- Category tabs across the top: Brunch / Lunch / Dinner / Drinks / Dessert (only tabs that match scraped services)
- Tab UI: underlined active tab + horizontal reveal animation (200ms ease) on switch, powered by Alpine `x-data` / `x-show`
- Grid: 2 columns desktop, 1 mobile. Each item is a horizontal card.

**Menu item card:**
- Left 35%: square food photo if available, else warm-tinted gradient tile with SVG plate icon
- Right 65%:
  - Item name (H3, display font, 20-24px)
  - One-line description (14-16px, muted, 12-20 words max)
  - Price on its own line, right-aligned, tabular-nums, accent color
  - Tiny dietary icons (V, GF, 🌶) as inline SVG only when implied by scraped data

**Motion:**
- Scroll-reveal: each card fades+slides up as it enters viewport (IntersectionObserver, `opacity 0 → 1`, `translateY(12px) → 0`, 400ms stagger by index).
- Tab change: cross-fade the grid, 200ms.
- Hover on card: lift 4px, soft shadow grows, border goes to accent.

**Rules:**
- Only list menu items the scrape actually found. No inventing dishes.
- If fewer than 6 items: use 1 column full width, cards twice as tall with bigger photo.
- No 3D flip on cards. No carousel.
- Include a sticky "View Full Menu" or "Order Online" button at bottom of section if scraped site has a menu URL.
