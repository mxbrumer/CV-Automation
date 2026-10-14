import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { streamChat, type ArtifactKind, type ChatMessage } from '../api/chat'
import {
  useAcceptProposal,
  useApprove,
  useArtifact,
  useChatHistory,
  useGenerated,
  usePosting,
  useReject,
  useSaveArtifact,
  useTemplate,
} from '../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import DiffView from '../components/DiffView'
import Markdown from '../components/Markdown'
import Toast from '../components/Toast'

const KINDS: { kind: ArtifactKind; label: string }[] = [
  { kind: 'cv', label: 'CV' },
  { kind: 'cover_letter', label: 'Cover letter' },
  { kind: 'recruiter_email', label: 'Recruiter email' },
]

const asStrings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

type Warning = { document: string; claim: string; reason: string }

/** Plan 09 stores the fact-check result as JSON after "fact-check: " in an event note. */
function factCheckWarnings(events: { note?: string | null }[]): Warning[] {
  for (const e of [...events].reverse()) {
    if (!e.note?.startsWith('fact-check: ')) continue
    try {
      const parsed: unknown = JSON.parse(e.note.slice('fact-check: '.length))
      return Array.isArray(parsed) ? (parsed as Warning[]) : []
    } catch {
      return []
    }
  }
  return []
}

function PostingPanel({ id }: { id: number }) {
  const q = usePosting(id)
  if (q.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-warn-fg">
        Could not load the posting.
      </p>
    )
  const p = q.data
  const brief = p.job_brief
  const warnings = factCheckWarnings(p.events)
  const mustHave = asStrings(brief?.must_have)
  const niceToHave = asStrings(brief?.nice_to_have)
  return (
    <div className="space-y-3 text-sm">
      <div>
        <h2 className="font-semibold">{p.title}</h2>
        <p className="text-muted">
          {p.company} · {p.posting_language ?? '?'} · score{' '}
          {p.match_score === null ? '–' : Math.round(p.match_score)}
        </p>
      </div>
      {p.match_rationale && (
        <div>
          <h3 className="font-medium">Why it matched</h3>
          <p className="text-muted">{p.match_rationale}</p>
        </div>
      )}
      {(mustHave.length > 0 || niceToHave.length > 0) && (
        <div>
          <h3 className="font-medium">Requirements</h3>
          <ul className="list-disc pl-5 text-muted">
            {mustHave.map((t) => (
              <li key={`m-${t}`}>Must have: {t}</li>
            ))}
            {niceToHave.map((t) => (
              <li key={`n-${t}`}>Nice to have: {t}</li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h3 className="font-medium">Fact-check</h3>
        {warnings.length === 0 ? (
          <p className="text-muted">No unsupported claims found.</p>
        ) : (
          <ul className="space-y-1">
            {warnings.map((w, i) => (
              <li key={i} className="rounded-md bg-warn-bg px-2 py-1 text-warn-fg">
                <span className="font-medium">{w.document.replace('_', ' ')}:</span> {w.claim}
                <span className="block text-xs">{w.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {p.source_url && (
        <a href={p.source_url} target="_blank" rel="noreferrer" className="text-accent underline">
          Open the posting
        </a>
      )}
    </div>
  )
}

function ChatPanel({ id, kind, current }: { id: number; kind: ArtifactKind; current: string }) {
  const qc = useQueryClient()
  const history = useChatHistory(id, kind)
  const accept = useAcceptProposal(id, kind)
  const [text, setText] = useState('')
  const [streaming, setStreaming] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [discarded, setDiscarded] = useState<number[]>([])
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const messages = history.data ?? []
  const last: ChatMessage | undefined = messages[messages.length - 1]
  const proposal =
    last?.role === 'assistant' &&
    last.proposal &&
    last.proposal !== current &&
    !discarded.includes(last.message_id)
      ? last
      : null

  const send = async () => {
    const message = text.trim()
    if (!message || streaming !== null) return
    setText('')
    setError(null)
    setStreaming('')
    abort.current = new AbortController()
    try {
      let raw = ''
      await streamChat(
        id,
        kind,
        message,
        (d) => {
          raw += d
          setStreaming(raw)
        },
        abort.current.signal,
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The chat failed.')
    } finally {
      setStreaming(null)
      await qc.invalidateQueries({ queryKey: ['chat', id, kind] })
    }
  }

  return (
    <div className="flex h-full flex-col gap-3 text-sm">
      <h2 className="font-semibold">Chat about this document</h2>
      <ul className="max-h-72 space-y-2 overflow-y-auto" aria-label="Chat history">
        {messages.map((m) => (
          <li
            key={m.message_id}
            className={clsx(
              'rounded-md px-2 py-1',
              m.role === 'user' ? 'bg-accent/10' : 'border border-line',
            )}
          >
            <span className="block text-xs text-muted">{m.role === 'user' ? 'You' : 'Model'}</span>
            {m.content}
          </li>
        ))}
        {streaming !== null && (
          <li className="rounded-md border border-line px-2 py-1 text-muted" aria-live="polite">
            Writing… {streaming.length} characters
          </li>
        )}
      </ul>
      {proposal?.proposal && (
        <div className="space-y-2">
          <h3 className="font-medium">Proposed change</h3>
          <DiffView before={current} after={proposal.proposal} />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={accept.isPending}
              onClick={() => accept.mutate(proposal.message_id)}
              className="rounded-md bg-accent px-3 py-1 font-medium text-bg disabled:opacity-50"
            >
              Accept
            </button>
            <button
              type="button"
              onClick={() => setDiscarded((d) => [...d, proposal.message_id])}
              className="rounded-md border border-line px-3 py-1"
            >
              Discard
            </button>
          </div>
        </div>
      )}
      {(error || accept.isError) && (
        <p role="alert" className="text-warn-fg">
          {error ?? `Could not save the change: ${accept.error?.message}`}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
        className="mt-auto space-y-2"
      >
        <label className="block">
          <span className="text-muted">Ask for a change</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="e.g. make the opening shorter"
            className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1"
          />
        </label>
        <button
          type="submit"
          disabled={!text.trim() || streaming !== null}
          className="rounded-md bg-accent px-3 py-1 font-medium text-bg disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  )
}

function DocumentPane({
  id,
  kind,
  versions,
  onProposalBase,
}: {
  id: number
  kind: ArtifactKind
  versions: { version: number; pdf_path?: string | null }[]
  onProposalBase: (markdown: string) => void
}) {
  const [source, setSource] = useState<'generated' | 'template'>('generated')
  const [version, setVersion] = useState<number | undefined>()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const artifact = useArtifact(id, kind, version)
  const template = useTemplate(kind)
  const save = useSaveArtifact(id, kind)
  const latest = versions.length ? Math.max(...versions.map((v) => v.version)) : undefined
  const shown = artifact.data
  const markdown = shown?.markdown
  // The chat edits the latest version; older versions are only for reading.
  const isLatest = version === undefined || version === latest

  useEffect(() => {
    if (markdown !== undefined && isLatest) onProposalBase(markdown)
  }, [markdown, isLatest, onProposalBase])

  const pdf = shown?.pdf_path?.split('/').pop()

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <div
          role="group"
          aria-label="Source"
          className="flex overflow-hidden rounded-md border border-line"
        >
          {(['generated', 'template'] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={source === s}
              onClick={() => {
                setSource(s)
                setEditing(false)
              }}
              className={clsx('px-3 py-1', source === s && 'bg-accent text-bg')}
            >
              {s === 'generated' ? 'Generated' : 'Template'}
            </button>
          ))}
        </div>
        {source === 'generated' && versions.length > 0 && (
          <label className="flex items-center gap-1">
            <span className="text-muted">Version</span>
            <select
              value={version ?? latest}
              onChange={(e) => setVersion(Number(e.target.value))}
              className="rounded-md border border-line bg-surface px-1 py-1"
            >
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                </option>
              ))}
            </select>
          </label>
        )}
        {source === 'generated' && pdf && (
          <a
            href={`/api/v1/files/${id}/${pdf}`}
            target="_blank"
            rel="noreferrer"
            className="text-accent underline"
          >
            Open PDF
          </a>
        )}
        {source === 'generated' && isLatest && markdown !== undefined && (
          <button
            type="button"
            onClick={() => {
              setDraft(markdown)
              setEditing((e) => !e)
            }}
            className="ml-auto rounded-md border border-line px-3 py-1"
          >
            {editing ? 'Cancel edit' : 'Edit'}
          </button>
        )}
      </div>

      {source === 'template' ? (
        template.isPending ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : template.isError ? (
          <p className="text-sm text-muted">
            No template file for this document in DATA_ROOT/profile.
          </p>
        ) : (
          <Markdown source={template.data} />
        )
      ) : artifact.isPending ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : artifact.isError ? (
        <p role="alert" className="text-sm text-warn-fg">
          Could not load the document.
        </p>
      ) : editing ? (
        <div className="space-y-2">
          <textarea
            aria-label="Markdown source"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={22}
            className="w-full rounded-md border border-line bg-bg p-2 font-mono text-xs"
          />
          <button
            type="button"
            disabled={!draft.trim() || save.isPending}
            onClick={() => save.mutate(draft, { onSuccess: () => setEditing(false) })}
            className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg disabled:opacity-50"
          >
            Save as new version
          </button>
          {save.isError && (
            <p role="alert" className="text-sm text-warn-fg">
              Could not save: {save.error.message}
            </p>
          )}
        </div>
      ) : (
        <Markdown source={markdown ?? ''} />
      )}
    </div>
  )
}

export default function ReviewDetail() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const posting = usePosting(id)
  const generated = useGenerated()
  const approve = useApprove()
  const reject = useReject()
  const [kind, setKind] = useState<ArtifactKind>('cv')
  const [viewed, setViewed] = useState<ArtifactKind[]>(['cv'])
  const [current, setCurrent] = useState('')
  const [confirm, setConfirm] = useState<'approve' | 'reject' | null>(null)
  const [note, setNote] = useState('')

  const artifacts = posting.data?.artifacts ?? []
  const present = KINDS.filter((k) => artifacts.some((a) => a.kind === k.kind))
  const allViewed = present.length > 0 && present.every((k) => viewed.includes(k.kind))

  const queue = useMemo(() => generated.data ?? [], [generated.data])
  const index = queue.findIndex((i) => i.posting_id === id)

  const goNext = useCallback(
    (toast?: string) => {
      const next = queue.find((i) => i.posting_id !== id)
      navigate(next ? `/review/${next.posting_id}` : '/review', { state: { toast } })
    },
    [queue, id, navigate],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey)
        return
      if ((e.key === 'j' || e.key === 'k') && index >= 0) {
        const next = queue[index + (e.key === 'j' ? 1 : -1)]
        if (next) navigate(`/review/${next.posting_id}`)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [queue, index, navigate])

  const onProposalBase = useCallback((m: string) => setCurrent(m), [])
  const title = posting.data ? `${posting.data.title}, ${posting.data.company}` : 'this posting'

  if (posting.isError)
    return (
      <p role="alert" className="text-warn-fg">
        Could not load the posting.{' '}
        <Link to="/review" className="underline">
          Back to Review
        </Link>
      </p>
    )

  return (
    <section className="space-y-4">
      <Toast />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/review" className="text-sm text-accent underline">
          ← Review
        </Link>
        <span className="hidden text-xs text-muted sm:inline">j/k previous and next draft</span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!allViewed || posting.data?.status !== 'generated'}
            title={allViewed ? undefined : 'Open every document tab first'}
            onClick={() => setConfirm('approve')}
            className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-bg disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={posting.data?.status !== 'generated'}
            onClick={() => setConfirm('reject')}
            className="rounded-md border border-line px-3 py-1 text-sm disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      </div>

      {confirm && (
        <div
          role="dialog"
          aria-label={`Confirm ${confirm}`}
          className="space-y-2 rounded-lg border border-accent bg-surface p-3 text-sm"
        >
          {confirm === 'approve' ? (
            <p>Approve the drafts for {title}? It moves to the Queue.</p>
          ) : (
            <label className="block">
              <span>Reject {title}. Reason (optional)</span>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1"
              />
            </label>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={approve.isPending || reject.isPending}
              onClick={() =>
                confirm === 'approve'
                  ? approve.mutate(id, {
                      onSuccess: () => goNext(`Approved ${title}. It is in the Queue.`),
                    })
                  : reject.mutate({ id, note }, { onSuccess: () => goNext(`Rejected ${title}.`) })
              }
              className="rounded-md bg-accent px-3 py-1 font-medium text-bg disabled:opacity-50"
            >
              {confirm === 'approve' ? 'Yes, approve' : 'Yes, reject'}
            </button>
            <button
              type="button"
              onClick={() => setConfirm(null)}
              className="rounded-md border border-line px-3 py-1"
            >
              Cancel
            </button>
          </div>
          {(approve.isError || reject.isError) && (
            <p role="alert" className="text-warn-fg">
              Could not save the decision: {(approve.error ?? reject.error)?.message}
            </p>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)_20rem]">
        <aside className="rounded-lg border border-line bg-surface p-3">
          <PostingPanel id={id} />
        </aside>
        <div className="min-w-0 rounded-lg border border-line bg-surface p-3">
          <div
            role="tablist"
            aria-label="Documents"
            className="mb-3 flex gap-1 border-b border-line"
          >
            {KINDS.map((k) => (
              <button
                key={k.kind}
                role="tab"
                type="button"
                aria-selected={kind === k.kind}
                onClick={() => {
                  setKind(k.kind)
                  setViewed((v) => (v.includes(k.kind) ? v : [...v, k.kind]))
                }}
                className={clsx(
                  'border-b-2 px-3 py-2 text-sm font-medium',
                  kind === k.kind ? 'border-accent' : 'border-transparent text-muted',
                )}
              >
                {k.label}
              </button>
            ))}
          </div>
          <DocumentPane
            key={kind}
            id={id}
            kind={kind}
            versions={artifacts.filter((a) => a.kind === kind)}
            onProposalBase={onProposalBase}
          />
        </div>
        <aside className="rounded-lg border border-line bg-surface p-3">
          <ChatPanel key={kind} id={id} kind={kind} current={current} />
        </aside>
      </div>
    </section>
  )
}
