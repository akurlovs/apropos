import { useEffect, useState } from "react";
import { fmt, getSummary } from "../api";
import type { Settings, SpendResult, Summary } from "../types";
import { Lineage } from "./Lineage";

function SpendTable({ title, data, original }: { title: string; data: SpendResult; original: boolean }) {
  const grouped = data.group_by !== "none";
  return (
    <div className="block">
      <h4>{title}</h4>
      <table className="small">
        <thead>
          <tr>
            {grouped && <th>{data.group_by}</th>}
            {original && <th>Cur.</th>}
            <th className="num">Gross</th><th className="num">Credits</th><th className="num">Net</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i}>
              {grouped && <td>{r.grp}</td>}
              {original && <td>{r.currency}</td>}
              <td className="num">{fmt(r.gross)}</td>
              <td className="num">{r.credit_notes ? fmt(r.credit_notes) : "—"}</td>
              <td className="num">{fmt(r.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SummaryPanel({ settings }: { settings: Settings }) {
  const [s, setS] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setErr(null);
    getSummary(settings, ctl.signal).then(setS).catch((e) => {
      if (e.name !== "AbortError") setErr(String(e.message ?? e));
    });
    return () => ctl.abort();
  }, [settings]);
  if (err) return <div className="warning">Summary failed: {err}</div>;
  if (!s) return <div className="muted">Loading summary…</div>;
  // Render from the settings the loaded summary was computed with (avoids a stale-data race on toggle).
  const original = s.settings.report_currency === "original";
  const eurTotal = (original ? s.total.cross_currency_total_eur : s.total.rows[0]) ?? s.total.rows[0];
  return (
    <div className="summary">
      {s.period && <p className="period">Period: <b>{s.period}</b></p>}
      <div className="tiles">
        <div className="tile"><span>Gross spend (EUR)</span><b>{fmt(eurTotal.gross)}</b></div>
        <div className="tile"><span>Credit notes (EUR)</span><b>{fmt(eurTotal.credit_notes)}</b></div>
        <div className="tile"><span>Net (EUR)</span><b>{fmt(eurTotal.net)}</b></div>
      </div>
      {original && (
        <p className="muted">Totals above are EUR (converted at the ECB rate on the invoice date). Tables below
          show per-currency subtotals — amounts in different currencies are never added together.</p>
      )}
      {s.total.rate_pending && (
        <p className="warning">{s.total.rate_pending.note}</p>
      )}
      {s.total.excluded_by_scope && (
        <p className="muted">
          Excluding {s.total.excluded_by_scope.count} invoices without approver record (§3.1 holds):{" "}
          {s.total.excluded_by_scope.invoice_numbers.join(", ")}
        </p>
      )}
      <div className="block">
        <h4>Policy flags <span className="muted">(not affected by the approver filter)</span></h4>
        <ul className="flags">
          {Object.entries(s.flags).map(([k, v]) => <li key={k}><b>{v}</b> {k}</li>)}
        </ul>
      </div>
      {original && <SpendTable title="By currency" data={s.total} original />}
      {!original && <SpendTable title="By currency (EUR)" data={s.by_currency} original={false} />}
      <SpendTable title={`By vendor${original ? "" : " (EUR)"}`} data={s.by_vendor} original={original} />
      <SpendTable title={`By vendor category${original ? "" : " (EUR)"}`} data={s.by_vendor_category} original={original} />
      <Lineage sources={s.lineage.computations} />
    </div>
  );
}
