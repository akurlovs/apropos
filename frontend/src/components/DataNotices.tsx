import type { DataStatus } from "../types";

export function coverageText(st: DataStatus): string {
  const files = st.files ?? [];
  return `${st.invoices_loaded?.toLocaleString("en-GB")} invoices from ${files.length} file${files.length === 1 ? "" : "s"}` +
    ` · latest invoice ${st.latest_year_through} · data loaded ${st.loaded_at?.slice(0, 16).replace("T", " ")} UTC`;
}

export function DataNotices({ st }: { st: DataStatus }) {
  const rejected = st.rejected ?? [];
  const pending = st.rate_pending?.count ?? 0;
  const ignored = st.ignored_files ?? [];
  if (!rejected.length && !pending && !ignored.length) return null;
  return (
    <div className="notices">
      {rejected.length > 0 && (
        <details className="warning">
          <summary>{st.rejected_count} invoice rows could not be loaded and are not in any figure</summary>
          <ul>
            {rejected.map((r, i) => (
              <li key={i}>{r.file}, line {r.csv_line}{r.invoice_number ? ` (${r.invoice_number})` : ""}: {r.reason}</li>
            ))}
          </ul>
        </details>
      )}
      {pending > 0 && (
        <div className="warning">
          {pending} invoice{pending === 1 ? " has" : "s have"} no exchange rate yet (latest rate {st.fx_latest_date}), so{" "}
          {pending === 1 ? "it is" : "they are"} left out of EUR totals and thresholds.
        </div>
      )}
      {ignored.length > 0 && <div className="warning">Files not loaded (unexpected name): {ignored.join(", ")}</div>}
    </div>
  );
}
