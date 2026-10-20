import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const summary = (id: number, status: string, over: Record<string, unknown> = {}) => ({
  posting_id: id,
  company: 'Novo Nordisk A/S',
  title: 'Data Engineer',
  status,
  posting_language: null,
  match_score: null,
  queue_position: null,
  source_url: 'https://careers.example.com/42',
  created_at: '2026-10-17T08:00:00Z',
  updated_at: '2026-10-17T08:00:00Z',
  ...over,
})

const LONG = 'We are looking for a data engineer with Python and SQL. '.repeat(20)

type Reply = { status: number; body: unknown }

/** `replies` answer successive POST /postings calls; the bodies sent are collected. */
function mockApi(replies: Reply[]) {
  const sent: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      if (url.pathname === '/health') return json({ status: 'ok' })
      if (url.pathname === '/api/v1/stats')
        return json({ reviewed: 0, awaiting_match_review: 0, good_match: 0 })
      if (url.pathname === '/api/v1/postings' && input.method === 'POST') {
        sent.push((await input.json()) as Record<string, unknown>)
        const reply = replies.shift() ?? { status: 500, body: { detail: 'unexpected' } }
        return json(reply.body, reply.status)
      }
      if (url.pathname === '/api/v1/postings')
        return json({ items: [], total: 0, page: 1, page_size: 1 })
      return json({}, 404)
    }),
  )
  return sent
}

function renderAt(path = '/add') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function fill(text = LONG, url = 'https://careers.example.com/42') {
  await userEvent.type(await screen.findByLabelText('Company'), 'Novo Nordisk A/S')
  await userEvent.type(screen.getByLabelText('Job title'), 'Data Engineer')
  if (url) await userEvent.type(screen.getByLabelText('Application URL (optional)'), url)
  await userEvent.click(screen.getByLabelText(/Job description/))
  await userEvent.paste(text)
}

const submit = () => userEvent.click(screen.getByRole('button', { name: 'Add job' }))

describe('Add job', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is a tab right after Home', async () => {
    mockApi([])
    renderAt('/')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    const tabs = within(nav)
      .getAllByRole('link')
      .map((a) => a.textContent)
    expect(tabs).toEqual(['Home', 'Add job', 'Matches', 'Review', 'Queue', 'Jobs'])
  })

  it('needs company, title and description before it can be sent', async () => {
    mockApi([])
    renderAt()
    expect(await screen.findByRole('button', { name: 'Add job' })).toBeDisabled()
    await fill(LONG, '')
    expect(screen.getByRole('button', { name: 'Add job' })).toBeEnabled()
  })

  it('counts words and warns under 150 without blocking', async () => {
    const sent = mockApi([{ status: 201, body: summary(7, 'new') }])
    renderAt()
    await fill('Short teaser text only.')
    expect(screen.getByTestId('word-count')).toHaveTextContent('4 words')
    expect(screen.getByText(/Only 4 words/)).toBeInTheDocument()
    await submit()
    expect(await screen.findByRole('status')).toHaveTextContent('Its analysis has started')
    expect(sent).toHaveLength(1)
  })

  it('does not warn for a full description', async () => {
    mockApi([])
    renderAt()
    await fill()
    expect(screen.getByTestId('word-count')).toHaveTextContent('220 words')
    expect(screen.queryByText(/Only \d+ words/)).not.toBeInTheDocument()
  })

  it('adds the job, shows a toast and clears the form', async () => {
    const sent = mockApi([{ status: 201, body: summary(7, 'new') }])
    renderAt()
    await fill()
    await submit()
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Added “Data Engineer” at Novo Nordisk A/S',
    )
    expect(sent[0]).toEqual({
      company: 'Novo Nordisk A/S',
      title: 'Data Engineer',
      url: 'https://careers.example.com/42',
      text: LONG,
      force: false,
    })
    expect(screen.getByLabelText('Company')).toHaveValue('')
    expect(screen.getByLabelText(/Job description/)).toHaveValue('')
  })

  it('sends no URL when the field is empty', async () => {
    const sent = mockApi([{ status: 201, body: summary(7, 'new', { source_url: null }) }])
    renderAt()
    await fill(LONG, '')
    await submit()
    await screen.findByRole('status')
    expect(sent[0].url).toBeNull()
  })

  it('shows a similar job with Add anyway, which resends with force', async () => {
    const match = summary(3, 'awaiting_match_review')
    const sent = mockApi([
      { status: 409, body: { reason: 'similar', posting: match } },
      { status: 201, body: summary(8, 'new') },
    ])
    renderAt()
    await fill()
    await submit()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('A similar job is already stored')
    expect(alert).toHaveTextContent('awaiting match review')
    expect(within(alert).getByRole('link')).toHaveAttribute('href', '/matches')
    await userEvent.click(within(alert).getByRole('button', { name: 'Add anyway' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Its analysis has started')
    expect(sent.map((b) => b.force)).toEqual([false, true])
  })

  it('Cancel dismisses the similar job and keeps the form', async () => {
    const sent = mockApi([
      { status: 409, body: { reason: 'similar', posting: summary(3, 'low_match') } },
    ])
    renderAt()
    await fill()
    await submit()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Company')).toHaveValue('Novo Nordisk A/S')
    expect(sent).toHaveLength(1)
  })

  it('refuses the same URL and shows only the link to the stored posting', async () => {
    mockApi([{ status: 409, body: { reason: 'same_url', posting: summary(5, 'generated') } }])
    renderAt()
    await fill()
    await submit()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This application URL is already stored')
    expect(within(alert).getByRole('link')).toHaveAttribute('href', '/review/5')
    expect(screen.queryByRole('button', { name: 'Add anyway' })).not.toBeInTheDocument()
  })

  it('shows other errors', async () => {
    mockApi([{ status: 500, body: { detail: 'boom' } }])
    renderAt()
    await fill()
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not add the job')
  })
})
