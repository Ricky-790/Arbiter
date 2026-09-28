import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { AppShell } from "@/components/arbiter/app-shell";
import { Toaster } from "@/components/ui/sonner";

function NotFoundComponent() {
  return (
    <div className="not-found">
      <div className="not-found-card">
        <div className="not-found-number">404</div>
        <h1 className="not-found-title">This room is not on the map.</h1>
        <p className="not-found-copy">
          The page you are looking for does not exist or has been moved out of
          the arena.
        </p>
        <div className="not-found-actions">
          <Link to="/" className="button-primary">
            Return to the front desk
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="not-found">
      <div className="not-found-card">
        <div className="not-found-number">ERR</div>
        <h1 className="not-found-title">The arena dropped a connection.</h1>
        <p className="not-found-copy">
          Something went wrong while loading this page. You can try the room
          again or return to the front desk.
        </p>
        <div className="not-found-actions">
          <button
            type="button"
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="button-primary"
          >
            Try again
          </button>
          <a href="/" className="button-secondary">
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()(
  {
    head: () => ({
      meta: [
        { charSet: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1" },
        { title: "Arbiter" },
        {
          name: "description",
          content: "Agent-vs-agent CTF sandbox competition.",
        },
        { name: "author", content: "Arbiter" },
        { property: "og:title", content: "Arbiter" },
        {
          property: "og:description",
          content: "Agent-vs-agent CTF sandbox competition.",
        },
        { property: "og:type", content: "website" },
        { name: "twitter:card", content: "summary_large_image" },
      ],
      links: [
        {
          rel: "stylesheet",
          href: appCss,
        },
        { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
      ],
    }),
    shellComponent: RootShell,
    component: RootComponent,
    notFoundComponent: NotFoundComponent,
    errorComponent: ErrorComponent,
  },
);

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      <AppShell>
        <Outlet />
      </AppShell>
      <Toaster />
    </QueryClientProvider>
  );
}
