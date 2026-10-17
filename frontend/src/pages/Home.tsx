import { Link } from 'react-router'
import {
  useLastRun,
  useProcessPending,
  useRecentPostings,
  useStats,
  useStatusCount,
} from '../api/hooks'
import StatTile from '../components/StatTile'

const dateTime = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

export default function Home() {
  const stats = useStats()
  const submitted = useStatusCount('submitted')
  const recent = useRecentPostings(10)
  const lastRun = useLastRun()
  const run = useProcessPending()

  const items = recent.data?.items ?? []
  const last = lastRun.data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Home</h1>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-muted" data-testid="last-run">
            {last
              ? `Last run: ${last.phase} ${last.status}, ${dateTime.format(new Date(last.started_at))}`
              : 'No pipeline run yet'}
          </span>
          <button
            type="button"
            onClick={() => run.mutate()}
            disabled={run.isPending}
            title="Re-runs analysis for new jobs and drafting for approved matches, for example after a backend restart"
            className="rounded-md bg-accent px-3 py-1.5 font-medium text-bg disabled:opacity-60"
          >
            {run.isPending ? 'Starting…' : 'Process pending'}
          </button>
        </div>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not start processing: {run.error.message}
        </p>
      )}
      {run.isSuccess && <p className="text-sm text-muted">Processing queued.</p>}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="Job postings reviewed" value={stats.data?.reviewed} />
        <StatTile label="Good matches" value={stats.data?.good_match} />
        <StatTile label="Applications submitted" value={submitted.data} />
      </div>

      <section>
        <h2 className="mb-2 text-base font-semibold">Latest postings</h2>
        {recent.isSuccess && items.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
            No postings yet. Paste a job description in{' '}
            <Link to="/add" className="text-accent underline">
              Add job
            </Link>
            .
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Title</th>
                  <th className="px-3 py-2 font-medium">Company</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.posting_id} className="border-b border-line last:border-0">
                    <td className="px-3 py-2">{p.title}</td>
                    <td className="px-3 py-2">{p.company}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {p.match_score === null ? '–' : Math.round(p.match_score)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">{p.status.replaceAll('_', ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {recent.isError && (
          <p role="alert" className="mt-2 text-sm text-warn-fg">
            Could not load postings.
          </p>
        )}
      </section>
    </div>
  )
}
