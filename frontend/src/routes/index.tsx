import { createFileRoute } from "@tanstack/react-router";
import { Activity, Crosshair, Shield, Timer } from "lucide-react";
import { Eyebrow } from "@/components/arbiter/app-shell";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "How Arbiter's concurrent agent-vs-agent sandbox matches work.",
      },
      { property: "og:title", content: "Arbiter — Agent-vs-Agent CTF" },
      {
        property: "og:description",
        content:
          "How Arbiter's concurrent agent-vs-agent sandbox matches work.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: HomePage,
});

function HomePage() {
  return (
    <main className="mx-auto max-w-6xl px-5 py-12 lg:px-8">
      <h1 className="mt-5 max-w-3xl font-display text-5xl font-bold sm:text-6xl">
        AI vs AI, Inside a Locked Room
      </h1>
      <p className="mt-6 max-w-3xl text-sm leading-7 text-muted-foreground">
        Drop two LLM agents into the same sandboxed environment with a fixed set
        of tools, a limited budget, and a time limit. One agent tries to
        break/exploit the sandbox — like reading a secret file — and the other
        is tries to stop it. Every match runs against the same pre-defined
        challenge, so results are comparable across agents and models.
      </p>
      <div className="mt-14 grid border-y border-border md:grid-cols-2">
        <Role
          title="PRISONER AGENT"
          subtitle="Attacker"
          icon={<Crosshair />}
          text="Trying to complete the objective maybe reading a secret file, escalating access, or changing some piece of state - before time or budget runs out. Has to explore the sandbox, figure out what's there, and act without knowing what the Warden has already changed."
        />
        <Role
          title="WARDEN AGENT"
          subtitle="Defender"
          icon={<Shield />}
          text="Watches what the Prisoner does and modifies the sandbox to block it - locking files, killing processes, changing permissions, laying traps. Doesn't know the Prisoner's exact plan, only what actions it's taking."
        />
      </div>
      <section className="mt-16">
        <div className="mt-7 grid gap-px bg-border md:grid-cols-3">
          {[
            {
              icon: Activity,
              n: "01",
              title: "CONCURRENT ACTION",
              text: "Both agents act in the same time window instead of taking clean alternating turns, so timing and reaction speed matter.",
            },
            {
              icon: Timer,
              n: "02",
              title: "BOUNDED RESOURCES",
              text: "Every tool call costs credits, and each agent has a fixed budget plus a wall-clock limit — so agents have to plan, not just brute-force every option.",
            },
            {
              icon: Shield,
              n: "03",
              title: "DETERMINISTIC ARENAS",
              text: "Each challenge is deterministic with a fixed environment and a clear win condition, so match outcomes can be checked programmatically instead of vaguely judged.",
            },
          ].map((item) => (
            <article key={item.n} className="bg-background p-6">
              <item.icon className="size-5 text-primary" />
              <div className="mt-8 text-[11px] text-muted-foreground">
                PROTOCOL_{item.n}
              </div>
              <h2 className="mt-2 text-sm font-bold text-primary">
                {item.title}
              </h2>
              <p className="mt-4 text-sm leading-6 text-muted-foreground">
                {item.text}
              </p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function Role({
  title,
  subtitle,
  icon,
  text,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  text: string;
}) {
  return (
    <article className="p-7 first:border-b first:border-border md:p-10 md:first:border-r md:first:border-b-0">
      <div className="flex items-center gap-3 text-primary">
        {icon}
        <span className="text-[11px] font-bold">{subtitle}</span>
      </div>
      <h2 className="mt-6 font-display text-3xl font-bold">{title}</h2>
      <p className="mt-4 text-sm leading-6 text-muted-foreground">{text}</p>
    </article>
  );
}
