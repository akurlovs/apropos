import { fmt } from "../api";
import type { DataSource } from "../types";

/** "How this was computed" (§8.2): produced by the backend, never by the model. */
export function Lineage({ sources, title = "How this was computed" }: { sources: DataSource[]; title?: string }) {
  if (!sources.length) return null;
  const meta = sources[0];
  return (
    <details className="lineage">
      <summary>{title}</summary>
      <div className="lineage-body">
        <p className="muted">
          Policy <b>{meta.policy}</b> · FX: {meta.fx_source}
        </p>
        <ul className="files">
          {meta.source_files.map((f) => (
            <li key={f.file}>
              <code>{f.file}</code> <span className="muted">sha256 {f.sha256.slice(0, 12)}…</span>
            </li>
          ))}
        </ul>
        <p className="muted">{meta.credit_note_treatment}</p>
        {sources.map((s, i) => (
          <div className="step" key={i}>
            <div>
              <b>{i + 1}. {s.tool}</b>{" "}
              {s.settings && (
                <span className="muted">
                  (currency {s.settings.report_currency}, scope {s.settings.approval_scope})
                </span>
              )}
            </div>
            {Object.values(s.args).some((v) => v !== null && v !== undefined && JSON.stringify(v) !== "{}") && (
              <div className="muted">args: <code>{JSON.stringify(s.args)}</code></div>
            )}
            <pre>{s.query}</pre>
            {s.note && <div className="muted">{s.note}</div>}
            {s.invoice_ids.length > 0 && (
              <details>
                <summary>{s.invoice_ids.length} invoice IDs</summary>
                <div className="ids">{s.invoice_ids.join(", ")}</div>
              </details>
            )}
            {s.fx_rows.length > 0 && (
              <details>
                <summary>{s.fx_rows.length} FX conversions used</summary>
                <table className="small">
                  <thead>
                    <tr><th>Invoice</th><th>Amount</th><th>Rate</th><th>Rate date</th><th>EUR</th></tr>
                  </thead>
                  <tbody>
                    {s.fx_rows.map((r) => (
                      <tr key={r.invoice_number}>
                        <td>{r.invoice_number}</td>
                        <td>{fmt(r.amount_original)} {r.currency}</td>
                        <td>{r.fx_rate}</td>
                        <td>{r.fx_rate_date}</td>
                        <td>{fmt(r.amount_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
