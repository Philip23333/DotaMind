# Design

## System

DotaMind is a product dashboard and callable agent console. Design serves repeated analysis work, so the interface should prioritize scanability, stable controls, and structured report output.

## Color

Color strategy: restrained product UI with an oxidized teal primary and copper accent. Backgrounds stay pure or near-pure neutral so the brand color carries identity instead of tinting the whole product.

```css
:root {
  --color-bg: oklch(1 0 0);
  --color-surface: oklch(0.982 0.004 170);
  --color-surface-raised: oklch(0.955 0.012 170);
  --color-ink: oklch(0.18 0.025 170);
  --color-muted: oklch(0.43 0.025 170);
  --color-primary: oklch(0.42 0.11 170);
  --color-primary-strong: oklch(0.34 0.105 170);
  --color-accent: oklch(0.58 0.14 35);
  --color-border: oklch(0.88 0.012 170);
  --color-success: oklch(0.48 0.12 150);
  --color-warning: oklch(0.64 0.16 70);
  --color-danger: oklch(0.55 0.16 25);
}
```

## Typography

Use one product sans stack: Inter when available, then system UI. Keep type sizes fixed in rem units. Headings should be compact and readable, not oversized hero type.

## Layout

Use an app shell with a sticky top bar, concise side navigation on desktop, and stacked sections on mobile. Dashboard sections use grids for metric groups and tables for rankings. Cards are limited to repeated report modules and should use an 8px radius.

## Components

- Query console: input, quick action buttons, request status.
- Metric card: label, value, trend, evidence status.
- Report table: hero/team rows with score, confidence, and key reasons.
- Service catalog: callable endpoint, price, input shape.
- Evidence list: source, signal, verdict, confidence.

## Motion

Use short 150-200ms transitions for hover, focus, and panel state changes. Respect `prefers-reduced-motion` by removing nonessential transitions.
