export function renderErrorPage(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>This page didn't load</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { color-scheme: dark; --ink: #18231d; --panel: #202d25; --line: rgba(234, 222, 178, .22); --bone: #eee5c9; --muted: #a8ad91; --signal: #d7ed55; }
      * { box-sizing: border-box; }
      body { min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 1.5rem; background-color: var(--ink); background-image: linear-gradient(rgba(234,222,178,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(234,222,178,.035) 1px, transparent 1px); background-size: 72px 72px; color: var(--bone); font: 15px/1.6 Lato, system-ui, sans-serif; }
      .card { width: min(100%, 42rem); border-top: 1px solid var(--signal); background: var(--panel); padding: clamp(1.5rem, 5vw, 4rem); }
      .code { margin: 0; color: var(--signal); font: 700 clamp(6rem, 20vw, 13rem)/.7 Georgia, serif; letter-spacing: -.1em; }
      h1 { margin: 2rem 0 0; font: 700 2rem/1 Georgia, serif; letter-spacing: -.05em; }
      p { max-width: 28rem; margin: .8rem 0 0; color: var(--muted); }
      .actions { display: flex; flex-wrap: wrap; gap: .7rem; margin-top: 1.8rem; }
      a, button { display: inline-flex; min-height: 2.7rem; align-items: center; padding: .7rem 1rem; border: 1px solid var(--line); border-radius: 1px; color: var(--bone); background: transparent; font: 700 11px/1 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .08em; text-decoration: none; text-transform: uppercase; cursor: pointer; }
      .primary { border-color: var(--signal); background: var(--signal); color: var(--ink); }
      .secondary:hover, a:hover { border-color: var(--signal); color: var(--signal); }
    </style>
  </head>
  <body>
    <div class="card">
      <p class="code">ERR</p>
      <h1>The arena dropped a connection.</h1>
      <p>Something went wrong while loading this page. You can try the room again or return to the front desk.</p>
      <div class="actions">
        <button class="primary" onclick="location.reload()">Try again</button>
        <a class="secondary" href="/">Go home</a>
      </div>
    </div>
  </body>
</html>`;
}
