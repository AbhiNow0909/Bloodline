import { Navigate, type RouteObject } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/AppLayout'
import { FamiliesPage } from './pages/FamiliesPage'
import { FamilyPage } from './pages/FamilyPage'
import { LoginPage } from './pages/LoginPage'
import { MemberPage } from './pages/MemberPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ReportPage } from './pages/ReportPage'
import { TestPage } from './pages/TestPage'

/** Families are folders, members are the files inside them, and reports belong to members:
 *  /families → /families/:familyId → …/members/:memberId → …/reports/:reportId
 *  and a member's results for one test: …/members/:memberId/tests/:metricId */
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
          {
            path: 'families/:familyId/members/:memberId/reports/:reportId',
            Component: ReportPage,
            handle: { wide: true },
          },
          { path: 'families/:familyId/members/:memberId/tests/:metricId', Component: TestPage },
          { path: '*', Component: NotFoundPage },
        ],
      },
    ],
  },
]
