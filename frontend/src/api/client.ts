import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

// The dev server and the nginx container both proxy /api and add the X-API-Key header,
// so the browser never holds the key.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request), // resolved per call so tests can stub it
})

export type PostingSummary = components['schemas']['PostingSummary']
export type PostingStatus = components['schemas']['PostingStatus']
export type CreateJobRequest = components['schemas']['CreateJobRequest']
export type DuplicateResponse = components['schemas']['DuplicateResponse']

/** Throws on an error response so React Query can surface it. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data === undefined) {
    throw new Error(`API ${result.response.status} ${result.response.statusText}`)
  }
  return result.data
}
