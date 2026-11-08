import { FormEvent, useEffect, useRef, useState } from "react";
import { ask, getStatus } from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { ConversionTable } from "./components/ConversionTable";
import { coverageText, DataNotices } from "./components/DataNotices";
import { SummaryPanel } from "./components/SummaryPanel";
import type { ChatTurn, DataStatus, Settings } from "./types";

const EXAMPLES = [
  "How much maverick spend did we have in Q3, and who must it be flagged to?",
  "Which invoices are missing an approver, and have any been paid?",
  "Which invoices need escalation because of vendor status?",
  "Have our credit notes been matched, and what is our net spend?",
  "Who had to approve INV-20133, and which FX rate was used?",
];

const MAX_HISTORY_SENT = 12; // the server only uses this many messages

export default function App() {
  const [settings, setSettings] = useState<Settings>({ report_currency: "EUR", approval_scope: "all", year: "latest" });
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"summary" | "invoices">("summary");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  useEffect(() => {
    getStatus().then(setStatus).catch((e) => setStatusErr(String(e.message ?? e)));
  }, []);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const next: ChatTurn[] = [...turns, { role: "user", content: q }];
    setTurns(next);
    setInput("");
    setBusy(true);
    try {
      // Only plain text history is sent; settings come from this request (never carried over silently).
      const r = await ask(next.slice(-MAX_HISTORY_SENT).map(({ role, content }) => ({ role, content })), settings);
      setTurns([...next, { role: "assistant", content: r.status === "ok" ? r.answer : "", response: r }]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setTurns([...next, {
        role: "assistant", content: "",
        response: { answer: `Request failed: ${msg}`, status: "error", applied_settings: null, data_sources: [],
          not_determinable: [], policy_citations: [], unverified_figures: [], answer_warnings: [], workflow: [] },
      }]);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  if (statusErr) {
    return (
      <div className="blocked">
        <h2>The server can't be reached</h2>
        <p>{statusErr}</p>
        <button onClick={() => location.reload()}>Retry</button>
      </div>
    );
  }
  if (!status) return <div className="blocked muted">Loading invoice data…</div>;
  if (status.state === "failed") {
    return (
      <div className="blocked">
        <h2>{status.redesign_needed ? "The data or policy has changed" : "The data could not be loaded"}</h2>
        <p>{status.message}</p>
        <p className="muted">No figures are shown until this is resolved.</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>Apropos</h1>
          <span className="muted">Invoices × {status.policy} — every answer sourced</span>
          <div className="muted coverage">{coverageText(status)}</div>
        </div>
        <div className="settings">
          <label>
            Period
            <select value={settings.year} onChange={(e) => setSettings({ ...settings, year: e.target.value })}>
              <option value="latest">Latest year ({status.latest_year})</option>
              {[...(status.years ?? [])].reverse().map((y) => <option key={y} value={String(y)}>{y}</option>)}
              <option value="all">All years</option>
            </select>
          </label>
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
      <DataNotices st={status} />
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
          {tab === "summary" ? <SummaryPanel settings={settings} /> : <ConversionTable currency={settings.report_currency} year={settings.year} />}
        </aside>
      </main>
    </div>
  );
}
