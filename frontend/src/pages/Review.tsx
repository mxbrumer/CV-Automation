import { Link } from 'react-router'
import { useGenerated } from '../api/hooks'
import Toast from '../components/Toast'

const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' })

export default function Review() {
  const generated = useGenerated()
  const items = generated.data ?? []

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Review</h1>
      <Toast />
      {generated.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not load the drafts.
        </p>
      )}
      {generated.isSuccess && items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
          No drafts to review. Approve a match in the{' '}
          <Link to="/matches" className="text-accent underline">
            Matches tab
          </Link>{' '}
          to generate one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Company</th>
                <th className="py-1 pr-3 font-medium">Title</th>
                <th className="py-1 pr-3 text-right font-medium">Score</th>
                <th className="py-1 pr-3 font-medium">Language</th>
                <th className="py-1 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.posting_id} className="border-t border-line">
                  <td className="py-2 pr-3">{i.company}</td>
                  <td className="py-2 pr-3">
                    <Link to={`/review/${i.posting_id}`} className="text-accent underline">
                      {i.title}
                    </Link>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {i.match_score === null ? '–' : Math.round(i.match_score)}
                  </td>
                  <td className="py-2 pr-3">{i.posting_language ?? '?'}</td>
                  <td className="py-2">{date.format(new Date(i.created_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
