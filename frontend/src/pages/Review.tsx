import { useState } from 'react'
import { Link } from 'react-router'
import type { PostingSummary } from '../api/client'
import { useGenerated, useNeedsText, usePasteText } from '../api/hooks'
import Toast from '../components/Toast'

const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' })

function PasteBox({ item }: { item: PostingSummary }) {
  const [text, setText] = useState('')
  const paste = usePasteText()
  const id = item.posting_id
  return (
    <li className="space-y-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span>
          <span className="font-medium">{item.title}</span>{' '}
          <span className="text-sm text-muted">{item.company}</span>
        </span>
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-accent underline"
          >
            Open the posting
          </a>
        )}
      </div>
      <label className="block text-sm">
        <span className="text-muted">Posting text for {item.title}</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1"
        />
      </label>
      <button
        type="button"
        disabled={text.trim().length < 20 || paste.isPending}
        onClick={() => paste.mutate({ id, text })}
        className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg disabled:opacity-50"
      >
        Send to analysis
      </button>
      {paste.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not save the text: {paste.error.message}
        </p>
      )}
    </li>
  )
}

export default function Review() {
  const generated = useGenerated()
  const needsText = useNeedsText()
  const items = generated.data ?? []
  const manual = needsText.data ?? []

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
      {manual.length > 0 && (
        <div className="space-y-2">
          <h2 className="font-medium">Needs the posting text</h2>
          <p className="text-sm text-muted">
            The page could not be read automatically. Paste the text and the posting goes back to
            analysis.
          </p>
          <ul className="space-y-2">
            {manual.map((i) => (
              <PasteBox key={i.posting_id} item={i} />
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
