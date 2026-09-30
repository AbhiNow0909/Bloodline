/**
 * Object URLs for files held in the query cache (e.g. a report's PDF). Each blob gets one URL
 * for as long as the cache keeps it; the URL is released when the cache drops the blob,
 * including when the user signs out and the whole cache is cleared.
 */
import type { QueryClient } from '@tanstack/react-query'

const urls = new WeakMap<Blob, string>()

export function objectUrlFor(blob: Blob): string {
  let url = urls.get(blob)
  if (url === undefined) {
    url = URL.createObjectURL(blob)
    urls.set(blob, url)
  }
  return url
}

function release(data: unknown): void {
  if (!(data instanceof Blob)) return
  const url = urls.get(data)
  if (url === undefined) return
  URL.revokeObjectURL(url)
  urls.delete(data)
}

/** Release a blob's URL when its query is removed from the cache. */
export function releaseObjectUrlsWith(client: QueryClient): () => void {
  return client.getQueryCache().subscribe((event) => {
    if (event.type === 'removed') release(event.query.state.data)
  })
}
