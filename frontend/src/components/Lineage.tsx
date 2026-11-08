import { fmt } from "../api";
import type { DataSource, WorkflowStep } from "../types";

function QueryDetails({ s }: { s: DataSource }) {
  return (
    <>
      {s.settings && (
        <div className="muted">Currency {s.settings.report_currency}, scope {s.settings.approval_scope}</div>
      )}
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
                  <td>{r.fx_rate ?? "pending"}</td>
                  <td>{r.fx_rate_date ?? "—"}</td>
                  <td>{fmt(r.amount_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </>
  );
}

const STATED_BY_ASSISTANT = "Rule being checked";

function Step({ n, w, sources }: { n: number; w: WorkflowStep; sources: DataSource[] }) {
  const source = w.source !== undefined ? sources[w.source] : undefined;
  return (
    <div className={`step ${w.step}`}>
      <div>
        <span className={`step-kind ${w.step}`}>{w.step === "policy" ? "Policy" : "Data"}</span>{" "}
        <b>{n}. {w.label}</b>
        {w.result && <span className="muted"> — {w.result}</span>}
      </div>
      {w.text && <div>{w.text}</div>}
      {w.label === STATED_BY_ASSISTANT && <div className="muted">As stated by the assistant before the lookup.</div>}
      {source && <QueryDetails s={source} />}
    </div>
  );
}

/** "How this was computed" (§8.2): produced by the backend, never written into the answer by the model. */
export function Lineage({ sources, workflow = [], title = "How this was computed" }:
  { sources: DataSource[]; workflow?: WorkflowStep[]; title?: string }) {
  if (!sources.length && !workflow.length) return null;
  const meta = sources[0];
  return (
    <details className="lineage">
      <summary>{title}</summary>
      <div className="lineage-body">
        {workflow.length > 0
          ? workflow.map((w, i) => <Step key={i} n={i + 1} w={w} sources={sources} />)
          : sources.map((s, i) => (
            <div className="step" key={i}>
              <div><b>{i + 1}. {s.label}</b></div>
              <QueryDetails s={s} />
            </div>
          ))}
        {meta && (
          <>
            <p className="muted">Policy <b>{meta.policy}</b> · FX: {meta.fx_source}</p>
            <ul className="files">
              {meta.source_files.map((f) => (
                <li key={f.file}>
                  <code>{f.file}</code> <span className="muted">sha256 {f.sha256.slice(0, 12)}…</span>
                </li>
              ))}
            </ul>
            <p className="muted">{meta.credit_note_treatment}</p>
          </>
        )}
      </div>
    </details>
  );
}
