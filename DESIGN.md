---
name: Nexus System Protocol
colors:
  surface: '#0f131d'
  surface-dim: '#0f131d'
  surface-bright: '#353944'
  surface-container-lowest: '#0a0e18'
  surface-container-low: '#171b26'
  surface-container: '#1b1f2a'
  surface-container-high: '#262a34'
  surface-container-highest: '#313540'
  on-surface: '#dfe2f0'
  on-surface-variant: '#cbc3d7'
  inverse-surface: '#dfe2f0'
  inverse-on-surface: '#2c303b'
  outline: '#958ea0'
  outline-variant: '#494454'
  surface-tint: '#d0bcff'
  primary: '#d0bcff'
  on-primary: '#3c0091'
  primary-container: '#a078ff'
  on-primary-container: '#340080'
  inverse-primary: '#6d3bd7'
  secondary: '#5de6ff'
  on-secondary: '#00363e'
  secondary-container: '#00cbe6'
  on-secondary-container: '#00515d'
  tertiary: '#4edea3'
  on-tertiary: '#003824'
  tertiary-container: '#00a572'
  on-tertiary-container: '#00311f'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e9ddff'
  primary-fixed-dim: '#d0bcff'
  on-primary-fixed: '#23005c'
  on-primary-fixed-variant: '#5516be'
  secondary-fixed: '#a2eeff'
  secondary-fixed-dim: '#2fd9f4'
  on-secondary-fixed: '#001f25'
  on-secondary-fixed-variant: '#004e5a'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#0f131d'
  on-background: '#dfe2f0'
  surface-variant: '#313540'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.03em
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 26px
    letterSpacing: -0.015em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: '0'
  code-base:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: -0.01em
  label-mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
  label-mono-xs:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: 12px
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-mobile: 0.75rem
  margin: 2rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1.25rem
  space-xl: 2rem
---

## Brand & Style

The design system embodies the ethos of a high-precision, mission-critical personal AI operating system. It treats computational intelligence, runtime agents, and protocol security with executive transparency and developer-grade control. Drawing heavily from technical minimalism, hyper-refined tool design, and modern operations interfaces (evocative of Linear and Vercel), it balances strict density with absolute legibility.

The interface prioritizes high-bandwidth technical context, low-latency observability, and crystalline signal-to-noise ratios. It delivers a tactile feeling of precision machinery: engineered borders, razor-sharp status states, and subtle glowing accents that signify dynamic autonomous reasoning without unnecessary ornament. The aesthetic avoids consumer softness in favor of deliberate, deterministic control.

## Colors

The palette operates strictly within an ultra-deep, cold-tone dark substrate designed for prolonged technical engagement and high optical contrast:

- **Canvas & Backgrounds:**
  - Base Canvas: `#0B0D12` (Deep Obsidian Void)
  - Surface Container: `#121620` (Structural Frame / Card Default)
  - Elevated Surface: `#181E2B` (Hover layers, context flyouts, active nodes)
  - Sub-surface / Inset: `#0E1118` (Terminal shells, inline log viewports)

- **Structural Borders:**
  - Subtle Border: `#252B38` (Component boundaries, interior card dividers)
  - Strong Border: `#374151` (Focus rings, modal frames, active card anchors)

- **Typographic Scale:**
  - Primary Text: `#F3F4F6` (High contrast, focal readability)
  - Secondary Text: `#9CA3AF` (Metadata, descriptive labels, secondary keys)
  - Muted Text: `#6B7280` (Timestamps, inactive icons, system timestamps)

- **Semantic & Engine State Accents:**
  - AI Intelligence & Neural Reasoning: `#8B5CF6` (Violet)
  - Runtime, MCP Protocols & Event Streams: `#22D3EE` (Cyan)
  - Trust State — ALLOW / Active Integrity: `#10B981` (Emerald)
  - Trust State — ASK / Gatekeeper Suspended: `#F59E0B` (Amber)
  - Trust State — DENY / Breach / Execution Error: `#EF4444` (Rose)

## Typography

The type ecosystem forms a hybrid symbiosis between high-density structural readability (Inter) and machine-level telemetry (JetBrains Mono).

- **Primary UI & Narrative (Inter):** Leveraged across view headers, dashboard summaries, navigation, and user-facing interactions. Tracking is tightly condensed in higher weights to preserve geometric tension.
- **Machine & Agent Layer (JetBrains Mono):** Reserved for autonomous reasoning traces, token counters, memory addresses, cryptographic checksums, security states, and tool invocations. All tabular logs, execution times, and status capsules enforce monospace alignment to stabilize data grids across continuous streaming updates.

## Layout & Spacing

The layout is architected around an extensible modular grid optimized for split-pane IDE-style workflows, operations timelines, and active monitor cards.

- **Grid Architecture:** 
  - Desktop: 12-column adaptive fluid grid with 1rem gutters and 2rem outer margins.
  - Tablet (768px - 1024px): 8-column grid with 1rem gutters and 1.5rem margins.
  - Mobile (< 768px): 4-column flow with 0.75rem gutters and 1rem margins; utility toolbars and multi-pane panes stack into single-column vertical flows or swipeable navigation panels.
- **Density Standard:** Spacing tokens reflect compact operator ergonomics. Interior component padding defaults to `space-sm` (8px) and `space-md` (12px), eliminating superfluous vertical padding to maximize visible information density per viewport.

## Elevation & Depth

Visual hierarchy does not use diffuse blurs or traditional drop shadows. Instead, it relies on tonal stacking paired with structural 1px low-contrast outlines:

- **Level 0 (Canvas Base):** Ground layer at `#0B0D12`. Serves as the bedrock for navigation sidebars, backdrop panels, and background workspaces.
- **Level 1 (Surface Containers):** Standard modules at `#121620` bounded by a 1px border of `#252B38`. Zero box-shadow; pure planar boundary.
- **Level 2 (Active & Elevated Cards):** Hovered panels, inspection windows, and popovers at `#181E2B` with a refined perimeter border of `#374151`.
- **Level 3 (Command Overlays & Modals):** Command palette (Cmd+K) and critical approval interrupts sit atop an overlay veil (`rgba(11, 13, 18, 0.85)` with `backdrop-filter: blur(8px)`). Surfaces feature an edge glow via a subtle inset highlight: `box-shadow: inset 0 1px 0 0 rgba(255, 255, 255, 0.06), 0 16px 32px -8px rgba(0, 0, 0, 0.6)`.

## Shapes

The design system adheres to a sharp, machined geometry (`roundedness: 1`). Outer container boundaries, action items, and data cards feature tight 4px (`0.25rem`) radii, escalating to 6px (`0.375rem`) only for modal windows and larger panel wrappers. 

Status tags and security pills maintain micro-radii or clipped technical geometries rather than organic pills, reinforcing an industrial, telemetry-driven platform language.

## Components

### Buttons & Interactive Controls
- **Primary / Neural Execution:** Background `#8B5CF6`, text `#F3F4F6`, border `transparent`. Hover transitions to `#7C3AED` with an ultra-subtle ambient glow (`0 0 12px rgba(139, 92, 246, 0.35)`). Active state scales to `0.99`.
- **Secondary / MCP Runtime:** Background `#121620`, text `#22D3EE`, border `1px solid #252B38`. Hover shifts background to `#181E2B` and border to `#22D3EE` (40% opacity).
- **Subtle / Ghost:** Background `transparent`, text `#9CA3AF`, border `1px solid transparent`. Hover yields `#121620` surface with `#F3F4F6` text.

### Trust Engine Status Badges
- **ALLOW (Approved):** Background `rgba(16, 185, 129, 0.1)`, text `#10B981`, border `1px solid rgba(16, 185, 129, 0.25)`. Monospace font (`label-mono-xs`), uppercase. Accompanied by a static 4px emerald indicator dot.
- **ASK (Waiting Approval):** Background `rgba(245, 158, 11, 0.1)`, text `#F59E0B`, border `1px solid rgba(245, 158, 11, 0.3)`. Features an asynchronous pulsing dot animation.
- **DENY (Rejected / Security Fault):** Background `rgba(239, 68, 68, 0.1)`, text `#EF4444`, border `1px solid rgba(239, 68, 68, 0.3)`.

### Cards & Telemetry Nodes
- Rendered on `#121620` with a 1px `#252B38` structural border and 4px border radius. Header slots feature separated border-bottom rails dividing contextual run metadata from log payload bodies.

### Form Inputs & Terminal Inputs
- Field backgrounds use inset dark `#0E1118`, framed by `#252B38`. Text sits at `#F3F4F6` with `#6B7280` placeholder color.
- Focus state switches the border to `#8B5CF6` (or `#22D3EE` in execution contexts) with no diffuse outer glow rings—maintaining a clean 1px precision outline.

### Run Tags & Micro Pills
- Built exclusively with `JetBrains Mono` at `label-mono-xs`. Padding: `2px 6px`. Designed for high-frequency runtime tags (`RUN_ID: 0x9AF4`, `LATENCY: 42ms`, `TOKENS: 1,420`).

### Checkboxes & Segmented Switches
- Form factor is square (2px radius). Default state `#121620` with `#252B38` border; checked state leverages `#8B5CF6` fill with `#0B0D12` checkmark icon.