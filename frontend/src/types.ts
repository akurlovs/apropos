export type ReportCurrency = "EUR" | "original";
export type ApprovalScope = "all" | "approved_only";
export interface Settings {
  report_currency: ReportCurrency;
  approval_scope: ApprovalScope;
  year: string; // "latest", "all" or a calendar year
}

export interface RatePending {
  count: number;
  invoice_numbers: string[];
  note?: string;
}

export interface FileLoad {
  file: string;
  year: number;
  rows_read: number;
  rows_loaded: number;
  rows_rejected: number;
  date_from: string | null;
  date_to: string | null;
}

export interface DataStatus {
  state: "ready" | "failed";
  message: string | null;
  redesign_needed: boolean;
  loaded_at?: string;
  policy?: string;
  files?: FileLoad[];
  ignored_files?: string[];
  invoices_loaded?: number;
  rejected_count?: number;
  rejected?: { file: string; csv_line: number; invoice_number: string | null; reason: string }[];
  rate_pending?: RatePending;
  fx_latest_date?: string | null;
  years?: number[];
  latest_year?: number;
  latest_year_through?: string;
}

export interface FxRow {
  invoice_number: string;
  currency: string;
  amount_original: number;
  fx_rate: number | null;
  fx_rate_date: string | null;
  amount_eur: number | null;
}

export interface SourceFile {
  file: string;
  sha256: string;
}

export interface DataSource {
  tool: string;
  label: string;
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
  period: string | null;
}

export interface WorkflowStep {
  step: "policy" | "data";
  label: string;
  text?: string;
  source?: number;
  result?: string;
}

export interface AnswerWarning {
  check: string;
  message: string;
  items: string[];
}

export interface AskResponse {
  answer: string;
  status: "ok" | "error";
  applied_settings: AppliedSettings | null;
  data_sources: DataSource[];
  not_determinable: NotDeterminable[];
  policy_citations: Citation[];
  unverified_figures: string[];
  answer_warnings: AnswerWarning[];
  workflow: WorkflowStep[];
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
  rate_pending?: RatePending;
  cross_currency_total_eur?: { label: string; gross: number; credit_notes: number; net: number };
}

export interface Summary {
  settings: Settings;
  period: string | null;
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
  fx_rate: number | null;
  fx_rate_date: string | null;
  amount_eur: number | null;
  is_credit_note: boolean;
  po_number: string | null;
  approved_by: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  response?: AskResponse;
}
