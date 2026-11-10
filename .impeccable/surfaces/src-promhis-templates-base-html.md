---
version: 1
slug: "src-promhis-templates-base-html"
primary_target: "src/promhis/templates/base.html"
related_targets: []
---

## Direction contract

THESIS: One flat operational console shared by every page — the navbar and page chrome are the single constant, everything below it reads as plain bordered tables and panels. Refuses a bespoke "product" shell in favor of looking exactly like the real Alertmanager/Prometheus UI operators already trust, so there is zero onboarding cost.

OWN-WORLD: A dark navbar (`#1f2229`, unchanged by the theme toggle) carries the single Prometheus flame-orange accent (`#e6522c`) — active-tab underline, primary buttons, chart bars — and nothing else uses that color. Body copy is the system sans stack, no custom webfont. Components are flat, 1px-bordered Bootstrap-era chrome: white/dark panels with an alt-background header strip, `.register` tables with a 2px-bottom-border header row and row-hover tint, solid-rectangle status/severity labels (red/green/amber/cyan/gray, always paired with text, never color alone). Flat at rest everywhere except the one accepted exception, a soft hover lift on node cards. A sun/moon inline-SVG theme toggle in the navbar persists to `localStorage`, defaulting to OS preference.

STORY: The visitor opens any page and the navbar tells them where they are (orange underline, white active tab); the content area reads as a dense, scannable operational layout — gauge tiles, register tables, chart panels — matching the real Alertmanager UI closely enough that prior familiarity with it transfers directly.

FIRST VIEWPORT: A 50px sticky dark navbar — brand mark (flame glyph + wordmark) left, the full tab row (Overview/Alerts/Nodes/Stats/Audit Log/API Tokens/Integrations/Routing) beside it, wrapping to a horizontally-scrolling row below 980px, theme toggle and sign-out right. Below it, a max-1280px content column: on Overview, a `.gauge-row` of four stat tiles (Total/Firing/Resolved/Nodes), two `.grid-2` chart-panel rows (event volume + severity, then top-noisy alerts + MTTR), and a `.register` table of recent alerts. Every other page extends this same shell and column width.

FORM: This surface brief documents an already-shipped, already-decided redesign rather than a new rolled direction — no concept-seed round applies. The dashboard's visual world was explicitly replaced per direct user instruction, trading an earlier bespoke direction for the real Alertmanager/Prometheus ecosystem's own visual language; `DESIGN.md` is the durable record of that decision and is authoritative over this (now corrected) surface-scoped brief. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
