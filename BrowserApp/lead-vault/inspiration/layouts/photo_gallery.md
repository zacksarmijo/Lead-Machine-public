# Photo Gallery

Masonry-style visual showcase. For restaurants, salons, medspas, landscapers — any business where photography sells.

**Section structure:**
- Eyebrow + short H2 ("The Space", "Our Work", "Gallery", "Recent Projects")
- Optional 1-line lede (max 15 words)
- Masonry grid: 3 columns desktop (varying row heights), 2 tablet, 1 mobile
- Use CSS `grid-template-rows: masonry` with `@supports` fallback to `column-count: 3` for safety
- Gap: 12-16px

**Image tiles:**
- Mix portrait + landscape aspect ratios, never force-crop to squares
- Rounded corners (8px)
- Each tile wrapped in `<a>` that opens a lightweight Alpine lightbox (modal dialog with dim overlay + close button + left/right arrows)
- Alt text: meaningful description if scraped data has context, else generic like "Interior of {business_name}"

**Motion:**
- On-load: staggered fade-in, 80ms delay per tile, capped at 12 tiles
- Hover: zoom the image 4% inside a fixed tile (overflow hidden), overlay a dark-to-transparent gradient from bottom 40% with a tiny caption
- Lightbox open: scale from 0.95 → 1.0, fade bg from 0 → 0.7 opacity, 250ms

**Rules:**
- Minimum 6 tiles for masonry to read right. If scraped photos < 6, fall back to 2-column grid of larger tiles.
- No autoplay slideshow. User-initiated only.
- Respect prefers-reduced-motion: disable zoom, keep fade only.
- If `photos_source == pollinations_fallback`, reduce to 3 tiles max and use neutral alt text ("Atmospheric imagery for {business_name}").
