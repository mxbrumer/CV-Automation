import MarkdownIt from 'markdown-it'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useArtifact, usePosting, useQueue, useQueueAction } from '../api/hooks'
import { fileUrl } from '../api/client'
import Markdown from '../components/Markdown'

const UNDO_MS = 5000
const DIAGRAM_URL =
  'https://raw.githubusercontent.com/mxbrumer/Moving-To-Denmark/main/docs/assets/workflow.png'

const md = new MarkdownIt({ html: false, linkify: false })

/** The recruiter email is stored as `Subject: ...` on the first line, then the body. */
function splitEmail(markdown: string): { subject: string; body: string } {
  const m = markdown.match(/^\s*Subject:[ \t]*(.*)\r?\n?/i)
  return m
    ? { subject: m[1].trim(), body: markdown.slice(m[0].length).trim() }
    : { subject: '', body: markdown.trim() }
}

type Action = 'submitted' | 'declined'
type Pending = { id: number; action: Action; note: string; timer: number }

function CopyButton({ label, text }: { label: string; text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setDone(true)
        window.setTimeout(() => setDone(false), 1500)
      }}
      className="rounded-md border border-line px-2 py-1 text-sm"
    >
      {done ? 'Copied' : label}
    </button>
  )
}

function Email({ id, address }: { id: number; address: string | null }) {
  const q = useArtifact(id, 'recruiter_email')
  const [rich, setRich] = useState<'idle' | 'done' | 'failed'>('idle')
  if (q.isPending) return <p className="text-sm text-muted">Loading email…</p>
  if (q.isError) return <p className="text-sm text-warn-fg">Could not load the recruiter email.</p>
  const { subject, body } = splitEmail(q.data.markdown)

  async function copyRich() {
    const html = `${md.render(body)}<img src="${DIAGRAM_URL}" width="600" alt="Workflow diagram">`
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([body], { type: 'text/plain' }),
        }),
      ])
      setRich('done')
    } catch {
      setRich('failed')
    }
  }

  return (
    <div className="space-y-2" aria-label="Recruiter email">
      <h3 className="font-medium">Recruiter email</h3>
      <dl className="text-sm">
        <div className="flex gap-2">
          <dt className="text-muted">To</dt>
          <dd>{address ?? 'no address found'}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Subject</dt>
          <dd>{subject || 'no subject'}</dd>
        </div>
      </dl>
      <div className="rounded-md border border-line bg-bg p-3">
        <Markdown source={body} />
        <img src={DIAGRAM_URL} width={300} alt="Workflow diagram" className="mt-3" />
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={copyRich}
          className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg"
        >
          Copy as rich text
        </button>
        <CopyButton label="Copy subject" text={subject} />
        {address && <CopyButton label="Copy address" text={address} />}
      </div>
      {rich === 'done' && <p className="text-sm text-muted">Copied with the diagram.</p>}
      {rich === 'failed' && (
        <p role="alert" className="text-sm text-warn-fg">
          The browser refused rich-text copy.
        </p>
      )}
    </div>
  )
}

function Files({ id }: { id: number }) {
  const q = usePosting(id)
  if (q.isPending) return <p className="text-sm text-muted">Loading files…</p>
  if (q.isError) return <p className="text-sm text-warn-fg">Could not load the posting.</p>
  const p = q.data
  const latest = new Map<string, (typeof p.artifacts)[number]>()
  for (const a of p.artifacts) {
    if (!a.pdf_path || !a.approved) continue
    const cur = latest.get(a.kind)
    if (!cur || a.version > cur.version) latest.set(a.kind, a)
  }
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h3 className="font-medium">Final files</h3>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <code className="break-all rounded bg-bg px-1.5 py-0.5">
            {p.host_folder ?? 'no folder'}
          </code>
          {p.host_folder && <CopyButton label="Copy path" text={p.host_folder} />}
        </div>
        <ul className="text-sm">
          {[...latest.values()].map((a) => (
            <li key={a.artifact_id}>
              <a
                className="text-accent underline"
                target="_blank"
                rel="noreferrer"
                href={fileUrl(id, a.pdf_path ?? '')}
              >
                {a.kind === 'cv' ? 'CV' : 'Cover letter'} (v{a.version}, PDF)
              </a>
            </li>
          ))}
          {latest.size === 0 && <li className="text-muted">No approved PDFs found.</li>}
        </ul>
      </div>
      <Email id={id} address={p.recruiter_email} />
    </div>
  )
}

export default function Queue() {
  const queue = useQueue()
  const act = useQueueAction()
  const [confirm, setConfirm] = useState<{ action: Action; note: string } | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const pendingRef = useRef<Pending | null>(null)
  useEffect(() => {
    pendingRef.current = pending
  }, [pending])

  // Leaving the page sends a decision that is still in its undo window.
  const mutate = act.mutate
  useEffect(
    () => () => {
      const p = pendingRef.current
      if (p) {
        window.clearTimeout(p.timer)
        mutate({ id: p.id, action: p.action, note: p.note })
      }
    },
    [mutate],
  )

  const items = queue.data ?? []
  const head = items.find((i) => i.posting_id !== pending?.id) ?? null
  const total = items.length - (pending ? 1 : 0)

  function start(action: Action, note: string) {
    if (!head) return
    const id = head.posting_id
    const timer = window.setTimeout(() => {
      setPending(null)
      mutate({ id, action, note })
    }, UNDO_MS)
    setPending({ id, action, note, timer })
    setConfirm(null)
  }

  function undo() {
    if (pending) window.clearTimeout(pending.timer)
    setPending(null)
  }

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Queue</h1>
      {queue.isError && (
        <p role="alert" className="text-sm text-warn-fg">
          Could not load the queue.
        </p>
      )}
      {pending && (
        <p
          role="status"
          className="flex items-center gap-3 rounded-md border border-line bg-surface px-3 py-2 text-sm"
        >
          {pending.action === 'submitted' ? 'Marked as submitted.' : 'Rejected.'}
          <button type="button" onClick={undo} className="text-accent underline">
            Undo
          </button>
        </p>
      )}
      {queue.isSuccess && !head ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-muted">
          The queue is empty. Approve drafts in the{' '}
          <Link to="/review" className="text-accent underline">
            Review tab
          </Link>
          .
        </p>
      ) : (
        head && (
          <article className="space-y-4 rounded-lg border border-line bg-surface p-4">
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold">{head.title}</h2>
                <p className="text-muted">{head.company}</p>
              </div>
              <div className="text-sm text-muted">
                {head.match_score !== null && <span>Match {Math.round(head.match_score)} · </span>}
                <span>1 of {total}</span>
              </div>
            </header>
            {head.source_url && (
              <a
                href={head.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-accent underline"
              >
                Open the application website
              </a>
            )}
            <Files id={head.posting_id} />
            {confirm ? (
              <div
                className="space-y-2 rounded-md border border-line p-3"
                role="group"
                aria-label="Confirm"
              >
                <p className="text-sm">
                  {confirm.action === 'submitted'
                    ? 'Mark this application as submitted?'
                    : 'Reject this application?'}
                </p>
                {confirm.action === 'declined' && (
                  <label className="block text-sm">
                    <span className="text-muted">Reason (optional)</span>
                    <input
                      value={confirm.note}
                      onChange={(e) => setConfirm({ ...confirm, note: e.target.value })}
                      className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1"
                    />
                  </label>
                )}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => start(confirm.action, confirm.note)}
                    className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg"
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirm(null)}
                    className="rounded-md border border-line px-3 py-1 text-sm"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={pending !== null}
                  onClick={() => setConfirm({ action: 'submitted', note: '' })}
                  className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg disabled:opacity-50"
                >
                  Mark submitted
                </button>
                <button
                  type="button"
                  disabled={pending !== null}
                  onClick={() => setConfirm({ action: 'declined', note: '' })}
                  className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Reject
                </button>
                <button
                  type="button"
                  disabled={pending !== null || act.isPending}
                  onClick={() => act.mutate({ id: head.posting_id, action: 'skip' })}
                  className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Skip
                </button>
              </div>
            )}
            {act.isError && (
              <p role="alert" className="text-sm text-warn-fg">
                Action failed: {act.error.message}
              </p>
            )}
          </article>
        )
      )}
    </section>
  )
}
