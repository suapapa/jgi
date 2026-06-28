---
name: JGI Design System
description: Analytical, sharp, and terminal-adjacent design language for JooGall Sentiment Index
colors:
  primary: "#3dd68c"
  neutral-bg: "#0c0f14"
  neutral-surface: "#141a24"
  neutral-text: "#e8ecf4"
  neutral-muted: "#8b95a8"
  bear: "#f07178"
  bull: "#3dd68c"
  mixed: "#e6c07b"
typography:
  display:
    fontFamily: "Newsreader, Georgia, serif"
    fontWeight: 600
  body:
    fontFamily: "IBM Plex Sans KR, system-ui, sans-serif"
    fontWeight: 400
rounded:
  sm: "8px"
  md: "12px"
components:
  card:
    backgroundColor: "{colors.neutral-surface}"
    rounded: "{rounded.md}"
    textColor: "{colors.neutral-text}"
---

# Design System: JGI (JooGall Sentiment Index)

## 1. Overview

**Creative North Star: "The Sentiment Terminal"**

JGI is a high-density, dark-mode analytical UI built for retail investors who need to scan market sentiment trends in seconds. The aesthetic is clean, professional, and terminal-adjacent, avoiding typical consumer SaaS clutter. We rely on visual restraint, sharp borders, and purposeful typography to establish hierarchy.

**Key Characteristics:**
- **Terminal Dark Palette**: Deep charcoal and black foundations optimize readability under low light conditions.
- **Strict Color Semantics**: Red, green, and yellow are strictly reserved for market sentiment indication (Bearish, Bullish, Mixed).
- **Subtle Organic Texture**: Tiny parallax "ants" (scroll dots) add a micro-tactile layer to prevent the UI from feeling flat or sterile.

## 2. Colors

Colors in JGI are functional, not decorative. Backgrounds are deep and ink-like, while sentiment indicators use high-contrast midtones.

### Primary
- **Deep Mint Green** (#3dd68c): The primary accent color, used for high-emphasis highlights, primary actions, and bullish indicators.

### Neutral
- **Deep Ink Black** (#0c0f14): The primary page background.
- **Charcoal Surface** (#141a24): The background for containers, cards, and interactive blocks.
- **Off-White Text** (#e8ecf4): The main content text color, ensuring high legibility (contrast ratio ≥ 4.5:1).
- **Cool Slate Muted** (#8b95a8): Used for secondary metadata, timestamps, and low-contrast labels.
- **Border Stroke** (rgba(255, 255, 255, 0.08)): Subtle borders dividing sections and wrapping cards.

### Named Rules
**The Color-Only-For-Data Rule.** Colored text or icons (Green, Red, Yellow) must ONLY be used for conveying market sentiment data (bull, bear, mixed) or key interactive active states. Never use these accent colors for general headers or decorative accents.

## 3. Typography

**Display Font:** Newsreader (Georgia, serif)
**Body Font:** IBM Plex Sans KR (system-ui, sans-serif)

**Character:** We pair a classic editorial serif (`Newsreader`) for headlines with a clean, high-legibility geometric sans-serif (`IBM Plex Sans KR`) for body copy and metadata. This builds a professional, newsletter-style reading atmosphere.

### Hierarchy
- **Display** (Semi-Bold (600), 2rem, 1.25): Used for main page titles and primary index headings.
- **Headline** (Medium (500), 1.2rem, 1.35): Used inside report cards and secondary section titles.
- **Body** (Regular (400), 15px, 1.65): The standard reading size for reports and summaries. Line lengths are constrained below 75ch.
- **Label** (Regular (400), 0.8rem, normal): Timestamps, metadata, and footer copyright text.

## 4. Elevation

The JGI interface is designed to be flat and structural. Depth is conveyed purely through tonal layering (dark gray surfaces on black backgrounds) and thin borders, not drop shadows.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest. Drop shadows are strictly forbidden, with the single exception of the Fear & Greed gauge pointer needle to guarantee it floats cleanly over the colored dial sectors.

## 5. Components

### Cards / Containers
- **Corner Style:** Medium Rounded (12px)
- **Background:** Charcoal Surface (`#141a24`)
- **Border:** Thin Border Stroke (`1px solid rgba(255, 255, 255, 0.08)`)
- **Internal Padding:** `1.25rem 1.5rem` (Report cards), `2rem 2.25rem` (Report body)

### Fear & Greed Gauge
- **Dial Segments:** Curved arc with 5 color sections representing market sentiment states: Extreme Fear (`#c41e1e`), Fear (`#f07178`), Neutral (`#e6c07b`), Greed (`#3dd68c`), Extreme Greed (`#1a7d5a`).
- **Pointer:** Off-White needle (`#e8ecf4`) with a soft blur dropshadow overlay for clarity.

### Buttons / Report Links
- **States:** Transition on hover with `border-color 0.2s` and a subtle `translateX(4px)` slide to indicate interactivity.

## 6. Do's and Don'ts

### Do:
- **Do** maintain a strict contrast ratio (≥ 4.5:1) for all body text on the dark container background.
- **Do** restrict colored indicators (Red/Green/Yellow) to represent actual bearish, bullish, and mixed sentiments.
- **Do** ensure all report layouts scale down cleanly to a single-column layout on mobile viewports.

### Don't:
- **Don't** use neon-colored gradients, purple highlights, or generic SaaS aesthetics.
- **Don't** add side-stripe borders (e.g. `border-left: 4px solid var(--accent)`) on cards.
- **Don't** apply box-shadows to cards or standard buttons.
- **Don't** exceed 75ch in body copy width to maintain optimal text scannability.
