import type { ReactNode } from "react";

import type { JsonObject } from "@/lib/dto";

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <section className="spec-section">
      <h3 className="spec-label">{label}</h3>
      <div className="spec-content">{children}</div>
    </section>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground">{children}</span>;
}

export function JsonBlock({ value }: { value: JsonObject }) {
  if (Object.keys(value).length === 0) return <Muted>—</Muted>;
  return <pre className="code-block">{JSON.stringify(value, null, 2)}</pre>;
}

export function TextBlock({ value }: { value: string | null }) {
  if (value === null || value.trim() === "") return <Muted>—</Muted>;
  return <pre className="code-block">{value}</pre>;
}

export function FileBlocks({ files }: { files: JsonObject }) {
  const entries = Object.entries(files);
  if (entries.length === 0) return <Muted>—</Muted>;
  return (
    <div>
      {entries.map(([path, content]) => (
        <div className="file-block" key={path}>
          <div className="file-path">{path}</div>
          <pre className="file-content">{formatValue(content)}</pre>
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
