import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { PostingSummary } from '../api/client'
import { DuplicateError, useAddJob } from '../api/hooks'
import Toast from '../components/Toast'

/** Below this the pasted text is probably a teaser, not the whole description (D4). */
const MIN_WORDS = 150
const EMPTY = { company: '', title: '', url: '', text: '' }

const wordCount = (s: string) => s.split(/\s+/).filter(Boolean).length

/** Where the app shows a posting in its current status, if anywhere. */
function appHref(p: PostingSummary): string | null {
  if (p.status === 'awaiting_match_review') return '/matches'
  if (p.status === 'generated') return `/review/${p.posting_id}`
  if (p.status === 'approved') return '/queue'
  return null
}

function PostingLink({ p }: { p: PostingSummary }) {
  const label = `${p.title} at ${p.company}`
  const href = appHref(p)
  if (href) {
    return (
      <Link to={href} className="text-accent underline">
        {label}
      </Link>
    )
  }
  if (p.source_url) {
    return (
      <a href={p.source_url} target="_blank" rel="noreferrer" className="text-accent underline">
        {label}
      </a>
    )
  }
  return <span>{label}</span>
}

const field = 'mt-1 w-full rounded-md border border-line bg-bg px-2 py-1'

export default function AddJob() {
  const [form, setForm] = useState(EMPTY)
  const add = useAddJob()
  const navigate = useNavigate()
  const words = wordCount(form.text)
  const duplicate = add.error instanceof DuplicateError ? add.error.duplicate : null
  const ready = form.company.trim() && form.title.trim() && form.text.trim()

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: e.target.value }))
    if (add.isError) add.reset() // an edit answers a duplicate warning
  }

  const submit = (force: boolean) =>
    add.mutate(
      {
        company: form.company,
        title: form.title,
        url: form.url.trim() || null,
        text: form.text,
        force,
      },
      {
        onSuccess: (p) => {
          setForm(EMPTY)
          add.reset()
          navigate('/add', {
            replace: true,
            state: { toast: `Added “${p.title}” at ${p.company}. Its analysis has started.` },
          })
        },
      },
    )

  return (
    <section className="max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Add job</h1>
      <Toast />
      <p className="text-sm text-muted">
        Paste the whole job description. The job is scored against your CV and shows up in Matches
        when it is a good fit.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (ready) submit(false)
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-muted">Company</span>
            <input value={form.company} onChange={set('company')} required className={field} />
          </label>
          <label className="block text-sm">
            <span className="text-muted">Job title</span>
            <input value={form.title} onChange={set('title')} required className={field} />
          </label>
        </div>
        <label className="block text-sm">
          <span className="text-muted">Application URL (optional)</span>
          <input type="url" value={form.url} onChange={set('url')} className={field} />
        </label>
        <label className="block text-sm">
          <span className="flex justify-between text-muted">
            <span>Job description</span>
            <span data-testid="word-count">{words} words</span>
          </span>
          <textarea value={form.text} onChange={set('text')} required rows={14} className={field} />
        </label>
        {words > 0 && words < MIN_WORDS && (
          <p className="text-sm text-warn-fg">
            Only {words} words. A full description is usually longer; check that you pasted all of
            it. You can still add the job.
          </p>
        )}

        {duplicate?.reason === 'same_url' && (
          <p role="alert" className="text-sm text-warn-fg">
            This application URL is already stored: <PostingLink p={duplicate.posting} />
          </p>
        )}
        {duplicate?.reason === 'similar' && (
          <div role="alert" className="space-y-2 rounded-lg border border-warn-fg bg-warn-bg p-3">
            <p className="text-sm text-warn-fg">A similar job is already stored:</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
              <dt className="text-muted">Company</dt>
              <dd>{duplicate.posting.company}</dd>
              <dt className="text-muted">Title</dt>
              <dd>{duplicate.posting.title}</dd>
              <dt className="text-muted">Status</dt>
              <dd>{duplicate.posting.status.replaceAll('_', ' ')}</dd>
            </dl>
            <p className="text-sm">
              <PostingLink p={duplicate.posting} />
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => submit(true)}
                disabled={add.isPending}
                className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg disabled:opacity-50"
              >
                Add anyway
              </button>
              <button
                type="button"
                onClick={() => add.reset()}
                className="rounded-md border border-line px-3 py-1 text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {add.isError && !duplicate && (
          <p role="alert" className="text-sm text-warn-fg">
            Could not add the job: {add.error.message}
          </p>
        )}

        {!duplicate && (
          <button
            type="submit"
            disabled={!ready || add.isPending}
            className="rounded-md bg-accent px-3 py-1.5 font-medium text-bg disabled:opacity-50"
          >
            {add.isPending ? 'Adding…' : 'Add job'}
          </button>
        )}
      </form>
    </section>
  )
}
