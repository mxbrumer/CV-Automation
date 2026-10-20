import { Link, useSearchParams } from 'react-router'
import type { PostingStatus } from '../api/client'
import { JOBS_PAGE_SIZE, usePostings } from '../api/hooks'
import { STATUS_LABEL } from '../components/PostingInfo'

const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' })
const STATUSES = Object.keys(STATUS_LABEL) as PostingStatus[]

const isStatus = (v: string | null): v is PostingStatus =>
  v !== null && STATUSES.includes(v as PostingStatus)

const field = 'rounded-md border border-line bg-surface px-2 py-1.5 text-sm'

/** Every posting in the system; filters live in the URL so Back returns to the same view. */
export default function Jobs() {
  const [params, setParams] = useSearchParams()
  const rawStatus = params.get('status')
  const status = isStatus(rawStatus) ? rawStatus : undefined
  const q = params.get('q') ?? ''
  const sort = params.get('sort') === 'score' ? 'score' : 'recent'
  const page = Math.max(1, Number(params.get('page')) || 1)

  const postings = usePostings({ status, q, sort, page })
  const items = postings.data?.items ?? []
  const total = postings.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / JOBS_PAGE_SIZE))
  const filtered = status !== undefined || q !== ''

  /** Changes one filter and goes back to page 1; `replace` keeps typing out of the history. */
  function set(key: string, value: string) {
    setParams(
      (cur) => {
        const next = new URLSearchParams(cur)
        if (value) next.set(key, value)
        else next.delete(key)
        if (key !== 'page') next.delete('page')
        return next
      },
      { replace: key === 'q' },
    )
  }

  const first = (page - 1) * JOBS_PAGE_SIZE + 1
  const last = first + items.length - 1

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Jobs</h1>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          <span className="text-muted">Search title or company</span>
          <input
            type="search"
            value={q}
            onChange={(e) => set('q', e.target.value)}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Status</span>
          <select
            value={status ?? ''}
            onChange={(e) => set('status', e.target.value)}
            className={field}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Sort</span>
          <select
            value={sort}
            onChange={(e) => set('sort', e.target.value === 'score' ? 'score' : '')}
            className={field}
          >
            <option value="recent">Newest first</option>
            <option value="score">Best match first</option>
          </select>
        </label>
      </div>

      {postings.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not load the jobs.
        </p>
      )}
      {postings.isSuccess && items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
          {filtered ? (
            'No jobs match these filters.'
          ) : (
            <>
              No jobs yet. Paste a job description in{' '}
              <Link to="/add" className="text-accent underline">
                Add job
              </Link>
              .
            </>
          )}
        </p>
      ) : (
        items.length > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-line bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">Title</th>
                    <th className="px-3 py-2 font-medium">Company</th>
                    <th className="px-3 py-2 text-right font-medium">Score</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Added</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((p) => (
                    <tr key={p.posting_id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2">
                        <Link
                          to={`/jobs/${p.posting_id}`}
                          state={{ from: `/jobs?${params}` }}
                          className="text-accent underline"
                        >
                          {p.title}
                        </Link>
                      </td>
                      <td className="px-3 py-2">{p.company}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {p.match_score === null ? '–' : Math.round(p.match_score)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">{STATUS_LABEL[p.status]}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {date.format(new Date(p.created_at))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="text-muted">
                {first}–{last} of {total}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => set('page', String(page - 1))}
                  className="rounded-md border border-line px-3 py-1 disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-muted">
                  Page {page} of {pages}
                </span>
                <button
                  type="button"
                  disabled={page >= pages}
                  onClick={() => set('page', String(page + 1))}
                  className="rounded-md border border-line px-3 py-1 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )
      )}
    </section>
  )
}
