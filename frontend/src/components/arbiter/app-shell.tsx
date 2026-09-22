import { Link } from "@tanstack/react-router";
import { Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

const navItems = [
  { to: "/", label: "HOME" },
  { to: "/challenges", label: "CHALLENGES" },
  { to: "/matches", label: "MATCHES" },
  { to: "/leaderboard", label: "LEADERBOARD" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-8 px-5 lg:px-8">
          <Link to="/" className="font-display text-2xl font-bold tracking-normal">ARBITER</Link>
          <nav className="hidden h-full items-center gap-7 md:flex" aria-label="Main navigation">
            {navItems.map((item) => (
              <Link key={item.to} to={item.to} activeOptions={{ exact: item.to === "/" }} className="nav-link" activeProps={{ className: "nav-link nav-link-active" }}>
                {item.label}
              </Link>
            ))}
          </nav>
          <Button variant="ghost" size="icon" className="ml-auto rounded-none md:hidden" onClick={() => setMenuOpen((open) => !open)} aria-label={menuOpen ? "Close menu" : "Open menu"}>
            {menuOpen ? <X /> : <Menu />}
          </Button>
        </div>
        {menuOpen && (
          <nav className="grid border-t border-border bg-panel px-5 py-3 md:hidden" aria-label="Mobile navigation">
            {navItems.map((item) => (
              <Link key={item.to} to={item.to} onClick={() => setMenuOpen(false)} className="border-b border-border py-3 font-mono text-sm text-muted-foreground last:border-0" activeProps={{ className: "border-b border-border py-3 font-mono text-sm text-primary last:border-0" }}>
                {item.label}
              </Link>
            ))}
          </nav>
        )}
      </header>
      {children}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="font-mono text-xs font-bold uppercase text-primary">// {children}</p>;
}

export function RoleBadge({ children }: { children: ReactNode }) {
  return <span className="inline-flex border border-primary px-1.5 py-0.5 font-mono text-xs font-bold text-primary">{children}</span>;
}

export function ResultBadge({ result }: { result: "WIN" | "LOSS" | "DRAW" }) {
  return <span className={result === "DRAW" ? "status-badge status-muted" : "status-badge"}>{result}</span>;
}