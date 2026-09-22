import type { ReactNode } from "react";

import type { JsonObject } from "@/lib/dto";

/** A labelled block of challenge spec content. */
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <section className="mt-6">
      <h3 className="text-xs text-muted-foreground">// {label}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <span className="text-xs text-muted-foreground">{children}</span>;
}

/** A JSONB column rendered as pretty-printed JSON. */
export function JsonBlock({ value }: { value: JsonObject }) {
  if (Object.keys(value).length === 0) return <Muted>—</Muted>;
  return (
    <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all border border-border bg-background p-3 text-sm leading-5 text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** A nullable text column (a script, for example). */
export function TextBlock({ value }: { value: string | null }) {
  if (value === null || value.trim() === "") return <Muted>—</Muted>;
  return (
    <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all border border-border bg-background p-3 text-sm leading-5 text-muted-foreground">
      {value}
    </pre>
  );
}

/** `path -> content` blocks for a challenge's `files` column. */
export function FileBlocks({ files }: { files: JsonObject }) {
  const entries = Object.entries(files);
  if (entries.length === 0) return <Muted>—</Muted>;
  return (
    <div className="space-y-3">
      {entries.map(([path, content]) => (
        <div key={path} className="border border-border bg-background">
          <div className="break-all border-b border-border px-3 py-2 text-xs text-primary">
            {path}
          </div>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all px-3 py-2 text-sm leading-5 text-muted-foreground">
            {formatValue(content)}
          </pre>
        </div>
      ))}
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value, null, 2);
}
