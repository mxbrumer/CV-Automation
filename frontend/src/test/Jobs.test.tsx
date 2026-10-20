import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const summary = (id: number, status: string, score: number | null) => ({
  posting_id: id,
  company: `Company ${id}`,
  title: `Title ${id}`,
  status,
  posting_language: 'en',
  match_score: score,
  queue_position: null,
  source_url: `https://example.com/${id}`,
  created_at: '2026-10-14T08:00:00Z',
  updated_at: '2026-10-15T08:00:00Z',
})

const detail = (id: number, status: string) => ({
  ...summary(id, status, 72.6),
  artifact_folder: 'company-3',
  host_folder: 'C:\\dev\\JobSearchData\\applications\\company-3',
  artifacts: [
    {
      artifact_id: 9,
      kind: 'cv',
      version: 1,
      approved: false,
      md_path: 'company-3/cv.md',
      pdf_path: 'company-3/cv.pdf',
      created_at: '2026-10-15T08:00:00Z',
    },
  ],
  embedding_score: 70,
  rubric_score: 75,
  events: [
    {
      event_id: 1,
      from_status: 'new',
      to_status: 'analyzed',
      actor: 'langflow',
      note: null,
      at: '2026-10-14T08:01:00Z',
    },
    {
      event_id: 2,
      from_status: 'generating',
      to_status: 'generated',
      actor: 'langflow',
      note: 'fact-check: []',
      at: '2026-10-15T08:00:00Z',
    },
  ],
  job_brief: { must_have: ['Python'], nice_to_have: [], location: 'Aarhus' },
  match_rationale: 'Strong overlap on Python.',
  posting_text: 'Full posting text',
  recruiter_email: 'jane@example.com',
  recruiter_name: 'Jane Doe',
  recruiter_phone: null,
})

/** 30 postings; the list endpoint pages, filters by status and searches the title. */
function mockApi() {
  const all = Array.from({ length: 30 }, (_, i) =>
    summary(30 - i, i % 3 === 0 ? 'low_match' : 'generated', 90 - i),
  )
  const lists: URLSearchParams[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      const one = url.pathname.match(/postings\/(\d+)$/)
      if (one) return json(detail(Number(one[1]), 'generated'))
      if (url.pathname === '/api/v1/postings') {
        const p = url.searchParams
        if (p.get('page_size') !== '1') lists.push(p) // skip the tab badge counts
        const size = Number(p.get('page_size') ?? 25)
        const page = Number(p.get('page') ?? 1)
        const items = all
          .filter((x) => !p.get('status') || x.status === p.get('status'))
          .filter((x) => !p.get('q') || x.title.includes(p.get('q')!))
        return json({
          items: items.slice((page - 1) * size, page * size),
          total: items.length,
          page,
          page_size: size,
        })
      }
      if (url.pathname === '/api/v1/stats')
        return json({ reviewed: 0, awaiting_match_review: 0, good_match: 0 })
      return json({}, 404)
    }),
  )
  return lists
}

function renderApp(path = '/jobs') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const rows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1)

describe('Jobs tab', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists every posting, newest first, one page at a time', async () => {
    const lists = mockApi()
    renderApp()
    expect(await screen.findByText('Title 30')).toBeInTheDocument()
    expect(rows()).toHaveLength(25)
    expect(screen.getByText('1–25 of 30')).toBeInTheDocument()
    expect(lists.at(-1)?.get('sort')).toBe('recent')
    expect(lists.at(-1)?.has('status')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('26–30 of 30')).toBeInTheDocument()
    expect(rows()).toHaveLength(5)
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('filters by status and search text', async () => {
    const lists = mockApi()
    renderApp()
    await screen.findByText('Title 30')
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'low match')
    await waitFor(() => expect(screen.getByText('1–10 of 10')).toBeInTheDocument())
    expect(lists.at(-1)?.get('status')).toBe('low_match')

    await userEvent.type(screen.getByLabelText('Search title or company'), 'nothing')
    expect(await screen.findByText('No jobs match these filters.')).toBeInTheDocument()
  })

  it('opens a posting with its analysis, documents and history, and goes back', async () => {
    mockApi()
    renderApp('/jobs?status=generated')
    await userEvent.click(await screen.findByRole('link', { name: 'Title 29' }))
    expect(await screen.findByRole('heading', { name: 'Title 29' })).toBeInTheDocument()
    expect(screen.getByText('Strong overlap on Python.')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe · jane@example.com')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute(
      'href',
      '/api/v1/files/29/cv.pdf',
    )
    expect(screen.getByText('generating → generated')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review the drafts' })).toHaveAttribute(
      'href',
      '/review/29',
    )

    await userEvent.click(screen.getByRole('link', { name: '← All jobs' }))
    expect(await screen.findByLabelText('Status')).toHaveValue('generated')
  })
})
