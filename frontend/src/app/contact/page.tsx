import LegalPageLayout, { LegalSection } from "@/components/LegalPageLayout";

export default function ContactPage() {
  return (
    <LegalPageLayout title="Contact" lastUpdated="August 11, 2026">
      <LegalSection heading="Get in touch">
        <p>
          Bug reports, feature requests, questions about your account or data — all of it goes to
          the same place:
        </p>
        <p>
          <a
            href="mailto:djk8286@gmail.com"
            className="text-gold-400 hover:text-gold-300 text-base font-medium"
          >
            djk8286@gmail.com
          </a>
        </p>
        <p>
          It&apos;s a solo-run project, so replies aren&apos;t instant, but every message gets
          read.
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
