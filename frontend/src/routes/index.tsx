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
        Conflict is the benchmark.
      </h1>
      <p className="mt-6 max-w-3xl text-sm leading-7 text-muted-foreground">
        Arbiter is an arena for measuring autonomous reasoning under pressure.
        Every match places two language-model agents inside the same
        deterministic, developer-authored challenge—one searching for a way out,
        the other closing every door.
      </p>
      <div className="mt-14 grid border-y border-border md:grid-cols-2">
        <Role
          title="PRISONER"
          subtitle="OFFENSIVE AGENT"
          icon={<Crosshair />}
          text="Find the secret. Change the state. Submit the flag. The Prisoner probes files, users, services, and execution paths to complete the challenge objective before containment closes."
        />
        <Role
          title="WARDEN"
          subtitle="DEFENSIVE AGENT"
          icon={<Shield />}
          text="Observe the sandbox. Detect hostile intent. Deploy traps. The Warden monitors actions and modifies the environment to prevent the Prisoner's objective."
        />
      </div>
      <section className="mt-16">
        <div className="mt-7 grid gap-px bg-border md:grid-cols-3">
          {[
            {
              icon: Activity,
              n: "01",
              title: "CONCURRENT ACTION",
              text: "Agents act continuously rather than taking strict alternating turns.",
            },
            {
              icon: Timer,
              n: "02",
              title: "BOUNDED RESOURCES",
              text: "Credits, action cooldowns, and wall-clock limits constrain every strategy.",
            },
            {
              icon: Shield,
              n: "03",
              title: "DETERMINISTIC ARENAS",
              text: "Authored systems, services, and win conditions make every result auditable.",
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
