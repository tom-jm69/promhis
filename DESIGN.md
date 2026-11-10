---
name: Promhis — Alertmanager-style console
description: Styled after the Prometheus / Alertmanager web UI — dark navbar, flame-orange accent, flat Bootstrap-era chrome.
colors:
  bg: "#ffffff"
  bg-alt: "#f7f7f9"
  bg-navbar: "#1f2229"
  bg-navbar-active: "#32363f"
  border: "#dddddd"
  border-light: "#e9e9e9"
  text: "#333333"
  text-muted: "#777777"
  text-navbar: "#d7d9dd"
  orange: "#e6522c"
  orange-dark: "#c7431f"
  blue: "#337ab7"
  blue-dark: "#286090"
  red: "#d9534f"
  amber: "#f0ad4e"
  cyan: "#5bc0de"
  green: "#5cb85c"
  gray-badge: "#777777"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  mono:
    fontFamily: "'Courier New', Courier, monospace"
rounded:
  sm: "3px"
  md: "4px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "15px"
  lg: "22px"
components:
  status-firing:
    backgroundColor: "{colors.red}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "2px 7px"
  status-resolved:
    backgroundColor: "{colors.green}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "2px 7px"
  navbar-tab-active:
    backgroundColor: "{colors.bg-navbar-active}"
    textColor: "#ffffff"
  button-primary:
    backgroundColor: "{colors.orange}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "9px"
---

# Design System: Promhis — Alertmanager-style console

## Overview

**Creative North Star: "The Alertmanager Console"**

Promhis's dashboard deliberately mirrors the real Prometheus/Alertmanager web UI: a dark top navbar carrying the Prometheus flame-orange accent, a white content area, and flat Bootstrap-era components (bordered panels, striped tables, solid-color status/severity labels). This replaces an earlier bespoke "brass fire-alarm annunciator" direction — that look was dropped in favor of the actual ecosystem's own visual language, so this is a full redesign, not a refinement: the structural content (tables, cards, filters, pages) carried over, the entire surface skin did not.

The goal is instant familiarity for anyone who has ever looked at Prometheus or Alertmanager: no custom display typeface, no bespoke signature animation, no decorative chrome — utilitarian and dense, exactly like the tools it sits next to. Within that core, modern polish is welcome: short (0.1–0.2s) transitions on every interactive element, a fade-in on htmx-swapped content, and a dark/light theme toggle (the real Alertmanager UI has one too, so this reinforces authenticity rather than fighting it). Motion is restrained and functional — it never replaces the flat, static identity of the surface itself.

**Key Characteristics:**
- Dark navbar (`#1f2229`, unchanged across themes) with Prometheus flame-orange (`#e6522c`) as the only strong accent color; everything else is neutral gray/white (or dark-mode equivalent) or a semantic status color.
- Status and severity are shown as solid-color Bootstrap-style labels (red=firing/critical, green=resolved, amber=warning, cyan=info, gray=none) — flat rectangles, no dots, no state-change animation.
- System font stack only (`-apple-system, Helvetica Neue, Arial, sans-serif`) — no self-hosted webfonts.
- Flat panels: 1px border, alt-background header bar, no shadows, no gradients, no glow — except a deliberately subtle hover lift on node cards (`0 2px 8px rgba(0,0,0,0.08)` + 1px translateY), the one accepted elevation exception.
- Dark/light theme toggle in the navbar, persisted to `localStorage`, defaulting to OS preference (`prefers-color-scheme`) when unset.

## Colors

A deliberately narrow palette: neutral grays and white carry the whole UI, orange is the single brand accent, and four Bootstrap-standard semantic colors carry status/severity meaning.

### Primary
- **Prometheus Orange** (`#e6522c`): the brand flame mark, active nav-tab underline, primary buttons (login submit), chart's volume bars. Nothing else uses this color.

### Secondary
- **Firing Red** (`#d9534f`) / **Resolved Green** (`#5cb85c`): the alert status label. Reserved exclusively for this axis.

### Tertiary
- **Warning Amber** (`#f0ad4e`), **Info Cyan** (`#5bc0de`), **Gray Badge** (`#777777`): severity labels for warning/info/none.

### Neutral
- **White** (`#ffffff`, dark theme: `#1b1d21`): page and panel background — swaps per theme via the `--bg` token.
- **Alt Gray** (`#f7f7f9`, dark theme: `#24272e`): table headers, panel headers, filter bars.
- **Border** (`#dddddd`, dark: `#3a3d45`) / **Border Light** (`#e9e9e9`, dark: `#2e3138`): all dividers and panel borders — always 1px, never thicker, never colored.
- **Text** (`#333333`, dark: `#e4e6eb`) / **Text Muted** (`#777777`, dark: `#9aa0ab`): body text and secondary/meta text.
- **Navbar Dark** (`#1f2229`) / **Navbar Active** (`#32363f`): the one dark surface in the system — unchanged by the theme toggle, in both light and dark mode.

Semantic colors (orange, red, green, amber, cyan, gray-badge) and the navbar colors are identical in both themes — only the neutral grays/white (`--bg`, `--bg-alt`, `--border`, `--border-light`, `--text`, `--text-muted`, and link color `--blue`/`--blue-dark`) swap per theme. See `:root[data-theme="dark"]` in `style.css` for the exact dark values.

### Named Rules
**The One Accent Rule.** Orange appears in exactly three places (flame mark, active-tab underline, primary buttons/chart bars) and nowhere else — its rarity is what makes it read as "brand" rather than decoration.

## Typography

**Body Font:** system sans stack (`-apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, Arial, sans-serif`) — no custom webfont, matching the real Prometheus/Alertmanager UI's plain Bootstrap typography.
**Label/Mono Font:** `"Courier New", Courier, monospace` — used only for label pills (`key=value`) and timestamps in the ledger, echoing how Alertmanager renders raw labels.

**Character:** Plain and utilitarian by design — the point is to look like ops tooling, not a crafted product.

### Hierarchy
- **Page title** (600, 22px): one per page, in `.page-title`.
- **Panel heading** (600, 14px): `.panel-head h2`.
- **Body** (400, 14px): default text size everywhere else.
- **Label/meta** (400, 11–13px, often `--text-muted`): table headers, gauge labels, timestamps.

### Named Rules
**The No-Webfont Rule.** Typography is the platform's own sans stack. No `@font-face`, no Google Fonts import — this keeps the page loading exactly like the tools it imitates.

## Layout

Dark navbar (50px, sticky) at top — brand mark left, Overview/Alerts/Nodes tabs beside it, sign-out right. Content column max-width 1280px, 22–24px padding. `.gauge-row` (4 equal stat boxes), `.grid-2` (1.6fr/1fr chart panels), `.detail-grid` (1fr/300px detail + sidebar). Below 980px the navbar wraps and the nav row scrolls horizontally; two-column grids collapse to one.

## Elevation & Depth

Flat at rest. Panels, cards, and the navbar are separated purely by 1px borders and background-color contrast (panel on `--bg-alt` page, or vice versa for headers) — a deliberate match to Bootstrap 3/4-era chrome. The one exception is `.node-card:hover`, which lifts 1px with a soft neutral shadow (`0 2px 8px rgba(0,0,0,0.08)`) as a modern, restrained hover affordance on an otherwise flat clickable card — never a colored or zero-offset glow.

### Named Rules
**The Flat-at-Rest Rule.** Nothing carries a shadow by default. A shadow may only appear as a hover/interaction response (currently just the node-card lift), never as resting-state decoration.

## Shapes

Small uniform radius: 4px for panels/buttons/inputs, 3px for status/severity labels and node-chips. Borders are always 1px solid, in `--border` or `--border-light`. No card, row, or label carries a border thicker than 1px or in an accent color.

## Components

### Buttons (`.btn`)
- **Shape:** 4px radius, 1px `#ccc` border.
- **Default (`.btn`):** white background, dark text; hover tints background to `--bg-alt`.
- **Primary action (login submit only):** solid orange background, white text, darkens on hover.

### Status Label (`.flap`)
- **Style:** a small solid-color rectangle, white text, uppercase — `state-firing` red, `state-resolved` green. No icon, no dot, no animation; state is legible from the label text alone as well as the color.

### Severity Label (`.sev-tag`)
- **Style:** same solid-rectangle treatment as the status label — critical=red, warning=amber (dark text for contrast), info=cyan, none=gray. Always paired with the severity word, never color-only.

### Navbar (`.rail` / `.tab`)
- **Style:** dark background, light-gray nav text; the active tab turns white and gets a 3px orange bottom border plus a slightly lighter active background. No rivets, no decorative hardware.

### Panel (`.panel`)
- **Style:** white body, 1px gray border, light-gray header strip with a bottom border. No shadow.

### Table (`.register`)
- **Style:** light-gray header row with a 2px bottom border, 1px row dividers, row hover tints to `--bg-alt`. No zebra striping, no colored row accents.

### Node Card (`.node-card`)
- **Style:** a flat bordered box, same visual weight as `.panel` — title, a status label, and a 3-stat row (firing/resolved/total).

### Label Pills (`.label-pill`)
- **Style:** monospace `key=value` tags with a light-gray background and 1px border — matches how Alertmanager itself renders alert labels.

### Theme Toggle (`.theme-toggle`)
- **Style:** a navbar icon button (sun drawn when light is active, moon when dark is active — both authored inline SVG, one stroke weight, no emoji), between the nav tabs and the sign-out button. Click toggles `data-theme` on `<html>` and persists the choice to `localStorage`; an inline head script applies the stored (or OS-preferred) theme before first paint to avoid a flash of the wrong theme.

## Do's and Don'ts

### Do:
- **Do** keep orange limited to the flame mark, active-tab underline, and primary buttons/chart accents, in both themes.
- **Do** pair every status/severity color with its text label — never color alone.
- **Do** keep elevation flat at rest; a shadow may only appear as a hover response, never as resting decoration.
- **Do** use the system font stack; don't load a custom webfont.
- **Do** use short (0.1–0.2s) transitions on hover/focus/htmx-swap — this is the sanctioned "modern" layer on top of the flat core.

### Don't:
- **Don't** bring back the bespoke signature animation (flap-drop/overshoot) from the earlier annunciator direction — status changes are instant, only the *transition into view* (fade-in) is animated.
- **Don't** add colored borders thicker than 1px to cards, rows, or labels.
- **Don't** use a display/brand typeface — body text and headings share the same system sans stack at different sizes/weights.
- **Don't** hardcode a neutral color (background/border/text) outside the `--bg`/`--bg-alt`/`--border`/`--text`/`--text-muted` tokens — anything hardcoded won't follow the theme toggle.
