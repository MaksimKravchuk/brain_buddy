import { ChevronLeft, Inbox, Mic, Plus, Square, Trash2, X } from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

interface Proposal {
  ordinal: number;
  title: string;
  tag?: string;
  project?: string;
  due?: string;
  status: "Ready to review" | "Provisional" | "Wording still changing" | "Edited" | "Needs review";
}

const proposals: Proposal[] = [
  { ordinal: 1, title: "Renew car insurance", tag: "errands", status: "Ready to review" },
  { ordinal: 2, title: "Reply to Anna about the offsite", status: "Ready to review" },
  { ordinal: 3, title: "Book flights to Lisbon", status: "Ready to review" },
  { ordinal: 4, title: "Update pricing page copy", status: "Ready to review" },
  { ordinal: 5, title: "Prepare interview questions for Vlad", status: "Ready to review" },
  { ordinal: 6, title: "Call dentist to move Monday's appointment", tag: "calls", status: "Provisional" },
  { ordinal: 7, title: "Take car in for the flat tire", tag: "errands", due: "before Sat", status: "Provisional" },
  { ordinal: 8, title: "Draft launch announcement post", project: "Launch v2", status: "Provisional" },
  { ordinal: 9, title: "Cancel unused SaaS subscriptions", status: "Wording still changing" }
];

export function BrainDumpRoute(): JSX.Element {
  const location = useLocation();
  const params = useParams();
  const isReview = location.pathname.endsWith("/review");

  return isReview ? <ReviewSurface /> : <RecordingSurface operationId={params.operationId ?? "new"} />;
}

function RecordingSurface({ operationId }: { operationId: string }): JSX.Element {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-surface-base text-slate-900" data-operation-id={operationId}>
      <div className="pointer-events-none fixed inset-0 opacity-50 blur-[1px]" aria-hidden>
        <div className="h-[52px] border-b border-slate-200 bg-white" />
        <div className="mx-auto mt-7 flex max-w-[720px] flex-col gap-2 px-6">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-12 rounded-xl border border-slate-200 bg-white" />
          ))}
        </div>
      </div>
      <div className="fixed inset-0 flex items-center justify-center bg-slate-50/80 p-0 backdrop-blur-sm sm:p-4">
        <section
          role="dialog"
          aria-modal="true"
          aria-labelledby="brain-dump-title"
          className="flex h-[100dvh] w-full flex-col overflow-hidden bg-white shadow-floating sm:h-[640px] sm:w-[min(720px,calc(100vw-32px))] sm:rounded-[20px] sm:border sm:border-slate-200"
        >
          <header className="flex shrink-0 items-center gap-2 border-b border-slate-100 px-5 py-4 sm:px-6">
            <h1 id="brain-dump-title" className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">
              Brain dump
            </h1>
            <span className="text-xs text-slate-400">·</span>
            <span className="text-xs font-semibold text-slate-900">9 tasks captured</span>
            <span className="ml-auto inline-flex items-center gap-1.5 text-xs font-medium text-rose-600">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-600" aria-hidden />
              01:24
            </span>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-6" aria-live="polite">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">Headed to inbox · 9</div>
            <div className="flex flex-col gap-2">
              {proposals.map((proposal) => (
                <ProposalCard key={proposal.ordinal} proposal={proposal} forming={proposal.ordinal === 9} />
              ))}
            </div>
          </div>

          <footer className="shrink-0 border-t border-slate-100 bg-slate-50/80 px-4 py-3 sm:px-5">
            <div className="flex items-center gap-3">
              <div className="relative h-10 w-10 shrink-0">
                <span className="absolute inset-0 animate-[bbPulse_1.8s_cubic-bezier(.22,1,.36,1)_infinite] rounded-full bg-sky-200/70" />
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-brand-primary text-white">
                  <Mic className="h-4 w-4" aria-hidden />
                </div>
              </div>
              <div className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[13px] leading-normal text-slate-500">
                …take the car in before the weekend. For the launch post, <span className="text-slate-700">maybe AI can draft it and I'll review it on Thursday</span>
                <span className="ml-0.5 inline-block h-[13px] w-0.5 animate-[bbBlink_1.1s_step-end_infinite] bg-brand-primary align-text-bottom" />
              </div>
              <button type="button" className="hidden h-10 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 sm:inline-flex sm:items-center">
                Discard
              </button>
              <button
                type="button"
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white shadow-soft hover:bg-brand-primary-hover sm:px-5"
                onClick={() => navigate(`/brain-dump/${operationId}/review`)}
              >
                <Square className="h-3.5 w-3.5" aria-hidden />
                Stop & review
              </button>
            </div>
            <p className="mt-2 text-center text-xs text-slate-500">Nothing is saved until you stop</p>
          </footer>
        </section>
      </div>
    </div>
  );
}

function ProposalCard({ proposal, forming = false }: { proposal: Proposal; forming?: boolean }): JSX.Element {
  return (
    <article
      className={`flex items-center gap-2 rounded-[10px] border px-3.5 py-2.5 shadow-soft ${
        forming
          ? "border-dashed border-slate-300 bg-[linear-gradient(90deg,rgba(241,245,249,0)_0,rgba(255,255,255,.9)_50%,rgba(241,245,249,0)_100%),#f8fafc] bg-[length:260px_100%] bg-no-repeat animate-[bbShimmer_1.6s_linear_infinite]"
          : proposal.project
            ? "border-emerald-200 bg-white"
            : "border-slate-200 bg-white"
      }`}
    >
      <span className="text-[11px] font-semibold text-slate-500">#{proposal.ordinal}</span>
      <div className="min-w-0 flex-1 text-sm font-medium text-slate-900">{proposal.title}</div>
      {proposal.tag ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">@{proposal.tag}</span> : null}
      {proposal.project ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{proposal.project}</span> : null}
      {proposal.due ? <span className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">{proposal.due}</span> : null}
      <span className={forming ? "text-[11px] text-slate-500" : "rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700"}>
        {proposal.status}
      </span>
    </article>
  );
}

function ReviewSurface(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-surface-base text-slate-900">
      <header className="flex shrink-0 items-center gap-3 border-b border-slate-100 bg-white/95 px-4 pt-[max(16px,env(safe-area-inset-top))] pb-3">
        <button type="button" className="flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600" aria-label="Back to recording">
          <ChevronLeft className="h-5 w-5" aria-hidden />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="text-[17px] font-semibold tracking-[-0.015em] text-slate-900">Review 9 tasks</h1>
          <p className="mt-0.5 text-xs text-slate-500">Edit before they land in your inbox</p>
        </div>
        <button type="button" className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-sky-700">
          Select
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div className="flex flex-col gap-2.5">
          <ExpandedReviewCard proposal={proposals[0]} />
          {proposals.slice(1).map((proposal) => (
            <CollapsedReviewCard key={proposal.ordinal} proposal={proposal} revealDelete={proposal.ordinal === 4} />
          ))}
          <button type="button" className="flex min-h-11 items-center gap-2 rounded-[14px] border border-dashed border-slate-300 bg-transparent px-3.5 text-sm text-slate-600">
            <Plus className="h-4 w-4" aria-hidden />
            Add a task
          </button>
        </div>
      </main>

      <footer className="flex shrink-0 items-center gap-3 border-t border-slate-100 bg-white/95 px-4 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
        <button type="button" className="h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-600">
          Discard
        </button>
        <button type="button" className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand-primary text-[15px] font-semibold text-white shadow-glow">
          <Inbox className="h-4 w-4" aria-hidden />
          Save 9 to inbox
        </button>
      </footer>
    </div>
  );
}

function ExpandedReviewCard({ proposal }: { proposal: Proposal }): JSX.Element {
  return (
    <article className="rounded-[14px] border-[1.5px] border-brand-primary bg-white px-3.5 py-3 shadow-[0_1px_2px_rgba(15,23,42,.05),0_10px_24px_-14px_rgba(14,165,233,.4)]">
      <div className="flex items-start gap-2.5">
        <span className="mt-1 text-xs font-semibold text-slate-500">#{proposal.ordinal}</span>
        <div className="min-w-0 flex-1">
          <label className="sr-only" htmlFor="proposal-title-1">Task title #1</label>
          <input
            id="proposal-title-1"
            defaultValue={proposal.title}
            className="w-full border-0 border-b-[1.5px] border-sky-200 bg-transparent pb-1 text-[15px] font-medium text-slate-900 outline-none"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">Inbox</span>
            {proposal.tag ? <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">@{proposal.tag}</span> : null}
            <span className="rounded-full border border-dashed border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-500">Add date</span>
            <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs text-sky-700">{proposal.status}</span>
          </div>
        </div>
        <button type="button" className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-300 hover:bg-rose-50 hover:text-rose-500" aria-label={`Delete ${proposal.title}`}>
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </article>
  );
}

function CollapsedReviewCard({ proposal, revealDelete = false }: { proposal: Proposal; revealDelete?: boolean }): JSX.Element {
  if (revealDelete) {
    return (
      <ReviewRow
        proposal={proposal}
        className="border-rose-200 bg-rose-50/30"
        actionClassName="bg-rose-500 text-white hover:bg-rose-600 hover:text-white"
        actionIcon={<Trash2 className="h-4 w-4" aria-hidden />}
      />
    );
  }

  return <ReviewRow proposal={proposal} />;
}

function ReviewRow({
  proposal,
  className = "",
  actionClassName = "text-slate-400 hover:bg-rose-50 hover:text-rose-500",
  actionIcon = <X className="h-4 w-4" aria-hidden />
}: {
  proposal: Proposal;
  className?: string;
  actionClassName?: string;
  actionIcon?: JSX.Element;
}): JSX.Element {
  return (
    <article className={`flex min-h-12 items-center gap-3 rounded-[14px] border border-slate-200 bg-white px-3.5 py-3 shadow-soft ${className}`}>
      <span className="text-xs font-semibold text-slate-500">#{proposal.ordinal}</span>
      <div className="min-w-0 flex-1 text-[15px] font-medium text-slate-900">{proposal.title}</div>
      {proposal.tag ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">@{proposal.tag}</span> : null}
      <span className="sr-only">{proposal.status}</span>
      <button type="button" className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${actionClassName}`} aria-label={`Delete ${proposal.title}`}>
        {actionIcon}
      </button>
    </article>
  );
}
