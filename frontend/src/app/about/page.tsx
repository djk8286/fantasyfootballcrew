import Link from "next/link";
import LegalPageLayout, { LegalSection } from "@/components/LegalPageLayout";

export default function AboutPage() {
  return (
    <LegalPageLayout title="About FantasyFootballCrew" lastUpdated="August 11, 2026">
      <LegalSection heading="What this is">
        <p>
          FantasyFootballCrew is a fantasy football platform built around the leagues the big
          platforms don&apos;t really support well: fully custom scoring, 2-Man Teams, and
          Conference Battles, alongside the usual drafts, trades, waivers, and standings — plus
          AI-powered lineup and trade analysis.
        </p>
      </LegalSection>

      <LegalSection heading="Who's building it">
        <p>
          It&apos;s an independent, solo-built project, currently in beta — new features ship
          regularly, and some rough edges are still getting smoothed out along the way.
        </p>
      </LegalSection>

      <LegalSection heading="Get in touch">
        <p>
          Found a bug, or have an idea for a feature? See the{" "}
          <Link href="/contact" className="text-gold-400 hover:text-gold-300">
            Contact page
          </Link>
          .
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
