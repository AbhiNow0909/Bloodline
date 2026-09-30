/** The page with one test's chart and results for a member. */
export function testPath(familyId: string, memberId: string, metricId: string): string {
  return `/families/${familyId}/members/${memberId}/tests/${metricId}`
}
