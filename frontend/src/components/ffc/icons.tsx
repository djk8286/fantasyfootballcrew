// Spec v1.2 icon set: 24 grid, stroke 2, round caps.
import type { ReactNode, SVGProps } from "react";

const PATHS: Record<string, ReactNode> = {
  alert: (<><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><circle cx="12" cy="16.6" r="0.6" fill="currentColor" /></>),
  blade: (<><path d="M3 4h18" strokeWidth="2.4" /><path d="M6 7h12v4L6 16z" fill="currentColor" stroke="none" /><path d="M8 19h8" /></>),
  clock: (<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.2 2" /></>),
  equals: <path d="M5 9h14M5 15h14" />,
  medal: (<><circle cx="12" cy="14" r="6" /><path d="M8.5 3h7l-2 5.5h-3z" /><path d="M12 11.5v5" /></>),
  refresh: (<><path d="M20 12a8 8 0 1 1-2.4-5.7" /><path d="M20 4v5h-5" /></>),
  trophy: (<><path d="M7 4h10v5a5 5 0 0 1-10 0z" /><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3" /><path d="M12 14v3M8 20h8M9.5 17h5" /></>),
  up: <path d="M12 19V6M6 11l6-6 6 6" />,
  warn: (<><path d="M12 3.5 21.5 20h-19z" /><path d="M12 10v4.5" /><circle cx="12" cy="17.3" r="0.6" fill="currentColor" /></>),
};

export type FfcIconName = keyof typeof PATHS;

export function FfcIcon({ name, size = 12, ...rest }: { name: FfcIconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
