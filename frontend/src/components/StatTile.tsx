export default function StatTile({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums">{value ?? '–'}</div>
    </div>
  )
}
