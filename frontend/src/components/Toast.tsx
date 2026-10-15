import { useLocation } from 'react-router'

/** A one-line message handed over through router state (`navigate(to, { state: { toast } })`). */
export default function Toast() {
  const toast = (useLocation().state as { toast?: string } | null)?.toast
  if (!toast) return null
  return (
    <p
      role="status"
      className="rounded-md border border-line bg-surface px-3 py-2 text-sm"
      aria-live="polite"
    >
      {toast}
    </p>
  )
}
