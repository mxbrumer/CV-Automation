import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const summary = (id: number, status = 'generated') => ({
  posting_id: id,
  company: `Company ${id}`,
  title: `Title ${id}`,
  status,
  posting_language: 'en',
  match_score: 80 - id,
  queue_position: null,
  source_url: `https://example.com/${id}`,
  created_at: '2026-10-14T08:00:00Z',
  updated_at: '2026-10-14T08:00:00Z',
})

const artifact = (kind: string, version: number) => ({
  artifact_id: version,
  kind,
  version,
  md_path: `x/${kind}_v${version}.md`,
  pdf_path: kind === 'recruiter_email' ? null : `x/${kind}_v${version}.pdf`,
  approved: false,
  created_at: '2026-10-14T08:00:00Z',
})

const KINDS = ['cv', 'cover_letter', 'recruiter_email']

function sse(events: [string, unknown][]) {
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')
  return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
}

type Calls = { accepted: unknown[]; approved: string[]; rejected: unknown[]; chats: unknown[] }

function mockApi() {
  const calls: Calls = { accepted: [], approved: [], rejected: [], chats: [] }
  let version = 1
  let chat: unknown[] = []
  let nextId = 10
  const proposal = 'Hello brave new world'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const path = url.pathname
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        })
      if (path === '/health') return json({ status: 'ok' })
      if (path === '/api/v1/stats')
        return json({ reviewed: 0, awaiting_match_review: 0, good_match: 0 })
      if (path === '/api/v1/postings') {
        const items = url.searchParams.get('status') === 'generated' ? [summary(1), summary(2)] : []
        return json({ items, total: items.length, page: 1, page_size: 100 })
      }
      const accept = path.match(/postings\/(\d+)\/artifacts\/(\w+)\/chat\/accept/)
      if (accept) {
        calls.accepted.push(await input.json())
        version = 2
        return json({ ...artifact(accept[2], 2), markdown: proposal })
      }
      const chatRoute = path.match(/postings\/(\d+)\/artifacts\/(\w+)\/chat$/)
      if (chatRoute && input.method === 'POST') {
        const sent = (await input.json()) as { message: string }
        calls.chats.push(sent)
        const user = { message_id: nextId++, role: 'user', content: sent.message, created_at: 'x' }
        const message = {
          message_id: nextId++,
          role: 'assistant',
          content: 'Made it livelier.',
          proposal,
          created_at: 'x',
        }
        chat = [user, message]
        return sse([
          ['delta', { text: 'EXPLANATION: ' }],
          ['done', { message }],
        ])
      }
      if (chatRoute) return json(chat)
      const art = path.match(/postings\/(\d+)\/artifacts\/(\w+)$/)
      if (art)
        return json({
          ...artifact(art[2], version),
          markdown: version === 1 ? 'Hello world' : proposal,
        })
      if (path.endsWith('/approve')) {
        calls.approved.push(path)
        return json(summary(1, 'approved'))
      }
      if (path.endsWith('/reject')) {
        calls.rejected.push(await input.json())
        return json({ posting_id: 1, status: 'declined' })
      }
      if (path.startsWith('/api/v1/tools/profile')) return json({ detail: 'nope' }, 404)
      const one = path.match(/postings\/(\d+)$/)
      if (one)
        return json({
          ...summary(Number(one[1])),
          artifact_folder: 'x',
          host_folder: null,
          artifacts: KINDS.map((k) => artifact(k, version)),
          embedding_score: 70,
          rubric_score: 80,
          match_rationale: 'Good fit.',
          posting_text: 'text',
          recruiter_email: null,
          recruiter_name: null,
          recruiter_phone: null,
          job_brief: { must_have: ['Python'] },
          events: [
            {
              event_id: 1,
              from_status: 'generating',
              to_status: 'generated',
              actor: 'agent',
              at: 'x',
              note:
                'fact-check: ' +
                JSON.stringify([
                  { document: 'cv', claim: 'Led a team of 50', reason: 'not in cv.md' },
                ]),
            },
          ],
        })
      return json({}, 404)
    }),
  )
  return calls
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

afterEach(() => vi.unstubAllGlobals())

describe('Review list', () => {
  it('lists generated drafts with links to the detail page', async () => {
    mockApi()
    renderAt('/review')
    const link = await screen.findByRole('link', { name: 'Title 1' })
    expect(link).toHaveAttribute('href', '/review/1')
    expect(screen.getByText('Company 2')).toBeInTheDocument()
  })
})

describe('Review detail', () => {
  it('shows the fact-check warning and the document', async () => {
    mockApi()
    renderAt('/review/1')
    expect(await screen.findByText(/Led a team of 50/)).toBeInTheDocument()
    expect(await screen.findByText('Hello world')).toBeInTheDocument()
  })

  it('proposes a diff, discards it, and accepts it into a new version', async () => {
    const calls = mockApi()
    renderAt('/review/1')
    const u = userEvent.setup()
    await screen.findByText('Hello world')
    await u.type(screen.getByLabelText('Ask for a change'), 'livelier please')
    await u.click(screen.getByRole('button', { name: 'Send' }))

    const diff = await screen.findByLabelText('Proposed changes')
    expect(calls.chats).toEqual([{ message: 'livelier please' }])
    expect(within(diff).getByText('brave new')).toBeInTheDocument() // the added words

    await u.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.queryByLabelText('Proposed changes')).not.toBeInTheDocument()
    expect(calls.accepted).toHaveLength(0)

    // a new turn brings the proposal back; accept it
    await u.type(screen.getByLabelText('Ask for a change'), 'again')
    await u.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByLabelText('Proposed changes')
    await u.click(screen.getByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(calls.accepted).toEqual([{ message_id: 13 }]))
    expect(await screen.findByText('Hello brave new world')).toBeInTheDocument()
    expect(screen.queryByLabelText('Proposed changes')).not.toBeInTheDocument()
  })

  it('needs every document tab opened before Approve, then approves and moves on', async () => {
    const calls = mockApi()
    renderAt('/review/1')
    const u = userEvent.setup()
    const approve = await screen.findByRole('button', { name: 'Approve' })
    await waitFor(() => expect(approve).toBeDisabled())
    await u.click(screen.getByRole('tab', { name: 'Cover letter' }))
    await u.click(screen.getByRole('tab', { name: 'Recruiter email' }))
    await waitFor(() => expect(approve).toBeEnabled())

    await u.click(approve)
    expect(calls.approved).toHaveLength(0) // asks first
    await u.click(await screen.findByRole('button', { name: 'Yes, approve' }))
    await waitFor(() => expect(calls.approved).toEqual(['/api/v1/postings/1/approve']))
    expect(await screen.findByText(/Approved Title 1, Company 1/)).toBeInTheDocument()
  })

  it('rejects with a reason', async () => {
    const calls = mockApi()
    renderAt('/review/1')
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Reject' }))
    await u.type(await screen.findByLabelText(/Reason/), 'not a fit')
    await u.click(screen.getByRole('button', { name: 'Yes, reject' }))
    await waitFor(() => expect(calls.rejected).toEqual([{ note: 'not a fit' }]))
  })

  it('moves to the next draft with j', async () => {
    mockApi()
    renderAt('/review/1')
    await screen.findByText('Hello world')
    await userEvent.setup().keyboard('j')
    expect(await screen.findByRole('heading', { name: 'Title 2' })).toBeInTheDocument()
  })
})
