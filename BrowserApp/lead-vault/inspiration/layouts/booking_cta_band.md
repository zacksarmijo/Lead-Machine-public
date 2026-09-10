# Booking CTA Band

Appointment-driving conversion band for dentists, chiropractors, medspas, salons, barbers, any service with online booking.

**Section structure:**
- Full-width band, 40-50vh on desktop, 35vh mobile
- Background: accent-tinted gradient (primary → accent, 135deg) OR calm brand photo with light gradient scrim (rgba(255,255,255,0.55))
- Centered content column, max-width 720px:
  - Eyebrow ("Book Online", "Schedule", "Appointments")
  - H2 (display, 32-44px) with a calm direct hook ("Easy online booking.", "Your chair is waiting.", "Schedule your first visit.")
  - Subhead (16-18px, 18-28 words) addressing first-time anxiety or insurance clarity
  - Primary CTA: filled button "Book an Appointment" linked to scraped booking URL (or `tel:` fallback)
  - Secondary row: "Accepting new patients · Most insurance accepted · Evening hours" as a pill row (only pills matching scraped facts)

**Motion:**
- On scroll into viewport: content block fades+slides up 16px, 400ms ease-out
- CTA button: resting state has a very subtle pulsing shadow (box-shadow scale, 2.5s loop) to draw the eye without feeling aggressive
- On hover: button lifts 2px, shadow tightens, background shifts half a step deeper

**Rules:**
- If no scraped booking URL, fall back to `tel:` link but rename button to "Call to Book". Never use `#` placeholder links.
- Insurance pills must match scraped text. Never invent "Blue Cross, Aetna, Delta Dental" out of thin air.
- Keep the band calm — this is medical-adjacent. No bright discount stickers, no countdown timers.
- Respect prefers-reduced-motion: disable the pulse animation.
