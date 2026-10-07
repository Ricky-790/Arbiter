# Arbiter Frontend

The React + TanStack Start client: start matches, spectate them live, review the
archive, and fork interesting points to try again.

## Setup

```bash
bun install
cp .env.example .env.local   # optional; defaults to http://localhost:8000
```

`.env.local` only needs `VITE_API_BASE_URL`, the base URL of the Arbiter backend.
It defaults to `http://localhost:8000` when unset, which is where the backend's
dev server listens.

## Run

```bash
bun dev
```

Vite prints the URL on start; the default port is 5173.

| Command | Does |
| --- | --- |
| `bun dev` | Dev server with hot reload |
| `bun build` | Production build |
| `bun preview` | Serve the production build locally |
| `bun lint` | ESLint |
| `bun format` | Prettier |

The frontend talks to the backend over HTTP, so start the backend first — see
[`../backend/README.md`](../backend/README.md).

## Deployment note

This is a server-rendered TanStack Start app, so a static host will not serve it.
The production build emits a serverless function through Nitro's `vercel` preset
and needs `nitro` installed — it is an optional peer dependency of the shared
Vite config, and without it the build silently produces only client assets with
no server bundle and no `index.html`, which a host will answer with a 404.

```bash
bun run build && VERCEL=1 bun run build   # emits .vercel/output/
```