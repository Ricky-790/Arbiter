import { Link } from "@tanstack/react-router";
import { Github, Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

const REPOSITORY_URL = "https://github.com/Ricky-790/Arbiter/tree/main";

const navItems = [
  { to: "/", label: "Home", index: "00" },
  { to: "/challenges", label: "Challenges", index: "01" },
  { to: "/matches", label: "Matches", index: "02" },
  { to: "/forks", label: "Forks", index: "03" },
  { to: "/leaderboard", label: "Leaderboard", index: "04" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="site-frame">
      <header className="site-header">
        <div className="site-header-inner">
          <Link to="/" className="brand-mark" aria-label="Arbiter home">
            <span className="brand-mark-word">ARBITER</span>
            <span className="brand-mark-rule" aria-hidden="true" />
            <span className="brand-mark-meta">
              <span>Adversarial</span>
              <span>matchmaking</span>
            </span>
          </Link>

          <nav className="site-nav" aria-label="Main navigation">
            {navItems.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                activeOptions={{ exact: item.to === "/" }}
                className="nav-link"
                activeProps={{ className: "nav-link nav-link-active" }}
              >
                <span className="nav-index">{item.index}</span>
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="header-actions">
            <button
              type="button"
              className="mobile-menu-button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
            >
              {menuOpen ? (
                <X className="size-4" />
              ) : (
                <Menu className="size-4" />
              )}
            </button>
            <a
              href={REPOSITORY_URL}
              target="_blank"
              rel="noreferrer noopener"
              aria-label="View the Arbiter repository on GitHub"
              title="View the Arbiter repository on GitHub"
              className="github-link"
            >
              <Github className="size-3.5" />
              <span>Source</span>
            </a>
          </div>
        </div>

        {menuOpen && (
          <nav className="mobile-nav" aria-label="Mobile navigation">
            {navItems.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setMenuOpen(false)}
                className=""
                activeProps={{ className: "active" }}
              >
                <span className="nav-index">{item.index}</span>
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
  return <p className="eyebrow">{children}</p>;
}

export function RoleBadge({ children }: { children: ReactNode }) {
  return <span className="outcome-badge">{children}</span>;
}

export function ResultBadge({ result }: { result: "WIN" | "LOSS" | "DRAW" }) {
  return (
    <span
      className={result === "DRAW" ? "outcome-badge muted" : "outcome-badge"}
    >
      {result}
    </span>
  );
}
