import { Link, useLocation, useParams } from 'react-router'
import { fileUrl, type PostingStatus } from '../api/client'
import { usePosting } from '../api/hooks'
import PostingInfo, { STATUS_LABEL } from '../components/PostingInfo'

const dateTime = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

const KIND_LABEL = { cv: 'CV', cover_letter: 'Cover letter', recruiter_email: 'Recruiter email' }

/** Where the user acts on a posting in this status, if anywhere. */
function nextStep(id: number, status: PostingStatus): { to: string; label: string } | null {
  if (status === 'awaiting_match_review') return { to: '/matches', label: 'Decide in Matches' }
  if (status === 'generated') return { to: `/review/${id}`, label: 'Review the drafts' }
  if (status === 'approved') return { to: '/queue', label: 'Submit from the Queue' }
  return null
}

export default function JobDetail() {
  const id = Number(useParams().id)
  const q = usePosting(id)
  // the list passes its filtered URL, so going back keeps the search and page
  const back = (useLocation().state as { from?: string } | null)?.from ?? '/jobs'

  if (q.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-warn-fg">
        Could not load the posting.{' '}
        <Link to={back} className="text-accent underline">
          Back to Jobs
        </Link>
      </p>
    )

  const p = q.data
  const step = nextStep(p.posting_id, p.status)
  const contact = [p.recruiter_name, p.recruiter_email, p.recruiter_phone].filter(Boolean)

  return (
    <article className="space-y-6">
      <Link to={back} className="text-sm text-accent underline">
        ← All jobs
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{p.title}</h1>
          <p className="text-muted">{p.company}</p>
          <p className="mt-1 text-sm text-muted">
            Added {dateTime.format(new Date(p.created_at))} · updated{' '}
            {dateTime.format(new Date(p.updated_at))}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-baseline gap-3">
            <span className="rounded-full border border-line px-2 py-0.5 text-sm">
              {STATUS_LABEL[p.status]}
            </span>
            <span className="text-2xl font-semibold tabular-nums" aria-label="Match score">
              {p.match_score === null ? '–' : Math.round(p.match_score)}
            </span>
          </div>
          {step && (
            <Link
              to={step.to}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg"
            >
              {step.label}
            </Link>
          )}
        </div>
      </header>

      <PostingInfo posting={p} />

      {contact.length > 0 && (
        <section className="text-sm">
          <h2 className="mb-1 font-medium">Recruiter</h2>
          <p className="text-muted">{contact.join(' · ')}</p>
        </section>
      )}

      {p.artifacts.length > 0 && (
        <section className="text-sm">
          <h2 className="mb-1 font-medium">Documents</h2>
          {p.host_folder && (
            <p className="mb-1">
              <code className="break-all rounded bg-bg px-1.5 py-0.5">{p.host_folder}</code>
            </p>
          )}
          <ul className="space-y-0.5">
            {p.artifacts.map((a) => (
              <li key={a.artifact_id}>
                {KIND_LABEL[a.kind]} v{a.version}
                {a.approved && <span className="text-muted"> · approved</span>}
                {a.pdf_path && (
                  <>
                    {' · '}
                    <a
                      className="text-accent underline"
                      target="_blank"
                      rel="noreferrer"
                      href={fileUrl(p.posting_id, a.pdf_path)}
                    >
                      PDF
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="text-sm">
        <h2 className="mb-1 font-medium">History</h2>
        {p.events.length === 0 ? (
          <p className="text-muted">No status changes yet.</p>
        ) : (
          <ol className="space-y-1">
            {p.events.map((e) => (
              <li key={e.event_id} className="flex flex-wrap gap-x-2">
                <span className="text-muted tabular-nums">{dateTime.format(new Date(e.at))}</span>
                <span>
                  {e.from_status ? `${STATUS_LABEL[e.from_status]} → ` : ''}
                  {STATUS_LABEL[e.to_status]}
                </span>
                <span className="text-muted">({e.actor})</span>
                {e.note &&
                  (e.note.length > 120 ? (
                    <details className="w-full text-muted">
                      <summary className="cursor-pointer">Note</summary>
                      <p className="break-all">{e.note}</p>
                    </details>
                  ) : (
                    <span className="text-muted">{e.note}</span>
                  ))}
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  )
}
