import { FormEvent, useEffect, useRef, useState } from "react";
import { ask } from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { ConversionTable } from "./components/ConversionTable";
import { SummaryPanel } from "./components/SummaryPanel";
import type { ChatTurn, Settings } from "./types";

const EXAMPLES = [
  "How much maverick spend did we have in Q3, and who must it be flagged to?",
  "Which invoices are missing an approver, and have any been paid?",
  "Which invoices need escalation because of vendor status?",
  "Have our credit notes been matched, and what is our net spend?",
  "Who had to approve INV-20133, and which FX rate was used?",
];

export default function App() {
  const [settings, setSettings] = useState<Settings>({ report_currency: "EUR", approval_scope: "all" });
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"summary" | "invoices">("summary");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const next: ChatTurn[] = [...turns, { role: "user", content: q }];
    setTurns(next);
    setInput("");
    setBusy(true);
    try {
      // Only plain text history is sent; settings come from this request (never carried over silently).
      const r = await ask(next.map(({ role, content }) => ({ role, content })), settings);
      setTurns([...next, { role: "assistant", content: r.status === "ok" ? r.answer : "", response: r }]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setTurns([...next, {
        role: "assistant", content: "",
        response: { answer: `Request failed: ${msg}`, status: "error", applied_settings: null, data_sources: [],
          not_determinable: [], policy_citations: [], unverified_figures: [] },
      }]);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <div className="app">
      <header>
        <div>
          <h1>Apropos</h1>
          <span className="muted">2025 invoices × FIN-POL-014 v3.2 — every answer sourced</span>
        </div>
        <div className="settings">
          <label>
            Report currency
            <select value={settings.report_currency}
                    onChange={(e) => setSettings({ ...settings, report_currency: e.target.value as Settings["report_currency"] })}>
              <option value="EUR">EUR (converted)</option>
              <option value="original">Original currency</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={settings.approval_scope === "approved_only"}
                   onChange={(e) => setSettings({ ...settings, approval_scope: e.target.checked ? "approved_only" : "all" })} />
            Exclude invoices without approver record (§3.1 holds)
          </label>
        </div>
      </header>
      <main>
        <section className="chat">
          <div className="turns">
            {turns.length === 0 && (
              <div className="empty">
                <p>Ask about spend, PO compliance, approvals, vendor status, credit notes or FX — or about what the
                  policy requires. Try:</p>
                {EXAMPLES.map((q) => <button key={q} className="example" onClick={() => send(q)}>{q}</button>)}
              </div>
            )}
            {turns.map((t, i) =>
              t.role === "user"
                ? <div className="user" key={i}>{t.content}</div>
                : <AnswerCard key={i} r={t.response!} />,
            )}
            {busy && <div className="thinking">Querying data and policy…</div>}
            <div ref={endRef} />
          </div>
          <form onSubmit={onSubmit}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question…" maxLength={2000} />
            <button disabled={busy || !input.trim()}>Ask</button>
            {turns.length > 0 && <button type="button" className="secondary" onClick={() => setTurns([])}>New chat</button>}
          </form>
        </section>
        <aside>
          <div className="tabs">
            <button className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}>Summary</button>
            <button className={tab === "invoices" ? "active" : ""} onClick={() => setTab("invoices")}>Conversion table</button>
          </div>
          {tab === "summary" ? <SummaryPanel settings={settings} /> : <ConversionTable currency={settings.report_currency} />}
        </aside>
      </main>
    </div>
  );
}
