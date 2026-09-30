import { Navigate, type RouteObject } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/AppLayout'
import { FamiliesPage } from './pages/FamiliesPage'
import { FamilyPage } from './pages/FamilyPage'
import { LoginPage } from './pages/LoginPage'
import { MemberPage } from './pages/MemberPage'
import { NotFoundPage } from './pages/NotFoundPage'

/** Families are folders, members are the files inside them:
 *  /families → /families/:familyId → /families/:familyId/members/:memberId */
export const routes: RouteObject[] = [
  { path: '/login', Component: LoginPage },
  {
    path: '/',
    Component: RequireAuth,
    children: [
      {
        Component: AppLayout,
        children: [
          { index: true, element: <Navigate to="/families" replace /> },
          { path: 'families', Component: FamiliesPage },
          { path: 'families/:familyId', Component: FamilyPage },
          { path: 'families/:familyId/members/:memberId', Component: MemberPage },
          { path: '*', Component: NotFoundPage },
        ],
      },
    ],
  },
]
