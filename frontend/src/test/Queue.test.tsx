import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const summary = (id: number) => ({
  posting_id: id,
  company: `Company ${id}`,
  title: `Title ${id}`,
  status: 'approved',
  posting_language: 'en',
  match_score: 80,
  queue_position: id,
  source_url: `https://example.com/${id}`,
  created_at: '2026-10-14T08:00:00Z',
  updated_at: '2026-10-14T08:00:00Z',
})

const artifact = (kind: string, pdf: boolean) => ({
  artifact_id: kind.length,
  kind,
  version: 2,
  md_path: `x/${kind}_v2.md`,
  pdf_path: pdf ? `x/${kind}_v2.pdf` : null,
  approved: true,
  created_at: 'x',
})

function mockApi(items: number[]) {
  const actions: { id: string; body: { action: string; note: string | null } }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      const path = url.pathname
      const action = path.match(/queue\/(\d+)\/action/)
      if (action) {
        actions.push({ id: action[1], body: await input.json() })
        return json(summary(Number(action[1])))
      }
      if (path === '/api/v1/postings') {
        const list = url.searchParams.get('status') === 'approved' ? items : []
        return json({
          items: list.map(summary),
          total: list.length,
          page: 1,
          page_size: 100,
        })
      }
      if (path.endsWith('/artifacts/recruiter_email'))
        return json({
          ...artifact('recruiter_email', false),
          markdown: 'Subject: Data engineer application\n\nHello Anna, I would like to apply.',
        })
      const one = path.match(/postings\/(\d+)$/)
      if (one)
        return json({
          ...summary(Number(one[1])),
          artifact_folder: 'x',
          host_folder: 'C:\\dev\\JobSearchData\\applications\\acme',
          artifacts: [artifact('cv', true), artifact('cover_letter', true)],
          embedding_score: 70,
          rubric_score: 80,
          match_rationale: null,
          posting_text: 'text',
          recruiter_email: 'anna@example.com',
          recruiter_name: 'Anna',
          recruiter_phone: null,
          job_brief: null,
          events: [],
        })
      return json({}, 404)
    }),
  )
  return actions
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Queue', () => {
  it('shows the head posting, its files and the recruiter email', async () => {
    mockApi([1, 2, 3])
    renderAt('/queue')
    expect(await screen.findByText('Title 1')).toBeInTheDocument()
    expect(screen.getByText('1 of 3', { exact: false })).toBeInTheDocument()
    expect(
      await screen.findByText('C:\\dev\\JobSearchData\\applications\\acme'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /CV \(v2/ })).toHaveAttribute(
      'href',
      '/api/v1/files/1/cv_v2.pdf',
    )
    expect(await screen.findByText('Data engineer application')).toBeInTheDocument()
    expect(screen.getByText('anna@example.com')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the application website' })).toHaveAttribute(
      'target',
      '_blank',
    )
  })

  it('skips without a confirmation', async () => {
    const actions = mockApi([1, 2])
    renderAt('/queue')
    await screen.findByText('Title 1')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Skip' }))
    await vi.waitFor(() =>
      expect(actions).toEqual([{ id: '1', body: { action: 'skip', note: null } }]),
    )
  })

  it('submits after a confirmation and the 5 s undo window', async () => {
    const actions = mockApi([1])
    renderAt('/queue')
    const u = userEvent.setup()
    await screen.findByText('Title 1')
    await u.click(screen.getByRole('button', { name: 'Mark submitted' }))
    expect(actions).toHaveLength(0)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await u.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(actions).toHaveLength(0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100)
    })
    await vi.waitFor(() =>
      expect(actions).toEqual([{ id: '1', body: { action: 'submitted', note: null } }]),
    )
  })

  it('rejects with a reason, and undo cancels the call', async () => {
    const actions = mockApi([1])
    renderAt('/queue')
    const u = userEvent.setup()
    await screen.findByText('Title 1')
    await u.click(screen.getByRole('button', { name: 'Reject' }))
    await u.type(screen.getByLabelText('Reason (optional)'), 'too far')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await u.click(screen.getByRole('button', { name: 'Confirm' }))
    await u.click(screen.getByRole('button', { name: 'Undo' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(actions).toHaveLength(0)

    await u.click(screen.getByRole('button', { name: 'Reject' }))
    await u.type(screen.getByLabelText('Reason (optional)'), 'too far')
    await u.click(screen.getByRole('button', { name: 'Confirm' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100)
    })
    await vi.waitFor(() =>
      expect(actions).toEqual([{ id: '1', body: { action: 'declined', note: 'too far' } }]),
    )
  })

  it('shows the empty state with a link to Review', async () => {
    mockApi([])
    renderAt('/queue')
    expect(await screen.findByText(/The queue is empty/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review tab' })).toHaveAttribute('href', '/review')
  })
})
