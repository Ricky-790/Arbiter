import type { ReactNode } from "react";

/** One readout in the masthead strip. */
export type MatchMetric = {
  label: string;
  value: ReactNode;
  /** Renders in the accent colour. */
  signal?: boolean;
};

/**
 * The header block shared by every state of one match: the preparing gate, the
 * live stream and the recorded transcript.
 */
export function MatchMasthead({
  eyebrow,
  title,
  status,
  metrics,
  error,
}: {
  eyebrow: string;
  title: string;
  /** Stream/queue state chip, or anything else that replaces it. */
  status?: ReactNode;
  metrics?: MatchMetric[];
  error?: ReactNode;
}) {
  return (
    <section className="page-wrap match-masthead">
      <div className="match-masthead-top">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1 className="match-title">{title}</h1>
        </div>
        {status}
      </div>

      {metrics !== undefined && metrics.length > 0 && (
        <div className="match-metrics">
          {metrics.map((metric) => (
            <div className="match-metric" key={metric.label}>
              <span className="match-metric-label">{metric.label}</span>
              <span
                className={
                  metric.signal === true
                    ? "match-metric-value signal"
                    : "match-metric-value"
                }
              >
                {metric.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {error}
    </section>
  );
}
