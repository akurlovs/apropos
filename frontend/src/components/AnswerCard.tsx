import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AskResponse } from "../types";
import { Lineage } from "./Lineage";

export function AnswerCard({ r }: { r: AskResponse }) {
  const tools = Array.from(new Set(r.data_sources.map((s) => s.tool)));
  const a = r.applied_settings;
  return (
    <div className={`answer ${r.status === "error" ? "error" : ""}`}>
      {a && (
        <div className={`badge ${a.source === "question" ? "override" : ""}`}
             title={a.source === "question" ? "Overridden by your question for this answer only" : "From the settings bar"}>
          {a.report_currency === "EUR" ? "EUR" : "Original currency"} ·{" "}
          {a.approval_scope === "all" ? "All invoices" : "Approved only"} ·{" "}
          {a.source === "question" ? "set by question" : "settings"}
        </div>
      )}
      {r.unverified_figures.length > 0 && (
        <div className="warning">
          ⚠ Unverified figure{r.unverified_figures.length > 1 ? "s" : ""}: {r.unverified_figures.join(", ")} —
          not found in any tool result. Treat with caution.
        </div>
      )}
      <div className="md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.answer}</ReactMarkdown>
      </div>
      {r.not_determinable.length > 0 && (
        <div className="chips">
          {r.not_determinable.map((n) => (
            <span className="chip nd" key={n.clause} title={n.caveat || n.title}>
              {n.clause} not determinable · missing: {n.missing_fields.join(", ")}
            </span>
          ))}
        </div>
      )}
      {r.policy_citations.length > 0 && (
        <details className="citations">
          <summary>
            Policy citations:{" "}
            {Array.from(new Set(r.policy_citations.map((c) => c.section))).map((s) => (
              <span className="chip cite" key={s}>{s}</span>
            ))}
          </summary>
          <ul>
            {r.policy_citations.map((c, i) => (
              <li key={i}><b>{c.section}</b> <q>{c.quoted_text}</q></li>
            ))}
          </ul>
        </details>
      )}
      {tools.length > 0 && (
        <div className="chips">
          <span className="muted">Data:</span>
          {tools.map((t) => <span className="chip src" key={t}>{t}</span>)}
        </div>
      )}
      <Lineage sources={r.data_sources} />
    </div>
  );
}
