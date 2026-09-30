import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { DataRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'

import { clearCacheOnSessionChange } from './lib/queries'

export function App({ router, queryClient }: { router: DataRouter; queryClient: QueryClient }) {
  useEffect(() => clearCacheOnSessionChange(queryClient), [queryClient])

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
