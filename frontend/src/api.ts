import type { AskResponse, InvoiceRow, Settings, Summary } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export function getSummary(s: Settings): Promise<Summary> {
  const q = new URLSearchParams({ report_currency: s.report_currency, approval_scope: s.approval_scope });
  return fetch(`/api/summary?${q}`).then((r) => json<Summary>(r));
}

export function getInvoices(currency: Settings["report_currency"]): Promise<{ rows: InvoiceRow[] }> {
  return fetch(`/api/invoices?currency=${currency}`).then((r) => json(r));
}

export function csvUrl(currency: Settings["report_currency"]): string {
  return `/api/invoices?currency=${currency}&format=csv`;
}

export function ask(messages: { role: string; content: string }[], settings: Settings): Promise<AskResponse> {
  return fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, settings }),
  }).then((r) => json<AskResponse>(r));
}

export const fmt = (n: number, digits = 2) =>
  n.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
