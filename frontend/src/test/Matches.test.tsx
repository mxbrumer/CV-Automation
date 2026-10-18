import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const summary = (id: number, score: number, language = 'en') => ({
  posting_id: id,
  company: `Company ${id}`,
  title: `Title ${id}`,
  status: 'awaiting_match_review',
  posting_language: language,
  match_score: score,
  queue_position: null,
  source_url: `https://example.com/${id}`,
  created_at: '2026-10-14T08:00:00Z',
  updated_at: '2026-10-14T08:00:00Z',
})

const detail = (id: number, language: string) => ({
  ...summary(id, 80, language),
  artifact_folder: null,
  artifacts: [],
  embedding_score: 75,
  rubric_score: 83,
  events: [],
  host_folder: null,
  job_brief: {
    must_have: ['Python'],
    nice_to_have: ['dbt'],
    location: 'Aarhus',
    relocation_ok: true,
    required_languages: language === 'da' ? ['da', 'en'] : ['en'],
    danish_required: language === 'da',
  },
  match_rationale: 'Strong overlap on Python.',
  posting_text: 'Full posting text',
  recruiter_email: null,
  recruiter_name: null,
  recruiter_phone: null,
})

function mockApi(opts: { empty?: boolean } = {}) {
  const decisions: { id: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      const decision = url.pathname.match(/postings\/(\d+)\/match-decision/)
      if (decision) {
        decisions.push({ id: decision[1], body: await input.json() })
        return json(summary(Number(decision[1]), 80))
      }
      const one = url.pathname.match(/postings\/(\d+)$/)
      if (one) return json(detail(Number(one[1]), one[1] === '2' ? 'da' : 'en'))
      if (url.pathname === '/api/v1/postings') {
        const items = opts.empty ? [] : [summary(1, 90), summary(2, 70, 'da')]
        return json({ items, total: items.length, page: 1, page_size: 100 })
      }
      if (url.pathname === '/api/v1/stats')
        return json({ reviewed: 0, awaiting_match_review: 2, good_match: 0 })
      if (url.pathname === '/health') return json({ status: 'ok' })
      return json({}, 404)
    }),
  )
  return decisions
}

function renderMatches() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/matches']}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Matches tab (gate 1)', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

  it('approves after the undo window and says drafts are generated', async () => {
    const decisions = mockApi()
    renderMatches()
    await user().click((await screen.findAllByRole('button', { name: 'Approve' }))[0])
    expect(await screen.findByText(/Drafts are being generated/)).toBeInTheDocument()
    expect(decisions).toHaveLength(0)
    await act(() => vi.advanceTimersByTimeAsync(5100))
    expect(decisions).toEqual([{ id: '1', body: { decision: 'approve', note: null } }])
  })

  it('declines with the typed reason', async () => {
    const decisions = mockApi()
    renderMatches()
    const u = user()
    await u.click(await screen.findByText('Title 1'))
    await u.type(await screen.findByLabelText(/Decline reason/), 'too senior')
    await u.click(screen.getAllByRole('button', { name: 'Decline' })[0])
    await act(() => vi.advanceTimersByTimeAsync(5100))
    expect(decisions).toEqual([{ id: '1', body: { decision: 'decline', note: 'too senior' } }])
  })

  it('undo cancels the decision', async () => {
    const decisions = mockApi()
    renderMatches()
    const u = user()
    await u.click((await screen.findAllByRole('button', { name: 'Approve' }))[0])
    await u.click(await screen.findByRole('button', { name: 'Undo' }))
    await act(() => vi.advanceTimersByTimeAsync(6000))
    expect(decisions).toHaveLength(0)
    expect(screen.getByText('Title 1')).toBeInTheDocument()
  })

  it('supports j and a from the keyboard', async () => {
    const decisions = mockApi()
    renderMatches()
    const u = user()
    await screen.findByText('Title 1')
    await u.keyboard('jja')
    await act(() => vi.advanceTimersByTimeAsync(5100))
    expect(decisions.map((d) => d.id)).toEqual(['2'])
  })

  it('shows flags and the Danish-required chip', async () => {
    mockApi()
    renderMatches()
    await user().click(await screen.findByText('Title 2'))
    expect(await screen.findByText('Danish required')).toBeInTheDocument()
    expect(screen.getByText('location: Aarhus')).toBeInTheDocument()
    expect(screen.getByText('Strong overlap on Python.')).toBeInTheDocument()
    expect(screen.getByText('Must have: Python')).toBeInTheDocument()
  })

  it('shows an empty state linking to Add job', async () => {
    mockApi({ empty: true })
    renderMatches()
    expect(await screen.findByText(/Nothing to confirm/)).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(within(main).getByRole('link', { name: 'Add job' })).toHaveAttribute('href', '/add')
  })
})
