export type ReportCurrency = "EUR" | "original";
export type ApprovalScope = "all" | "approved_only";
export interface Settings {
  report_currency: ReportCurrency;
  approval_scope: ApprovalScope;
}

export interface FxRow {
  invoice_number: string;
  currency: string;
  amount_original: number;
  fx_rate: number;
  fx_rate_date: string;
  amount_eur: number;
}

export interface SourceFile {
  file: string;
  sha256: string;
}

export interface DataSource {
  tool: string;
  query: string;
  args: Record<string, unknown>;
  invoice_ids: string[];
  fx_rows: FxRow[];
  settings: Settings | null;
  credit_note_treatment: string;
  note: string;
  policy: string;
  source_files: SourceFile[];
  fx_source: string;
}

export interface NotDeterminable {
  clause: string;
  title: string;
  missing_fields: string[];
  caveat: string;
}

export interface Citation {
  section: string;
  quoted_text: string;
  document: string;
}

export interface AppliedSettings extends Settings {
  source: "gui" | "question";
}

export interface AskResponse {
  answer: string;
  status: "ok" | "error";
  applied_settings: AppliedSettings | null;
  data_sources: DataSource[];
  not_determinable: NotDeterminable[];
  policy_citations: Citation[];
  unverified_figures: string[];
  tools_called?: string[];
}

export interface SpendRow {
  grp?: string;
  currency?: string;
  invoice_count: number;
  credit_note_count: number;
  gross: number;
  credit_notes: number;
  net: number;
}

export interface SpendResult {
  currency: string;
  group_by: string;
  rows: SpendRow[];
  credit_note_treatment: string;
  excluded_by_scope?: { count: number; invoice_numbers: string[]; reason: string };
  cross_currency_total_eur?: { label: string; gross: number; credit_notes: number; net: number };
}

export interface Summary {
  settings: Settings;
  total: SpendResult;
  by_currency: SpendResult;
  by_vendor: SpendResult;
  by_vendor_category: SpendResult;
  flags: Record<string, number>;
  lineage: {
    policy: string;
    source_files: SourceFile[];
    fx_source: string;
    credit_note_treatment: string;
    computations: DataSource[];
  };
}

export interface InvoiceRow {
  invoice_number: string;
  invoice_date: string;
  vendor_name: string;
  description: string;
  cost_center: string;
  amount: number;
  currency: string;
  fx_rate: number;
  fx_rate_date: string;
  amount_eur: number;
  is_credit_note: boolean;
  po_number: string | null;
  approved_by: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  response?: AskResponse;
}
