import { describe, expect, it } from 'vitest'

import { contentSecurityPolicy } from './csp.ts'

describe('contentSecurityPolicy', () => {
  it('allows requests to the API origin only, whatever path the address has', () => {
    const policy = contentSecurityPolicy('https://bloodline-api.onrender.com/')

    expect(policy).toContain("connect-src 'self' https://bloodline-api.onrender.com;")
    expect(contentSecurityPolicy('https://api.example.org/v1/')).toContain(
      "connect-src 'self' https://api.example.org;",
    )
  })

  it('allows only the app’s own scripts and styles, and the PDF preview frame', () => {
    const directives = contentSecurityPolicy('http://localhost:8000').split('; ')

    expect(directives).toEqual(
      expect.arrayContaining([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        'frame-src blob:',
        "object-src 'none'",
        "base-uri 'self'",
      ]),
    )
    expect(directives.join(' ')).not.toContain('unsafe')
  })

  it('refuses an address that is not a URL', () => {
    expect(() => contentSecurityPolicy('bloodline-api.onrender.com')).toThrow()
  })
})
