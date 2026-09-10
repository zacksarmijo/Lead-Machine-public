# Reservation CTA Band

Full-width conversion band just before the footer. For restaurants and any appointment-driven business.

**Section structure:**
- Full-width, 50-60vh tall on desktop, 40vh mobile
- Background: layered — hero-tier food/atmosphere photo with dark gradient scrim (rgba(0,0,0,0.55) from bottom) OR rich accent-color gradient if no photo
- Centered content stack, max-width 640px:
  - Eyebrow in accent color ("Reservations")
  - H2 (display font, 36-48px, white or near-white on dark bg) with a hook line ("Come sit with us.", "A table is waiting.")
  - One-line subhead (18px, muted white, 15-25 words)
  - Two stacked CTAs on mobile, side-by-side desktop:
    - Primary: filled accent button "Reserve a Table" linking to reservations URL if scraped, else `tel:` link
    - Secondary: ghost button "View Menu" or "Order Online"
  - Small trust line below: "Walk-ins welcome · Hours: {scraped_hours}"

**Motion:**
- On scroll into view: background image applies subtle parallax (translate 0.15x scroll) via `transform: translateY(calc(var(--scroll-y) * -0.15))` with a passive scroll listener
- Content block fades+slides up once, on first viewport entry
- CTA hover: filled button shifts 2px up with deeper shadow; ghost button fills with accent color (250ms)

**Rules:**
- Exactly ONE reservation/booking link. Do not repeat with different wording.
- If no reservation system in scraped data, primary CTA is `tel:` to the scraped phone — still labeled "Reserve" or "Call to Reserve".
- Disable parallax if `prefers-reduced-motion: reduce`.
- Never use a blurry background image. If only low-res photos exist, use the accent gradient instead.
