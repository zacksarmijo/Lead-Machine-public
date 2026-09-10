# Class Schedule Grid

Weekly class calendar for gyms, yoga studios, fitness boutiques, dance studios.

**Section structure:**
- Eyebrow ("This Week", "Class Schedule")
- H2 (display, 32-40px)
- Filter pill row above grid: All · Strength · Yoga · Cardio · HIIT · Mobility (only pills matching scraped class types; Alpine `x-data` filter)
- Grid: 7 columns desktop (Mon-Sun), stacked accordion mobile (each day collapses/expands)

**Day column anatomy:**
- Day header (uppercase, tracking-wide, 13px)
- Date number (display font, large, 32px) if this is "this week"
- Class cards stacked below day:
  - Time (small, tabular-nums, body font)
  - Class name (H4, 16px)
  - Instructor first name
  - Difficulty dot row (1-3 filled dots by intensity)
  - Small capacity bar if scraped has it ("8/12 spots")

**Motion:**
- On-load: columns slide up sequentially left → right, 80ms stagger, 400ms total
- Filter pill click: classes not matching fade opacity 0.2 and shrink slightly, matching classes pulse once
- Class card hover: accent-color left border grows from 0 → 4px, card shifts 2px right
- Current day column has an always-on subtle highlighted background (surface tint)

**Rules:**
- Only list classes the scrape returns. Do NOT invent a Monday 6am "Power Flow" just to fill the grid.
- If fewer than 6 classes scraped, fall back to a simple 2-column list instead of the 7-day grid.
- Empty days show a single muted line: "No classes scheduled." Never placeholder "TBD" or "Coming soon".
- Accessibility: the grid must be keyboard-navigable; each class card is a focusable link to a booking URL or `tel:`.
- On mobile accordion: default expanded day is the current day.
