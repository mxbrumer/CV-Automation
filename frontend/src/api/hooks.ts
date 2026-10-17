import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ArtifactKind } from './chat'
import {
  api,
  unwrap,
  type CreateJobRequest,
  type DuplicateResponse,
  type PostingStatus,
} from './client'

const POLL_MS = 15_000

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: async () => unwrap(await api.GET('/health')),
    refetchInterval: POLL_MS,
    retry: false,
  })

export const useStats = () =>
  useQuery({
    queryKey: ['stats'],
    queryFn: async () => unwrap(await api.GET('/api/v1/stats')),
    refetchInterval: POLL_MS,
  })

/** Number of postings in one status (the list endpoint's total, fetching a single row). */
export const useStatusCount = (status: PostingStatus) =>
  useQuery({
    queryKey: ['count', status],
    queryFn: async () => {
      const page = unwrap(
        await api.GET('/api/v1/postings', { params: { query: { status, page_size: 1 } } }),
      )
      return page.total
    },
    refetchInterval: POLL_MS,
  })

export const useRecentPostings = (limit = 10) =>
  useQuery({
    queryKey: ['postings', 'recent', limit],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/postings', {
          params: { query: { sort: 'recent', page_size: limit } },
        }),
      ),
    refetchInterval: POLL_MS,
  })

export const useLastRun = () =>
  useQuery({
    queryKey: ['last-run'],
    queryFn: async () => {
      const res = await api.GET('/api/v1/workflow/last-run')
      if (res.error !== undefined) throw new Error(`API ${res.response.status}`)
      return res.data ?? null
    },
    refetchInterval: POLL_MS,
  })

/** Re-runs analysis for `new` postings and generation for `matched` ones (after a lost run). */
export const useProcessPending = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/workflow/process-pending')),
    onSettled: () => qc.invalidateQueries(),
  })
}

// ---- add job (plan 15) -----------------------------------------------------------------------

/** A 409 from `POST /postings`: same URL (refused) or a similar company and title (A5). */
export class DuplicateError extends Error {
  readonly duplicate: DuplicateResponse
  constructor(duplicate: DuplicateResponse) {
    super(`duplicate: ${duplicate.reason}`)
    this.duplicate = duplicate
  }
}

/** Stores a pasted job; the backend starts its analysis at once. */
export const useAddJob = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateJobRequest) => {
      const res = await api.POST('/api/v1/postings', { body })
      if (res.response.status === 409 && res.error && 'reason' in res.error) {
        throw new DuplicateError(res.error)
      }
      return unwrap(res)
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

export const useMatchQueue = () =>
  useQuery({
    queryKey: ['postings', 'awaiting_match_review'],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/postings', {
          params: { query: { status: 'awaiting_match_review', page_size: 100 } },
        }),
      ).items,
    refetchInterval: POLL_MS,
  })

export const usePosting = (id: number) =>
  useQuery({
    queryKey: ['posting', id],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/postings/{posting_id}', { params: { path: { posting_id: id } } }),
      ),
  })

/** Gate 1: approve starts draft generation in the backend; decline keeps the optional reason. */
export const useMatchDecision = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { id: number; decision: 'approve' | 'decline'; note?: string }) =>
      unwrap(
        await api.POST('/api/v1/postings/{posting_id}/match-decision', {
          params: { path: { posting_id: v.id } },
          body: { decision: v.decision, note: v.note || null },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}

// ---- review (plan 12) ------------------------------------------------------------------------

const listByStatus = (status: PostingStatus) => ({
  queryKey: ['postings', status],
  queryFn: async () =>
    unwrap(await api.GET('/api/v1/postings', { params: { query: { status, page_size: 100 } } }))
      .items,
  refetchInterval: POLL_MS,
})

export const useGenerated = () => useQuery(listByStatus('generated'))

export const useArtifact = (id: number, kind: ArtifactKind, version?: number) =>
  useQuery({
    queryKey: ['artifact', id, kind, version ?? 'latest'],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/postings/{posting_id}/artifacts/{kind}', {
          params: { path: { posting_id: id, kind }, query: { version } },
        }),
      ),
  })

/** Original template: the CV is its own template, so it is the joined cv.md sections. */
export const useTemplate = (kind: ArtifactKind) =>
  useQuery({
    queryKey: ['template', kind],
    retry: false,
    queryFn: async () => {
      if (kind === 'cv') {
        const sections = unwrap(await api.GET('/api/v1/tools/profile/cv-sections'))
        return sections.map((s) => s.markdown).join('\n\n')
      }
      return unwrap(
        await api.GET('/api/v1/tools/profile/templates/{kind}', { params: { path: { kind } } }),
      ).markdown
    },
  })

export const useChatHistory = (id: number, kind: ArtifactKind) =>
  useQuery({
    queryKey: ['chat', id, kind],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/postings/{posting_id}/artifacts/{kind}/chat', {
          params: { path: { posting_id: id, kind } },
        }),
      ),
  })

export const useAcceptProposal = (id: number, kind: ArtifactKind) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (messageId: number) =>
      unwrap(
        await api.POST('/api/v1/postings/{posting_id}/artifacts/{kind}/chat/accept', {
          params: { path: { posting_id: id, kind } },
          body: { message_id: messageId },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}

export const useSaveArtifact = (id: number, kind: ArtifactKind) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (markdown: string) =>
      unwrap(
        await api.PUT('/api/v1/postings/{posting_id}/artifacts/{kind}', {
          params: { path: { posting_id: id, kind } },
          body: { markdown },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}

/** Gate 2: approve moves the posting into the queue; reject declines it. */
export const useApprove = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) =>
      unwrap(
        await api.POST('/api/v1/postings/{posting_id}/approve', {
          params: { path: { posting_id: id } },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}

export const useReject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { id: number; note?: string }) =>
      unwrap(
        await api.POST('/api/v1/postings/{posting_id}/reject', {
          params: { path: { posting_id: v.id } },
          body: { note: v.note || null },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}

// ---- queue (plan 13) -------------------------------------------------------------------------

/** Approved postings in queue order; the first one is what `GET /queue/next` returns. */
export const useQueue = () =>
  useQuery({
    queryKey: ['postings', 'approved'],
    queryFn: async () => {
      const items = unwrap(
        await api.GET('/api/v1/postings', {
          params: { query: { status: 'approved', page_size: 100 } },
        }),
      ).items
      return [...items].sort(
        (a, b) =>
          (a.queue_position ?? Infinity) - (b.queue_position ?? Infinity) ||
          a.posting_id - b.posting_id,
      )
    },
    refetchInterval: POLL_MS,
  })

export const useQueueAction = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: {
      id: number
      action: 'submitted' | 'declined' | 'skip'
      note?: string
    }) =>
      unwrap(
        await api.POST('/api/v1/queue/{posting_id}/action', {
          params: { path: { posting_id: v.id } },
          body: { action: v.action, note: v.note || null },
        }),
      ),
    onSettled: () => qc.invalidateQueries(),
  })
}
