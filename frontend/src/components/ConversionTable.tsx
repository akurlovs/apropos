import { useEffect, useState } from "react";
import { csvUrl, fmt, getInvoices } from "../api";
import type { InvoiceRow, Settings } from "../types";

export function ConversionTable({ currency }: { currency: Settings["report_currency"] }) {
  const [rows, setRows] = useState<InvoiceRow[] | null>(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    getInvoices(currency).then((d) => setRows(d.rows));
  }, [currency]);
  if (!rows) return <div className="muted">Loading invoices…</div>;
  const f = filter.toLowerCase();
  const shown = rows.filter((r) => !f || JSON.stringify(r).toLowerCase().includes(f));
  return (
    <div className="conversion">
      <div className="toolbar">
        <input placeholder="Filter (invoice, vendor, currency…)" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <a className="button" href={csvUrl(currency)}>Download CSV</a>
      </div>
      <p className="muted">One row per invoice: amount / ECB rate (foreign units per EUR) = EUR, rounded to cents.
        Weekend and holiday dates use the previous ECB fixing (see rate date).</p>
      <div className="scroll">
        <table className="small">
          <thead>
            <tr><th>Invoice</th><th>Date</th><th>Vendor</th><th className="num">Amount</th><th>Cur.</th>
              <th className="num">Rate</th><th>Rate date</th><th className="num">EUR</th><th>PO</th><th>Approver</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.invoice_number} className={r.is_credit_note ? "credit" : ""}>
                <td>{r.invoice_number}</td><td>{r.invoice_date}</td><td>{r.vendor_name}</td>
                <td className="num">{fmt(r.amount)}</td><td>{r.currency}</td>
                <td className="num">{r.fx_rate}</td><td>{r.fx_rate_date}</td>
                <td className="num">{fmt(r.amount_eur)}</td>
                <td>{r.po_number ?? <span className="missing">none</span>}</td>
                <td>{r.approved_by ?? <span className="missing">none</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
