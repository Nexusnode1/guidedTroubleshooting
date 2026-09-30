/** Minimal hand-authored inline icons. No icon library dependency is installed, so these are
 * plain SVG paths sized to inherit color via `currentColor` and to sit on a 24x24 grid. */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

/** Shield with a check mark: "verified guidance" mark used in the product header. */
export function ShieldCheckIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

/** Magnifying glass with a small mark inside: used for the no-match state. */
export function SearchIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.3-4.3" />
      <path d="M10.5 8v5M8 10.5h5" />
    </svg>
  );
}

/** Diagonal external-link arrow: marks an actionable deeplink. */
export function ExternalLinkIcon(props: IconProps) {
  return (
    <svg {...base} width={14} height={14} {...props}>
      <path d="M7 17L17 7" />
      <path d="M9 7h8v8" />
    </svg>
  );
}

/** Check mark: marks a manual, non-clickable step. */
export function CheckIcon(props: IconProps) {
  return (
    <svg {...base} width={14} height={14} {...props}>
      <path d="M4 12l5 5L20 6" />
    </svg>
  );
}

/** Triangle with an exclamation mark: marks a disruptive/critical step. */
export function WarningIcon(props: IconProps) {
  return (
    <svg {...base} width={14} height={14} {...props}>
      <path d="M12 4l9 16H3L12 4z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

/** Wrench: a plain "troubleshooting" glyph used inside the query composer. */
export function WrenchIcon(props: IconProps) {
  return (
    <svg {...base} width={18} height={18} {...props}>
      <path d="M14.7 6.3a4 4 0 00-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 005.4-5.4l-2.3 2.3-2-2 2.3-2.3z" />
    </svg>
  );
}

/** Small chevron, rotated by the caller to indicate open/closed state. */
export function ChevronIcon(props: IconProps) {
  return (
    <svg {...base} width={14} height={14} {...props}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

/** Abstract device-diagnostics motif for the hero: a phone outline with a small verified
 * badge and a faint pulse/waveform line, built from plain shapes (no external imagery). */
export function DiagnosticGlyph(props: IconProps) {
  return (
    <svg {...base} width={64} height={64} strokeWidth={1.4} viewBox="0 0 64 64" {...props}>
      <rect x="20" y="8" width="24" height="48" rx="6" />
      <path d="M26 16h12" />
      <path d="M22 38l6-10 4 6 4-8 6 10" />
      <circle cx="46" cy="14" r="7" fill="var(--bg, #0b0f1a)" />
      <path d="M43 14l2 2 4-4" />
    </svg>
  );
}
