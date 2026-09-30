import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter } from 'react-router'

import { App } from '../App'
import { createQueryClient } from '../lib/queries'
import { routes } from '../routes'

/** The whole app at `path`, with the real routes, query client and session. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const queryClient = createQueryClient()
  // Same retry rules as the app, without waiting seconds between attempts.
  const { queries } = queryClient.getDefaultOptions()
  queryClient.setDefaultOptions({ queries: { ...queries, retryDelay: 0 } })
  const user = userEvent.setup()
  render(<App router={router} queryClient={queryClient} />)
  return { router, queryClient, user }
}
