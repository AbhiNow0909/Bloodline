import { Navigate, Outlet, useLocation } from 'react-router'

import { useSession } from '../lib/queries'

/** Renders the signed-in part of the app, or sends the user to sign in and back again. */
export function RequireAuth() {
  const current = useSession()
  const location = useLocation()

  if (current === null) {
    const from = `${location.pathname}${location.search}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  return <Outlet />
}
