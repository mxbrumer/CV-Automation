import clsx from 'clsx'
import type { PostingStatus } from '../api/client'
import type { components } from '../api/schema'

type PostingDetail = components['schemas']['PostingDetail']

export const STATUS_LABEL: Record<PostingStatus, string> = {
  new: 'new',
  analyzed: 'analyzed',
  low_match: 'low match',
  awaiting_match_review: 'awaiting match review',
  match_declined: 'match declined',
  matched: 'matched',
  generating: 'generating',
  generated: 'generated',
  approved: 'approved',
  submitted: 'submitted',
  declined: 'declined',
  duplicate: 'duplicate',
  needs_manual_text: 'needs manual text',
  unsupported_language: 'unsupported language',
  error: 'error',
}

export const asStrings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

export function Chip({
  children,
  tone = 'plain',
}: {
  children: React.ReactNode
  tone?: 'plain' | 'warn'
}) {
  return (
    <span
      className={clsx(
        'rounded-full border px-2 py-0.5 text-xs',
        tone === 'warn' ? 'border-warn-fg bg-warn-bg text-warn-fg' : 'border-line text-muted',
      )}
    >
      {children}
    </span>
  )
}

/** D10 flags: shown, never scored. */
export function Flags({
  brief,
  language,
}: {
  brief: Record<string, unknown> | null
  language: string | null
}) {
  const b = brief ?? {}
  const langs = asStrings(b.required_languages)
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Flags">
      {language && <Chip tone={language === 'da' ? 'warn' : 'plain'}>posting: {language}</Chip>}
      {b.danish_required === true && <Chip tone="warn">Danish required</Chip>}
      {b.danish_required === false && <Chip>Danish not required</Chip>}
      {langs.length > 0 && <Chip>languages: {langs.join(', ')}</Chip>}
      {typeof b.location === 'string' && <Chip>location: {b.location}</Chip>}
      {b.relocation_ok === true && <Chip>relocation OK</Chip>}
      {b.relocation_ok === false && <Chip tone="warn">no relocation</Chip>}
    </div>
  )
}

/** Analysis of one posting: flags, scores, rationale, requirements, link and full text. */
export default function PostingInfo({ posting: p }: { posting: PostingDetail }) {
  const brief = p.job_brief
  const mustHave = asStrings(brief?.must_have)
  const niceToHave = asStrings(brief?.nice_to_have)
  return (
    <div className="space-y-3 text-sm">
      <Flags brief={brief} language={p.posting_language} />
      <dl className="grid grid-cols-2 gap-2 sm:max-w-sm">
        <div className="rounded-md border border-line p-2">
          <dt className="text-muted">Embedding</dt>
          <dd className="text-lg tabular-nums">{p.embedding_score ?? '–'}</dd>
        </div>
        <div className="rounded-md border border-line p-2">
          <dt className="text-muted">Rubric</dt>
          <dd className="text-lg tabular-nums">{p.rubric_score ?? '–'}</dd>
        </div>
      </dl>
      {p.match_rationale && (
        <div>
          <h3 className="font-medium">Rationale</h3>
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
      {p.source_url && (
        <a href={p.source_url} target="_blank" rel="noreferrer" className="text-accent underline">
          Open the posting
        </a>
      )}
      {p.posting_text && (
        <details>
          <summary className="cursor-pointer text-muted">Posting text</summary>
          <p className="mt-2 whitespace-pre-wrap">{p.posting_text}</p>
        </details>
      )}
    </div>
  )
}
