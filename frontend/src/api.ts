import type { AskResponse, DataStatus, InvoiceRow, Settings, Summary } from "./types";

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

export function getStatus(): Promise<DataStatus> {
  return fetch("/api/status").then((r) => json<DataStatus>(r));
}

export function getSummary(s: Settings, signal?: AbortSignal): Promise<Summary> {
  const q = new URLSearchParams({ report_currency: s.report_currency, approval_scope: s.approval_scope, year: s.year });
  return fetch(`/api/summary?${q}`, { signal }).then((r) => json<Summary>(r));
}

export function getInvoices(currency: Settings["report_currency"], year: string, signal?: AbortSignal): Promise<{ rows: InvoiceRow[] }> {
  return fetch(`/api/invoices?currency=${currency}&year=${year}`, { signal }).then((r) => json(r));
}

export function csvUrl(currency: Settings["report_currency"], year: string): string {
  return `/api/invoices?currency=${currency}&year=${year}&format=csv`;
}

export function ask(messages: { role: string; content: string }[], settings: Settings): Promise<AskResponse> {
  return fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, settings }),
  }).then((r) => json<AskResponse>(r));
}

// A missing amount means "no exchange rate yet": never show it as 0 or blank.
export const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "pending" : n.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
