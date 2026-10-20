import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import type { PostingSummary } from '../api/client'
import { useMatchDecision, useMatchQueue, usePosting } from '../api/hooks'
import PostingInfo from '../components/PostingInfo'

const UNDO_MS = 5000
const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' })

type Decision = 'approve' | 'decline'
type Pending = { item: PostingSummary; decision: Decision; note: string; timer: number }

function Detail({ id, note, onNote }: { id: number; note: string; onNote: (v: string) => void }) {
  const q = usePosting(id)
  if (q.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-warn-fg">
        Could not load the posting.
      </p>
    )
  return (
    <div className="space-y-3 text-sm">
      <PostingInfo posting={q.data} />
      <label className="block">
        <span className="text-muted">Decline reason (optional)</span>
        <input
          value={note}
          onChange={(e) => onNote(e.target.value)}
          className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1"
        />
      </label>
    </div>
  )
}

export default function Matches() {
  const queue = useMatchQueue()
  const decide = useMatchDecision()
  const [selected, setSelected] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [pending, setPending] = useState<Record<number, Pending>>({})
  const pendingRef = useRef(pending)
  useEffect(() => {
    pendingRef.current = pending
  }, [pending])
  const mutate = decide.mutate

  const send = useCallback(
    (p: Pending) => mutate({ id: p.item.posting_id, decision: p.decision, note: p.note }),
    [mutate],
  )

  const drop = useCallback((id: number) => {
    setPending((cur) => {
      const rest = { ...cur }
      delete rest[id]
      return rest
    })
  }, [])

  // Leaving the page must not lose a decision that is still inside its undo window.
  useEffect(
    () => () => {
      for (const p of Object.values(pendingRef.current)) {
        window.clearTimeout(p.timer)
        send(p)
      }
    },
    [send],
  )

  const items = (queue.data ?? []).filter((i) => !pending[i.posting_id])

  const act = useCallback(
    (item: PostingSummary, decision: Decision) => {
      const id = item.posting_id
      const note = decision === 'decline' ? (notes[id] ?? '') : ''
      const timer = window.setTimeout(() => {
        const p = pendingRef.current[id]
        drop(id)
        if (p) send(p)
      }, UNDO_MS)
      setPending((cur) => ({ ...cur, [id]: { item, decision, note, timer } }))
    },
    [notes, send, drop],
  )

  const undo = (id: number) => {
    const p = pending[id]
    if (!p) return
    window.clearTimeout(p.timer)
    drop(id)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey)
        return
      const idx = items.findIndex((i) => i.posting_id === selected)
      if (e.key === 'j' || e.key === 'k') {
        const step = e.key === 'j' ? 1 : -1
        const next = items[Math.min(items.length - 1, Math.max(0, idx + step))]
        if (next) setSelected(next.posting_id)
      } else if ((e.key === 'a' || e.key === 'd') && idx >= 0) {
        // keep the cursor on a neighbour so repeated presses work through the list
        setSelected((items[idx + 1] ?? items[idx - 1])?.posting_id ?? null)
        act(items[idx], e.key === 'a' ? 'approve' : 'decline')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, selected, act])

  return (
    <section className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold">Matches</h1>
        <span className="hidden text-xs text-muted sm:inline">
          j/k move · a approve · d decline
        </span>
      </div>
      {queue.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not load matches.
        </p>
      )}
      {queue.isSuccess && items.length === 0 && Object.keys(pending).length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
          Nothing to confirm. Paste a job in{' '}
          <Link to="/add" className="text-accent underline">
            Add job
          </Link>
          ; good matches show up here after their analysis.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const id = item.posting_id
            const isOpen = open === id
            return (
              <li
                key={id}
                data-selected={selected === id}
                className={clsx(
                  'rounded-lg border bg-surface',
                  selected === id ? 'border-accent' : 'border-line',
                )}
              >
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => {
                    setSelected(id)
                    setOpen(isOpen ? null : id)
                  }}
                  className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-left"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{item.title}</span>
                    <span className="block text-sm text-muted">{item.company}</span>
                  </span>
                  <span className="text-sm text-muted">
                    {item.posting_language ?? '?'} · {date.format(new Date(item.created_at))}
                  </span>
                  <span className="w-10 text-right text-lg font-semibold tabular-nums">
                    {item.match_score === null ? '–' : Math.round(item.match_score)}
                  </span>
                </button>
                {isOpen && (
                  <div className="border-t border-line px-3 py-3">
                    <Detail
                      id={id}
                      note={notes[id] ?? ''}
                      onNote={(v) => setNotes((n) => ({ ...n, [id]: v }))}
                    />
                  </div>
                )}
                <div className="flex gap-2 border-t border-line px-3 py-2">
                  <button
                    type="button"
                    onClick={() => act(item, 'approve')}
                    className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => act(item, 'decline')}
                    className="rounded-md border border-line px-3 py-1 text-sm"
                  >
                    Decline
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {decide.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not save the decision: {decide.error.message}
        </p>
      )}
      <div className="fixed inset-x-4 bottom-4 space-y-2 sm:left-auto sm:w-96" aria-live="polite">
        {Object.values(pending).map(({ item, decision }) => (
          <div
            key={item.posting_id}
            role="status"
            className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-lg"
          >
            <span>
              {decision === 'approve'
                ? `Approved ${item.title}. Drafts are being generated.`
                : `Declined ${item.title}.`}
            </span>
            <button
              type="button"
              onClick={() => undo(item.posting_id)}
              className="font-medium text-accent underline"
            >
              Undo
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
