import { diffWords } from 'diff'

/** Word-level diff of the current document against a proposal. */
export default function DiffView({ before, after }: { before: string; after: string }) {
  const parts = diffWords(before, after)
  return (
    <pre
      aria-label="Proposed changes"
      className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-bg p-2 text-xs"
    >
      {parts.map((p, i) =>
        p.added ? (
          <ins key={i} className="bg-green-500/25 no-underline">
            {p.value}
          </ins>
        ) : p.removed ? (
          <del key={i} className="bg-red-500/25">
            {p.value}
          </del>
        ) : (
          <span key={i}>{p.value}</span>
        ),
      )}
    </pre>
  )
}
