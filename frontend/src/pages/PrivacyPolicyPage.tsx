import { Sprout } from "lucide-react";
import { Link } from "react-router-dom";

// Update these two constants when the policy text changes or the contact moves.
const CONTACT_EMAIL = "maksim.v.kravchuk@gmail.com";
const LAST_UPDATED = "August 6, 2026";

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <section className="mt-8">
      <h2 className="text-subtitle font-semibold text-slate-900">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-slate-600">{children}</div>
    </section>
  );
}

export default function PrivacyPolicyPage(): JSX.Element {
  return (
    <main className="min-h-screen bg-surface-base px-4 py-10">
      <article className="mx-auto max-w-[720px] rounded-2xl border border-slate-200 bg-surface-raised p-8 shadow-raised">
        <header>
          <Link to="/" className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Sprout className="h-5 w-5 text-brand-primary" aria-hidden="true" />
            <span>Brain Buddy</span>
          </Link>
          <h1 className="mt-4 text-title font-semibold text-slate-900">Privacy policy</h1>
          <p className="mt-1 text-xs text-slate-500">Last updated: {LAST_UPDATED}</p>
        </header>

        <Section title="Who we are">
          <p>
            Brain Buddy is a personal thinking and task assistant operated by its maintainer
            (the &ldquo;controller&rdquo; in GDPR terms). For anything in this policy, contact{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="text-brand-primary underline">
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </Section>

        <Section title="What we collect">
          <p>
            <strong>Account data:</strong> your email address, an optional display name, and a
            salted Argon2id hash of your password (never the password itself).
          </p>
          <p>
            <strong>Content you create:</strong> thinking trees with their version snapshots and
            AI validation history, tasks, projects, tags, subtasks, and comments.
          </p>
          <p>
            <strong>Voice brain dumps:</strong> if you use voice capture, the audio you record,
            transcripts derived from it, and a record of the consent you gave for each recording.
          </p>
          <p>
            <strong>Technical data:</strong> a session cookie (below) and server logs keyed by
            per-request correlation IDs, used for security and troubleshooting.
          </p>
        </Section>

        <Section title="Why we process it">
          <p>
            <strong>To provide the service</strong> (contract, Art. 6(1)(b) GDPR): storing and
            showing your content, keeping you signed in.
          </p>
          <p>
            <strong>With your consent</strong> (Art. 6(1)(a)): sending voice recordings to an
            external speech-to-text provider. Each recording asks for this consent explicitly,
            and you can withdraw it or delete the raw audio at any time from the app.
          </p>
          <p>
            <strong>Legitimate interest</strong> (Art. 6(1)(f)): security logging and rate
            limiting to protect accounts.
          </p>
        </Section>

        <Section title="How long we keep it">
          <p>Sessions expire after 30 days (or immediately when you sign out).</p>
          <p>Raw voice audio is deleted within 24 hours of processing.</p>
          <p>Uncommitted voice working artifacts (draft transcripts) are deleted within 7 days.</p>
          <p>
            Account data and content are kept until you delete your account. Deletion has a
            14-day grace period during which signing back in cancels it; after that, everything
            is permanently erased.
          </p>
        </Section>

        <Section title="Who else processes your data">
          <p>
            <strong>OpenAI</strong> (and, where configured, <strong>Deepgram</strong>) — speech
            transcription, text reconciliation, and AI validation, only when you have consented.
            API data is not used to train their models and is retained by OpenAI for up to 30
            days for abuse monitoring. A data processing agreement is in place.
          </p>
          <p>
            <strong>Fly.io</strong> — hosting. Servers are operated by Fly.io, a US company;
            data transfers are covered by the EU–US Data Privacy Framework and Standard
            Contractual Clauses.
          </p>
          <p>We never sell your data or share it with anyone else.</p>
        </Section>

        <Section title="International transfers">
          <p>
            Your data may be processed in the United States by the providers above. Transfers
            rely on the EU–US Data Privacy Framework and/or Standard Contractual Clauses.
          </p>
        </Section>

        <Section title="Your rights">
          <p>
            <strong>Access &amp; portability:</strong> download everything your account owns from
            Account settings → &ldquo;Download my data&rdquo; (a ZIP of machine-readable JSON).
          </p>
          <p>
            <strong>Rectification:</strong> change your display name, email, and password in
            Account settings.
          </p>
          <p>
            <strong>Erasure:</strong> delete your account in Account settings. Voice-specific
            controls (withdraw consent, delete raw audio) are available on each recording.
          </p>
          <p>
            <strong>Restriction, objection, complaint:</strong> email{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="text-brand-primary underline">
              {CONTACT_EMAIL}
            </a>{" "}
            for anything not covered by the self-serve controls — we respond within one month.
            You also have the right to lodge a complaint with your local data protection
            supervisory authority.
          </p>
        </Section>

        <Section title="Cookies">
          <p>
            Brain Buddy sets exactly one cookie: <code>brainbuddy_session</code>, a strictly
            necessary, HttpOnly session cookie that keeps you signed in for up to 30 days. It is
            not used for tracking, analytics, or advertising — which is why there is no cookie
            banner.
          </p>
        </Section>

        <Section title="Changes to this policy">
          <p>
            When this policy changes materially, the &ldquo;last updated&rdquo; date above changes
            with it, and significant changes will be called out in the app.
          </p>
        </Section>

        <p className="mt-10 text-center text-xs text-slate-400">
          <Link to="/login" className="underline">
            Back to sign in
          </Link>
        </p>
      </article>
    </main>
  );
}
