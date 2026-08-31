/**
 * Decouples the low-level axios client from the auth store.
 *
 * The client needs (a) the current bearer token to attach and (b) a way to react when the
 * server rejects that token (401). The auth store owns both, but having the client import the
 * store — while the store imports the client (via api/auth) — would create a require cycle.
 * Instead the store registers callbacks here at startup, and the client reads through this
 * neutral module.
 */

type TokenGetter = () => string | null
type UnauthorizedHandler = () => void

let getToken: TokenGetter = () => null
let onUnauthorized: UnauthorizedHandler = () => {}

export const sessionBridge = {
  /** Current access token, or null when unauthenticated. Read by the request interceptor. */
  getToken: (): string | null => getToken(),
  setTokenGetter: (fn: TokenGetter): void => {
    getToken = fn
  },

  /** Invoked by the response interceptor when a bearer request comes back 401. */
  handleUnauthorized: (): void => onUnauthorized(),
  setUnauthorizedHandler: (fn: UnauthorizedHandler): void => {
    onUnauthorized = fn
  },
}
