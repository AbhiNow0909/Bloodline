import type { Plugin } from 'vite'

/** Same default as `src/lib/api.ts`. */
const DEFAULT_API_BASE_URL = 'http://localhost:8000'

/**
 * The app's Content-Security-Policy: only its own scripts, styles and fonts, and network
 * requests only to itself and the API. The session token is kept in localStorage, so this
 * limits what injected script could load or where it could send data.
 *
 * `frame-ancestors` cannot be set from a <meta> tag; vercel.json sends it as a header.
 */
export function contentSecurityPolicy(apiBaseUrl: string): string {
  const api = new URL(apiBaseUrl).origin
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    // Vite inlines small images and fonts as data: URLs.
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src 'self' ${api}`,
    // The report review shows the original PDF from a local blob: URL in an iframe.
    'frame-src blob:',
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
}

/**
 * Adds the policy to the built index.html as a <meta> tag. It names the exact API origin,
 * which is only known at build time (VITE_API_BASE_URL), so it cannot live in vercel.json.
 * Not used by the dev server, whose hot reloading needs inline scripts.
 */
export function contentSecurityPolicyPlugin(): Plugin {
  let policy = ''
  return {
    name: 'bloodline:content-security-policy',
    apply: 'build',
    configResolved(config) {
      const configured: unknown = config.env.VITE_API_BASE_URL
      const apiBaseUrl = typeof configured === 'string' && configured ? configured : undefined
      // A Vercel build without the API's address would deploy an app that calls localhost.
      if (process.env.VERCEL && !apiBaseUrl?.startsWith('https://')) {
        throw new Error(
          'VITE_API_BASE_URL must be set to the API’s https:// address in the Vercel project ' +
            '(Settings → Environment Variables). See docs/deployment.md.',
        )
      }
      policy = contentSecurityPolicy(apiBaseUrl ?? DEFAULT_API_BASE_URL)
    },
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: { 'http-equiv': 'Content-Security-Policy', content: policy },
          injectTo: 'head-prepend',
        },
      ]
    },
  }
}
