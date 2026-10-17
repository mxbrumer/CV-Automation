import clsx from 'clsx'
import { NavLink, Outlet, useMatch } from 'react-router'
import { useHealth, useStats, useStatusCount } from '../api/hooks'

function Tab({
  to,
  label,
  count,
  end,
}: {
  to: string
  label: string
  count?: number
  end?: boolean
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium',
          isActive ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg',
        )
      }
    >
      {label}
      {count ? (
        <span
          aria-label={`${count} waiting`}
          className="rounded-full bg-accent px-1.5 text-xs font-semibold text-bg"
        >
          {count}
        </span>
      ) : null}
    </NavLink>
  )
}

export default function Layout() {
  const health = useHealth()
  const stats = useStats()
  const generated = useStatusCount('generated')
  const approved = useStatusCount('approved')
  const wide = useMatch('/review/:id') !== null // three panes need the room

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <nav aria-label="Main" className="mx-auto flex max-w-5xl overflow-x-auto px-2">
          <Tab to="/" label="Home" end />
          <Tab to="/add" label="Add job" />
          <Tab to="/matches" label="Matches" count={stats.data?.awaiting_match_review} />
          <Tab to="/review" label="Review" count={generated.data} />
          <Tab to="/queue" label="Queue" count={approved.data} />
        </nav>
      </header>
      {health.isError && (
        <div role="alert" className="bg-warn-bg px-4 py-2 text-center text-sm text-warn-fg">
          Cannot reach the backend. Start the stack with <code>scripts/dev.ps1 up</code> and check
          the API key in <code>frontend/.env.local</code>.
        </div>
      )}
      <main className={clsx('mx-auto px-4 py-6', wide ? 'max-w-7xl' : 'max-w-5xl')}>
        <Outlet />
      </main>
    </div>
  )
}
