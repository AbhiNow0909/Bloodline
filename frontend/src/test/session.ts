import { session } from '../lib/session'

const base64url = (value: object) =>
  btoa(JSON.stringify(value)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')

/** A JWT-shaped token that expires `seconds` from now. The signature is fake; only the
 * server checks signatures. */
export function fakeToken(seconds = 3600): string {
  const exp = Math.floor(Date.now() / 1000) + seconds
  return `${base64url({ alg: 'HS256', typ: 'JWT' })}.${base64url({ sub: 'user-1', exp })}.sig`
}

export function signIn(): void {
  session.start(fakeToken())
}
