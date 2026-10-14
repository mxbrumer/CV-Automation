import type { components } from './schema'

export type ChatMessage = components['schemas']['ChatMessageOut']
export type ArtifactKind = components['schemas']['ArtifactKind']

/**
 * Sends one chat turn and reads the server-sent events (openapi-fetch cannot stream).
 * `onDelta` gets raw model text as it arrives; the promise resolves with the saved assistant
 * message, or rejects when the model call failed.
 */
export async function streamChat(
  postingId: number,
  kind: ArtifactKind,
  message: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<ChatMessage> {
  const response = await globalThis.fetch(
    new Request(`${window.location.origin}/api/v1/postings/${postingId}/artifacts/${kind}/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
      signal,
    }),
  )
  if (!response.ok || !response.body) throw new Error(`API ${response.status}`)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done: ChatMessage | null = null
  for (;;) {
    const chunk = await reader.read()
    if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const event = /^event: (.*)$/m.exec(block)?.[1]
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (!event || !data) continue
      const payload = JSON.parse(data) as { text?: string; detail?: string; message?: ChatMessage }
      if (event === 'delta') onDelta(payload.text ?? '')
      else if (event === 'error') throw new Error(payload.detail ?? 'model call failed')
      else if (event === 'done') done = payload.message ?? null
    }
  }
  if (!done) throw new Error('The reply ended before it was complete.')
  return done
}
