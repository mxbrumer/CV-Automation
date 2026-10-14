import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type PostingStatus } from './client'

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

/** Starts the analysis phase for every new posting (POST /workflow/poll would also fetch the feed). */
export const useRunPipeline = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/workflow/poll')),
    onSettled: () => qc.invalidateQueries(),
  })
}
