import Link from "next/link";
import LegalPageLayout, { LegalSection } from "@/components/LegalPageLayout";

export default function PrivacyPolicyPage() {
  return (
    <LegalPageLayout title="Privacy Policy" lastUpdated="August 11, 2026">
      <LegalSection heading="The short version">
        <p>
          FantasyFootballCrew is a small, independently-run fantasy football platform. We collect
          the account and league data needed to run the service, we don&apos;t sell your data, and
          we don&apos;t run any advertising or analytics trackers. This page explains exactly what
          we collect and what happens to it.
        </p>
      </LegalSection>

      <LegalSection heading="Information we collect">
        <p>
          <strong className="text-white">Account information.</strong> Your email address,
          username, and password. Passwords are never stored in plain text — only a salted hash of
          your password is kept, which can&apos;t be reversed back into the original password.
        </p>
        <p>
          <strong className="text-white">League data you create.</strong> Leagues, teams, rosters,
          trades, waiver claims, draft picks, scoring settings, and anything else you enter while
          using the platform.
        </p>
        <p>
          <strong className="text-white">What we don&apos;t collect.</strong> We don&apos;t process
          payments, so we never see or store any billing or card information — there isn&apos;t
          any, since the platform is free to use.
        </p>
      </LegalSection>

      <LegalSection heading="How we use it">
        <p>
          Solely to run the service: authenticating you, storing your leagues and rosters,
          calculating scores and standings, and (if you use it) sending you a password reset link.
        </p>
      </LegalSection>

      <LegalSection heading="Who we share it with">
        <p>
          <strong className="text-white">Sleeper (api.sleeper.app).</strong> We pull public NFL
          player and stat data from Sleeper&apos;s API to power rosters, scoring, and player pages.
          This is one-way — we read public sports data from Sleeper, we don&apos;t send Sleeper any
          information about you.
        </p>
        <p>
          <strong className="text-white">AI providers (OpenAI or Anthropic).</strong> If you use
          the AI Analysis features, the relevant roster/matchup data (player names and positions,
          not your account info) — or, for the free-form bet-analysis tool, whatever text you type
          in — is sent to whichever AI provider is configured, to generate the analysis. Avoid
          typing personal information into that free-form box.
        </p>
        <p>
          <strong className="text-white">Hosting infrastructure.</strong> The app runs on Railway
          (backend and database) and Vercel (frontend). Like virtually all web hosts, they log
          standard request metadata (e.g. IP address, timestamps) as part of normal operation.
        </p>
        <p>We don&apos;t sell your data to anyone, for any reason.</p>
      </LegalSection>

      <LegalSection heading="Cookies and local storage">
        <p>
          We don&apos;t use tracking or advertising cookies, and we don&apos;t run any analytics.
          When you log in, your session token is stored in your browser&apos;s local storage (not a
          cookie) so you stay signed in.
        </p>
      </LegalSection>

      <LegalSection heading="Data retention and deletion">
        <p>
          We keep your account and league data for as long as your account exists. There&apos;s no
          self-service delete button yet — to request that your account and data be deleted, email
          us at{" "}
          <a href="mailto:djk8286@gmail.com" className="text-gold-400 hover:text-gold-300">
            djk8286@gmail.com
          </a>{" "}
          and we&apos;ll take care of it.
        </p>
      </LegalSection>

      <LegalSection heading="Children's privacy">
        <p>
          FantasyFootballCrew isn&apos;t directed at children under 13, and we don&apos;t knowingly
          collect information from anyone under 13.
        </p>
      </LegalSection>

      <LegalSection heading="Security">
        <p>
          We take reasonable steps to protect your information (password hashing, rate limiting on
          login attempts, and similar precautions), but no online service can guarantee perfect
          security. Use a password you don&apos;t reuse elsewhere.
        </p>
      </LegalSection>

      <LegalSection heading="Changes to this policy">
        <p>
          If this policy changes in a meaningful way, we&apos;ll update the date at the top of this
          page.
        </p>
      </LegalSection>

      <LegalSection heading="Contact">
        <p>
          Questions about this policy or your data:{" "}
          <a href="mailto:djk8286@gmail.com" className="text-gold-400 hover:text-gold-300">
            djk8286@gmail.com
          </a>
        </p>
        <p>
          <Link href="/terms" className="text-gold-400 hover:text-gold-300">
            Read the Terms of Service →
          </Link>
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
