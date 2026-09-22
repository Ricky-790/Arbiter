import { createFileRoute, Outlet } from "@tanstack/react-router";

/**
 * Layout for `/matches`. The archive lives in `matches.index.tsx` and the
 * live spectator view in `matches.$matchId.tsx`; this route only provides the
 * required `<Outlet />` so both children can render.
 */
export const Route = createFileRoute("/matches")({
  component: MatchesLayout,
});

function MatchesLayout() {
  return <Outlet />;
}
