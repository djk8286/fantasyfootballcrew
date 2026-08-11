import type { ReactNode } from "react";

export default function LegalPageLayout({
  title,
  lastUpdated,
  children,
}: {
  title: string;
  lastUpdated: string;
  children: ReactNode;
}) {
  return (
    <div>
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
          <h1 className="text-3xl md:text-4xl font-bold text-white mb-2">{title}</h1>
          <p className="text-surface-500 text-sm">Last updated {lastUpdated}</p>
        </div>
      </section>

      <section className="py-16 bg-surface-850">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 space-y-10">{children}</div>
      </section>
    </div>
  );
}

export function LegalSection({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-3">{heading}</h2>
      <div className="text-surface-300 text-sm leading-relaxed space-y-3">{children}</div>
    </div>
  );
}
