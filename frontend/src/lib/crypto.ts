import type { PublicKeyResponse } from "@/lib/dto";

/**
 * RSA transport for the provider keys this app sends.
 *
 * A browser holds no shared secret with the server, so anything it could use to
 * *decrypt* would be readable by whoever intercepts the request. The transport is
 * therefore asymmetric: `GET /api/v1/crypto/public-key` hands out the
 * deployment's public half, this module encrypts just the `*_api_key` fields
 * with it, and only the server can open them again.
 *
 * Nothing else in a request body is touched, and the ciphertext goes back in the
 * field it came from.
 *
 * **The transport can be off.** A deployment that has not configured
 * `ARBITER_RSA_PUBLIC_KEY` / `ARBITER_RSA_PRIVATE_KEY` answers that endpoint with
 * a 503, and the server still reads plaintext keys exactly as it did before this
 * existed. A 503 therefore means "send it as-is", not "fail": the app keeps
 * working against a deployment that has not adopted this.
 */

const configuredBaseUrl =
  import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000";

/** Backend origin, without a trailing slash. Matches `lib/api`. */
const API_BASE_URL = String(configuredBaseUrl).replace(/\/+$/, "");

/**
 * How long a fetched key is reused.
 *
 * The key is a property of the deployment, not of a request, so it is fetched
 * once rather than per keystroke — the model check alone fires on every debounced
 * model name. The window bounds how long a rotated key keeps being used; a
 * server that cannot open one clears the cache outright (see `resetApiKeyTransport`).
 */
const KEY_TTL_MS = 10 * 60 * 1000;

/**
 * The key, fetched at most once per window. `null` is a real answer, not a
 * failure: it records that this deployment has the transport switched off.
 */
type KeyState =
  | { status: "idle" }
  | { status: "loading"; promise: Promise<CryptoKey | null> }
  | { status: "ready"; key: CryptoKey | null; at: number };

let state: KeyState = { status: "idle" };

/**
 * Forget the key so the next request fetches it again.
 *
 * Worth calling when the server rejects a key it could not open: that is what a
 * rotated deployment key looks like, and the stale one would otherwise fail every
 * request until the page is reloaded.
 */
export function resetApiKeyTransport(): void {
  state = { status: "idle" };
}

/**
 * Encrypt one provider key for transport.
 *
 * Returns the value unchanged when the deployment has the transport off, or when
 * the value cannot be encrypted for any reason: a key that reaches the server as
 * plaintext is still a working request, while a request that refuses to be sent
 * is not. `null` in, `null` out, so an absent key stays absent.
 */
export async function encryptApiKey(
  plaintext: string | null,
): Promise<string | null> {
  if (plaintext === null || plaintext === "") return plaintext;

  const key = await loadKey();
  if (key === null) return plaintext;

  try {
    const ciphertext = await crypto.subtle.encrypt(
      { name: "RSA-OAEP" },
      key,
      new TextEncoder().encode(plaintext),
    );
    return base64(new Uint8Array(ciphertext));
  } catch {
    // RSA-OAEP only takes a couple of hundred bytes of plaintext, so a longer
    // value is not a provider key. Sending it whole beats dropping the request.
    return plaintext;
  }
}

/**
 * Encrypt the named fields of a request body.
 *
 * Every api-key field is named explicitly, so adding one to a request is a
 * deliberate act with a matching line at the call site rather than something a
 * route has to remember to do.
 *
 * The plaintexts are handed back alongside the body so the caller can scrub them
 * out of any error text the server returns. Today the server never echoes a key,
 * so that is belt and braces rather than a fix — but an error message is exactly
 * the kind of thing that ends up in a toast, a console, and an error reporter, so
 * it is worth closing.
 */
export async function encryptApiKeyFields<T extends Record<string, unknown>>(
  body: T,
  fields: readonly string[],
): Promise<{ body: T; secrets: string[] }> {
  const encrypted: Record<string, unknown> = { ...body };
  const secrets: string[] = [];

  await Promise.all(
    fields.map(async (field) => {
      const value = body[field];
      if (typeof value !== "string" || value === "") return;
      const cipher = await encryptApiKey(value);
      // A field left as plaintext (transport off, or too long to encrypt) is just
      // as much a secret as an encrypted one, so it is scrubbed either way.
      secrets.push(value);
      encrypted[field] = cipher;
    }),
  );

  return { body: encrypted as T, secrets };
}

/**
 * Replace any of `secrets` in `text` with a marker.
 *
 * Used on server-supplied error text before it becomes an Error. Matches on
 * substring rather than as a whole token, because a value could arrive embedded
 * in a sentence.
 */
export function redactSecrets(
  text: string,
  secrets: readonly string[],
): string {
  let scrubbed = text;
  for (const secret of secrets) {
    // Nothing this short can be a provider key, and replacing it would mangle
    // ordinary words.
    if (secret.length < 8) continue;
    scrubbed = scrubbed.split(secret).join("[redacted]");
  }
  return scrubbed;
}

/** The deployment's public half as a WebCrypto key, or `null` when it is off. */
async function loadKey(): Promise<CryptoKey | null> {
  if (state.status === "ready" && Date.now() - state.at < KEY_TTL_MS) {
    return state.key;
  }
  // One fetch for concurrent callers: seating both sides verifies both models,
  // and they would otherwise ask at the same moment.
  state = { status: "loading", promise: importPublicKey() };
  const key = await state.promise;
  state = { status: "ready", key, at: Date.now() };
  return key;
}

/**
 * `GET /api/v1/crypto/public-key`, imported for WebCrypto.
 *
 * `null` means there was nothing usable to import — the documented 503 for a
 * deployment with the transport off, or any failure to reach it. Both leave the
 * caller sending plaintext, which the server still accepts.
 */
async function importPublicKey(): Promise<CryptoKey | null> {
  const published = await fetchPublicKey();
  if (published === null) return null;
  try {
    return await crypto.subtle.importKey(
      "jwk",
      published.public_key_jwk,
      // WebCrypto's parameters come from the response rather than being hardcoded,
      // so a deployment that moves to another scheme says so instead of us
      // guessing. The JWK is the documented browser-side form; a PEM would have to
      // be stripped of its armour and base64-decoded to DER first.
      { name: published.algorithm, hash: published.hash_algorithm },
      false,
      ["encrypt"],
    );
  } catch {
    return null;
  }
}

async function fetchPublicKey(): Promise<PublicKeyResponse | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/crypto/public-key`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    return (await response.json()) as PublicKeyResponse;
  } catch {
    return null;
  }
}

/** Standard base64, chunked so a large buffer cannot blow the argument limit. */
function base64(bytes: Uint8Array): string {
  const CHUNK = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}
