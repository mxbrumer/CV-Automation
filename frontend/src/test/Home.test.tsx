import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const posting = (id: number, status: string, score: number | null) => ({
  posting_id: id,
  company: `Company ${id}`,
  title: `Title ${id}`,
  status,
  posting_language: 'en',
  match_score: score,
  queue_position: null,
  source_url: null,
  created_at: '2026-10-14T08:00:00Z',
  updated_at: '2026-10-14T08:00:00Z',
})

const totals: Record<string, number> = { generated: 4, approved: 2, submitted: 7 }

function mockApi(opts: { down?: boolean; empty?: boolean } = {}) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const req = typeof input === 'string' ? new Request(`http://x${input}`) : input
      const url = new URL(req.url)
      calls.push(`${req.method} ${url.pathname}`)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      if (opts.down) return json({ detail: 'down' }, 502)
      if (url.pathname === '/health') return json({ status: 'ok' })
      if (url.pathname === '/api/v1/stats')
        return json({ reviewed: 42, awaiting_match_review: 3, good_match: 11 })
      if (url.pathname === '/api/v1/workflow/last-run')
        return json({
          run_id: 5,
          phase: 'analysis',
          status: 'succeeded',
          started_at: '2026-10-14T08:00:00Z',
          finished_at: '2026-10-14T08:02:00Z',
          error: null,
        })
      if (url.pathname === '/api/v1/workflow/process-pending')
        return json({ status: 'queued' }, 202)
      if (url.pathname === '/api/v1/postings') {
        const status = url.searchParams.get('status')
        if (status) return json({ items: [], total: totals[status] ?? 0, page: 1, page_size: 1 })
        const items = opts.empty ? [] : [posting(2, 'matched', 81.4), posting(1, 'low_match', null)]
        return json({ items, total: items.length, page: 1, page_size: 10 })
      }
      return json({}, 404)
    }),
  )
  return calls
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Home dashboard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the three counts, the badges and the latest postings', async () => {
    mockApi()
    renderApp()
    const tile = async (label: string) => (await screen.findByText(label)).parentElement!
    await waitFor(async () => expect(await tile('Job postings reviewed')).toHaveTextContent('42'))
    await waitFor(async () => expect(await tile('Good matches')).toHaveTextContent('11'))
    await waitFor(async () => expect(await tile('Applications submitted')).toHaveTextContent('7'))
    expect(await screen.findByLabelText('3 waiting')).toBeInTheDocument() // Matches
    expect(await screen.findByLabelText('4 waiting')).toBeInTheDocument() // Review
    expect(await screen.findByLabelText('2 waiting')).toBeInTheDocument() // Queue
    expect(await screen.findByText('Title 2')).toBeInTheDocument()
    expect(screen.getByText('81')).toBeInTheDocument()
    expect(screen.getByText('low match')).toBeInTheDocument()
    expect(await screen.findByText(/analysis succeeded/)).toBeInTheDocument()
  })

  it('shows an empty state without postings', async () => {
    mockApi({ empty: true })
    renderApp()
    expect(await screen.findByText(/No postings yet/)).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(within(main).getByRole('link', { name: 'Add job' })).toHaveAttribute('href', '/add')
  })

  it('shows a banner when the backend is down', async () => {
    mockApi({ down: true })
    renderApp()
    expect(await screen.findByText(/Cannot reach the backend/)).toBeInTheDocument()
  })

  it('processes pending postings from the button', async () => {
    const calls = mockApi()
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Process pending' }))
    expect(await screen.findByText('Processing queued.')).toBeInTheDocument()
    expect(calls).toContain('POST /api/v1/workflow/process-pending')
  })
})
