# Routing test results

Run: 2026-11-08T15:54:19 · model `claude-sonnet-5-5` · settings: report_currency=EUR, approval_scope=all (GUI defaults) · **5/5 passed**

Each question needs both the **policy** (FIN-POL-014, cited via the Citations API) and the **database** (DuckDB tool calls). Expected figures come from `tests/evals/ground_truth.py` (independent pandas computation), not from the app.

| # | Question | Tools called | Result |
|---|---|---|---|
| 1 | How much maverick spend did we have in Q3, and who does the policy say it must be flagged and reported to? | maverick_spend | ✅ pass |
| 2 | Which invoices are missing an approver, what do they total in EUR, and have any of them already been paid? | missing_approval, clause_info | ✅ pass |
| 3 | Which vendors' invoices need to be escalated to Procurement Excellence, and was PharmaPrint already inactive when it invoiced us in March? | invoices_by_vendor_status, vendor_status, clause_info | ✅ pass |
| 4 | Have our credit notes been matched against the original invoices, and what is our net spend after credit notes? | clause_info, spend_summary, credit_notes | ✅ pass |
| 5 | Who had to approve INV-20133 under the approval thresholds, and which exchange rate was used to convert it to EUR? | approval_tier, invoice_lookup | ✅ pass |

---

## 1. How much maverick spend did we have in Q3, and who does the policy say it must be flagged and reported to?

**Expected routing:** Data: maverick_spend (§2.2 flags, Q3 filter or grouping). Policy: §2.2 escalation path (citation). Gap: no Cost Center owner names.

**Tools called (in order):** `maverick_spend`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui", "period": "2025-Q3"}`  
**Latency:** 7.5 s · **Tokens:** {"input_tokens": 1879, "output_tokens": 1009, "cache_read_input_tokens": 31990, "cache_creation_input_tokens": 0}

### Answer

**Q3 2025 had 7 invoices with no PO reference on file (§2.2 flags), totalling EUR 300,190.32.** These are flags, not confirmed violations. Amounts are converted to EUR at the ECB rate on the invoice date.

**By cost center**
- CC-FIN-100: 5 invoices, EUR 202,133.15
- CC-COM-440: 2 invoices, EUR 98,057.17

**Who it must be flagged and reported to**
Invoices received without a valid PO reference above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee. [§2.2]

- The data holds no Cost Center owner names, so I can't say who the individual owners are.
- The data does not show whether the flags were raised or reported. That is not determinable from available data.

**Recurring services (§2.3)**
Recurring services (e.g., cloud hosting, facilities) may operate under a blanket PO, renewed annually. [§2.3] 5 of the 7 flagged invoices are cloud hosting or facilities services, so they are possibly recurring services that could sit under a blanket PO. Whether a blanket PO exists is not determinable from available data, so all 7 stay flagged.

**Flagged invoices**
| Invoice | Date | Vendor | Cost center | EUR equivalent |
|---|---|---|---|---|
| INV-20012 | 2025-08-17 | Quanta Cloud Services | CC-FIN-100 | 11,653.62 |
| INV-20057 | 2025-09-05 | MedPack Logistics BV | CC-FIN-100 | 41,722.17 |
| INV-20067 | 2025-09-10 | PharmaPrint Studios | CC-COM-440 | 92,908.70 |
| INV-20077 | 2025-07-06 | Crown Travel Partners | CC-COM-440 | 5,148.47 |
| INV-20089 | 2025-07-14 | BioReagent Direct | CC-FIN-100 | 26,827.36 |
| INV-20113 | 2025-09-15 | Helix Consulting AG | CC-FIN-100 | 94,655.34 |
| INV-20123 | 2025-08-20 | Labtech Solutions GmbH | CC-FIN-100 | 27,274.66 |

INV-20123 also has no approver on record, so it must be held under §3.1.

### Workflow (as recorded)

1. **Policy: Rule being checked**: §2.2: invoices without a valid PO reference above EUR 1,000 must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee, so Q3 flags need listing.
2. **Data: Invoices without a PO**: 7 invoices · EUR 300,190.32 · 2025-Q3
3. **Policy: Policy applied in the answer**: §2.2: 2.2 Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.
4. **Policy: Policy applied in the answer**: §2.3: 2.3 Recurring services (e.g., cloud hosting, facilities) may operate under a blanket PO, renewed annually.
5. **Policy: Not determinable**: §2.3 Recurring services may operate under a blanket PO renewed annually. Missing: blanket-PO register, blanket-PO renewal dates

### Not determinable (from clause registry)

- **§2.3** Recurring services may operate under a blanket PO renewed annually: missing blanket-PO register, blanket-PO renewal dates

### Policy citations (Citations API)

- **§2.2**: “2.2 Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.”
- **§2.3**: “2.3 Recurring services (e.g., cloud hosting, facilities) may operate under a blanket PO, renewed annually.”

### Data sources (tool calls run by the backend)

- `maverick_spend` args `{"filters": {"quarter": "2025-Q3"}, "group_by": "none", "report_currency": null, "approval_scope": null}` → 7 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§2.2' AND TRUE AND i.quarter = '2025-Q3' ORDER BY i.invoice_number
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: maverick_spend
- ✅ tool arguments: [{'tool': 'maverick_spend', 'filters': {'quarter': '2025-Q3'}}, {'tool': 'maverick_spend', 'group_by': 'quarter'}]
- ✅ cites: §2.2
- ✅ workflow shows policy before and after the data
- ✅ figure maverick_q3_count = 7
- ✅ figure maverick_q3_eur = 300190.32
- ✅ mentions /cost cent(er|re) owner/
- ✅ mentions /finance controls committee/
- ✅ mentions /2025/
- ✅ does not say /\b(is|are|constitutes?|were) (a )?(policy )?violations?\b/ (unhedged)
- ✅ does not say /confirmed maverick/ (unhedged)
- ✅ plain language (no system jargon)
- ✅ no unverified figures
- ✅ answer checks clean

---

## 2. Which invoices are missing an approver, what do they total in EUR, and have any of them already been paid?

**Expected routing:** Data: missing_approval (§3.1). Policy: §3.1 'must be held and may not be paid'. Gap: payment status → clause_info.

**Tools called (in order):** `missing_approval`, `clause_info`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui", "period": "2025"}`  
**Latency:** 9.5 s · **Tokens:** {"input_tokens": 4179, "output_tokens": 1649, "cache_read_input_tokens": 31990, "cache_creation_input_tokens": 0}

### Answer

**In 2025, 25 invoices have no approver on record. Together they total EUR 1,057,076.74.** Amounts are converted to EUR at the ECB rate on the invoice date. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes. [§5.1] Invoices lacking an approver record must be held and may not be paid. [§3.1] So these 25 must be held under §3.1.

**Payment status:** whether any of them have been paid is not determinable from available data. The invoice data has no payment status or payment date.

| Invoice | Date | Vendor | EUR equivalent | PO number |
|---|---|---|---|---|
| INV-20005 | 2025-03-21 | Helix Consulting AG | 50,827.14 | PO-79125 |
| INV-20015 | 2025-04-18 | MedPack Logistics BV | 13,472.09 | PO-71235 |
| INV-20026 | 2025-08-27 | BioReagent Direct | 21,317.61 | PO-71137 |
| INV-20031 | 2025-07-26 | MedPack Logistics BV | 14,152.10 | PO-71193 |
| INV-20038 | 2025-02-13 | DataBridge Analytics Ltd | 20,249.63 | PO-76906 |
| INV-20042 | 2025-10-14 | Quanta Cloud Services | 52,320.77 | none on file |
| INV-20051 | 2025-06-03 | MedPack Logistics BV | 380.92 | PO-73792 |
| INV-20053 | 2025-12-10 | ClinSupply Iberia S.L. | 102,464.89 | PO-79798 |
| INV-20055 | 2025-08-11 | BioReagent Direct | 63,722.06 | PO-74722 |
| INV-20056 | 2025-08-04 | PharmaPrint Studios | 82,190.82 | PO-73073 |
| INV-20058 | 2025-10-08 | Stellar Facilities Mgmt | 43,934.49 | PO-74781 |
| INV-20060 | 2025-05-18 | BioReagent Direct | 39,046.70 | PO-75272 |
| INV-20061 | 2025-09-16 | Labtech Solutions GmbH | 36,787.99 | PO-72068 |
| INV-20073 | 2025-01-18 | ClinSupply Iberia S.L. | 37,031.40 | PO-72531 |
| INV-20078 | 2025-06-02 | Stellar Facilities Mgmt | 43,611.59 | PO-76984 |
| INV-20080 | 2025-05-15 | Stellar Facilities Mgmt | 35,241.66 | PO-75120 |
| INV-20084 | 2025-06-21 | ClinSupply Iberia S.L. | 10,402.32 | PO-75585 |
| INV-20087 | 2025-07-01 | Helix Consulting AG | 71,011.88 | PO-73770 |
| INV-20108 | 2025-07-26 | PharmaPrint Studios | 35,492.78 | PO-73060 |
| INV-20123 | 2025-08-20 | Labtech Solutions GmbH | 27,274.66 | none on file |
| INV-20128 | 2025-04-19 | DataBridge Analytics Ltd | 16,082.90 | none on file |
| INV-20129 | 2025-06-11 | DataBridge Analytics Ltd | 50,005.74 | PO-75608 |
| INV-20134 | 2025-01-14 | MedPack Logistics BV | 88,734.54 | PO-74742 |
| INV-20135 | 2025-12-18 | Helix Consulting AG | 84,499.63 | PO-71845 |
| INV-20136 | 2025-09-22 | PharmaPrint Studios | 16,820.43 | PO-71421 |

Three of these invoices also have no PO reference on file: INV-20042, INV-20123 and INV-20128. Each is also a §2.2 flag, because each is above EUR 1,000. Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee. [§2.2]

### Workflow (as recorded)

1. **Policy: Rule being checked**: §3.1: invoices lacking an approver record must be held and may not be paid, so these need listing.
2. **Data: Invoices without an approver**: 25 invoices · EUR 1,057,076.74 · 2025
3. **Policy: Checked what the data can show**: §3.1 payment status
4. **Policy: Policy applied in the answer**: §5.1: 5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.
5. **Policy: Policy applied in the answer**: §3.1: 3.1 Approval is evidenced by the `approved_by` field in the invoice processing system. Invoices lacking an approver record must be held and may not be paid.
6. **Policy: Policy applied in the answer**: §2.2: 2.2 Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.
7. **Policy: Not determinable**: §3.1 Invoices lacking an approver record must be held and may not be paid. Missing: payment status, payment date

### Not determinable (from clause registry)

- **§3.1** Invoices lacking an approver record must be held and may not be paid: missing payment status, payment date

### Policy citations (Citations API)

- **§5.1**: “5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.”
- **§3.1**: “3.1 Approval is evidenced by the `approved_by` field in the invoice processing system. Invoices lacking an approver record must be held and may not be paid.”
- **§2.2**: “2.2 Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.”

### Data sources (tool calls run by the backend)

- `missing_approval` args `{"filters": {"year": "2025"}, "report_currency": null, "approval_scope": null}` → 25 invoice IDs, 8 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§3.1' AND TRUE AND i.invoice_year = 2025 ORDER BY i.invoice_number
  ```
  </details>
- `clause_info` args `{"clause": "\u00a73.1 payment status"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  clause registry lookup: §3.1 payment status
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: missing_approval
- ✅ tool called: clause_info
- ✅ cites: §3.1
- ✅ workflow shows policy before and after the data
- ✅ not_determinable: §3.1
- ✅ figure missing_appr_count = 25
- ✅ figure missing_appr_eur = 1057076.74
- ✅ mentions /not determinable/
- ✅ mentions /held/
- ✅ does not say /\b(were|was|has been|have been) paid\b/ (unhedged)
- ✅ does not say /\bunpaid\b/ (unhedged)
- ✅ plain language (no system jargon)
- ✅ no unverified figures
- ✅ answer checks clean

---

## 3. Which vendors' invoices need to be escalated to Procurement Excellence, and was PharmaPrint already inactive when it invoiced us in March?

**Expected routing:** Data: invoices_by_vendor_status / vendor_status (§4.1). Policy: §4.1 escalation rule. Gap: status has no effective date → present tense only.

**Tools called (in order):** `invoices_by_vendor_status`, `vendor_status`, `clause_info`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui", "period": "2025"}`  
**Latency:** 6.6 s · **Tokens:** {"input_tokens": 4053, "output_tokens": 787, "cache_read_input_tokens": 31990, "cache_creation_input_tokens": 0}

### Answer

**Two vendors' invoices need escalation to Procurement Excellence for 2025.** Under the policy, invoices from vendors with status ON_HOLD or INACTIVE must be escalated to Procurement Excellence before processing. [§4.1] There are 29 such invoices, totalling EUR 1,500,384.49.

| Vendor | Status currently (Vendor Master snapshot, date unknown) | Invoices | Total (EUR equivalent) |
|---|---|---|---|
| PharmaPrint Studios | Inactive | 17 | 1,084,833.66 |
| Crown Travel Partners | On hold | 12 | 415,550.83 |

**Was PharmaPrint already inactive when it invoiced in March?** This is not determinable from available data.
- PharmaPrint Studios is currently inactive, according to a Vendor Master snapshot with no date.
- The Vendor Master has no effective date or status history. It therefore can't show what the vendor's status was when any invoice was issued.
- The data also has no payment records, so I can't say whether any payment was made.
- None of PharmaPrint's 17 flagged invoices is dated March 2025. Its invoices fall in other months, for example 9 January, 1 February and 5 April. If you mean a different invoice, send me the invoice number and I'll check it.

### Workflow (as recorded)

1. **Policy: Rule being checked**: §4.1: invoices from vendors that are on hold or inactive must be escalated to Procurement Excellence before processing.
2. **Data: Invoices by vendor status**: 29 invoices · EUR 1,500,384.49 · 2025
3. **Policy: Rule being checked**: §4.1: only ACTIVE vendors may be paid; need PharmaPrint's current status.
4. **Data: Vendor status**
5. **Policy: Checked what the data can show**: §4.1
6. **Policy: Policy applied in the answer**: §4.1: 4.1 Payments may only be made to vendors with **ACTIVE** status in the Vendor Master. Invoices from vendors with status **ON_HOLD** or **INACTIVE** must be escalated to Procurement Excellence before processing.
7. **Policy: Not determinable**: §4.1 history Vendor status at invoice time / payments made. Missing: vendor status effective date / history, payment records
8. **Policy: Not determinable**: §4.1 Payments only to ACTIVE vendors; ON_HOLD / INACTIVE -> escalate to Procurement Excellence. Missing: vendor status effective date / history, payment records

### Not determinable (from clause registry)

- **§4.1 history** Vendor status at invoice time / payments made: missing vendor status effective date / history, payment records
- **§4.1** Payments only to ACTIVE vendors; ON_HOLD / INACTIVE -> escalate to Procurement Excellence: missing vendor status effective date / history, payment records

### Policy citations (Citations API)

- **§4.1**: “4.1 Payments may only be made to vendors with **ACTIVE** status in the Vendor Master. Invoices from vendors with status **ON_HOLD** or **INACTIVE** must be escalated to Procurement Excellence before processing.”

### Data sources (tool calls run by the backend)

- `invoices_by_vendor_status` args `{"statuses": ["INACTIVE", "ON_HOLD"], "filters": {"year": "2025"}, "report_currency": null, "approval_scope": null}` → 29 invoice IDs, 12 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, v.status AS vendor_status_now FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE v.status IN ('INACTIVE', 'ON_HOLD') AND TRUE AND i.invoice_year = 2025 ORDER BY i.invoice_number
  ```
  </details>
- `vendor_status` args `{"vendor": "PharmaPrint"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT vendor_id, vendor_name, country, category, status FROM vendors WHERE vendor_id = 'PharmaPrint' OR vendor_name ILIKE '%PharmaPrint%' ORDER BY vendor_id
  ```
  </details>
- `clause_info` args `{"clause": "\u00a74.1"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  clause registry lookup: §4.1
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: invoices_by_vendor_status | vendor_status
- ✅ cites: §4.1
- ✅ workflow shows policy before and after the data
- ✅ figure esc_count = 29
- ✅ figure pharmaprint_count = 17
- ✅ figure crown_count = 12
- ✅ mentions /currently|current/
- ✅ mentions /snapshot|no effective date|date unknown|not determinable/
- ✅ does not say /PharmaPrint was (already )?inactive in March/ (unhedged)
- ✅ does not say /was inactive when/ (unhedged)
- ✅ plain language (no system jargon)
- ✅ no unverified figures
- ✅ answer checks clean

---

## 4. Have our credit notes been matched against the original invoices, and what is our net spend after credit notes?

**Expected routing:** Data: credit_notes + spend_summary (gross / credits / net). Policy: §6.1 matching rule. Gap: no original-invoice reference → clause_info.

**Tools called (in order):** `clause_info`, `spend_summary`, `credit_notes`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui", "period": "2025"}`  
**Latency:** 5.2 s · **Tokens:** {"input_tokens": 1232, "output_tokens": 607, "cache_read_input_tokens": 31990, "cache_creation_input_tokens": 0}

### Answer

**Credit note matching: not determinable from available data.** The policy requires negative invoice amounts to be processed as credit notes and matched against the original invoice, and unmatched credit notes older than 90 days are escalated to the Finance Director. [§6.1] The invoice data has no original invoice reference, no matching status and no credit note receipt date. I haven't matched any credit notes by vendor, amount or PO, because that would be a guess.

**Net spend for 2025 (in EUR, converted at the ECB rate on the invoice date per §5.1 [§5.1]):**

| | EUR |
|---|---|
| Gross spend (138 invoices) | 6,964,721.16 |
| Credit notes (2) | -78,090.06 |
| **Net spend** | **6,886,631.10** |

The two credit notes are both from Helix Consulting AG:
- INV-20029, dated 13 Nov 2025: -52,749.39 EUR (cloud hosting).
- INV-20096, dated 20 Oct 2025: -29,534.55 USD, which is -25,340.67 EUR.

### Workflow (as recorded)

1. **Policy: Checked what the data can show**: §6.1 matching
2. **Policy: Rule being checked**: §6.1: negative amounts are processed as credit notes; net spend = gross invoices plus credit notes.
3. **Data: Spend totals**: net EUR 6,886,631.10 · 2025
4. **Policy: Rule being checked**: §6.1: negative amounts must be processed as credit notes and matched to the original invoice.
5. **Data: Credit notes**: 2 invoices · EUR -78,090.06 · 2025
6. **Policy: Policy applied in the answer**: §6.1: 6.1 Negative invoice amounts must be processed as credit notes and matched against the original invoice. Unmatched credit notes older than 90 days are escalated to the Finance Director.
7. **Policy: Policy applied in the answer**: §5.1: 5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.
8. **Policy: Not determinable**: §6.1 matching Credit notes matched to original invoice; unmatched > 90 days escalated. Missing: original invoice reference, matching status, credit note receipt date

### Not determinable (from clause registry)

- **§6.1 matching** Credit notes matched to original invoice; unmatched > 90 days escalated: missing original invoice reference, matching status, credit note receipt date

### Policy citations (Citations API)

- **§6.1**: “6.1 Negative invoice amounts must be processed as credit notes and matched against the original invoice. Unmatched credit notes older than 90 days are escalated to the Finance Director.”
- **§5.1**: “5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.”

### Data sources (tool calls run by the backend)

- `clause_info` args `{"clause": "\u00a76.1 matching"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  clause registry lookup: §6.1 matching
  ```
  </details>
- `spend_summary` args `{"group_by": "none", "filters": {"year": "2025"}, "report_currency": null, "approval_scope": null, "top_n": null}` → 140 invoice IDs, 51 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT count(i.amount_eur) AS invoice_count, count(i.amount_eur) FILTER (WHERE NOT i.is_credit_note) AS positive_invoice_count, count(i.amount_eur) FILTER (WHERE i.is_credit_note) AS credit_note_count, coalesce(sum(i.amount_eur) FILTER (WHERE NOT i.is_credit_note), 0) AS gross, coalesce(sum(i.amount_eur) FILTER (WHERE i.is_credit_note), 0) AS credit_notes, coalesce(sum(i.amount_eur), 0) AS net FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE TRUE AND i.invoice_year = 2025 ORDER BY 1
  ```
  </details>
- `credit_notes` args `{"filters": {"year": "2025"}, "report_currency": null, "approval_scope": null}` → 2 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§6.1' AND TRUE AND i.invoice_year = 2025 ORDER BY i.invoice_number
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: credit_notes | spend_summary
- ✅ tool called: clause_info
- ✅ cites: §6.1
- ✅ workflow shows policy before and after the data
- ✅ not_determinable: §6.1 matching
- ✅ figure gross_eur = 6964721.16
- ✅ figure credits_eur = -78090.06
- ✅ figure net_eur = 6886631.1
- ✅ mentions /not determinable/
- ✅ mentions /original.invoice/
- ✅ plain language (no system jargon)
- ✅ no unverified figures
- ✅ answer checks clean

---

## 5. Who had to approve INV-20133 under the approval thresholds, and which exchange rate was used to convert it to EUR?

**Expected routing:** Data: approval_tier / invoice_lookup (amount_eur, fx_rate, fx_rate_date). Policy: §3 tier table + §5.1 ECB rule. Gap: approver→role mapping; Good Friday → prior fixing.

**Tools called (in order):** `approval_tier`, `invoice_lookup`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui", "period": null}`  
**Latency:** 5.2 s · **Tokens:** {"input_tokens": 1036, "output_tokens": 564, "cache_read_input_tokens": 31990, "cache_creation_input_tokens": 0}

### Answer

**Required approver: Department Head.** INV-20133 is for USD 38,762.96. Converted to EUR, that is EUR 34,122.32. Invoices of 5,000.01 – 50,000 EUR require the Department Head as approver. [§3] The approver on record is r.okafor. The invoice data does not record approvers' roles, so whether r.okafor holds that role is not determinable from available data.

**Exchange rate: 1.136 USD per 1 EUR.**
- Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes. [§5.1]
- The invoice is dated 18 April 2025. The ECB rate used is dated 17 April 2025, because the ECB publishes no rate on some days, including some holidays. On those days the most recent earlier rate applies.
- USD 38,762.96 at 1.136 gives EUR 34,122.32.

### Workflow (as recorded)

1. **Policy: Rule being checked**: §3: required approver depends on the invoice's EUR value.
2. **Data: Required approvers**: 1 invoice
3. **Policy: Rule being checked**: §5.1: non-EUR invoices are converted at the ECB reference rate on the invoice date.
4. **Data: Invoice details**: 1 invoice
5. **Policy: Policy applied in the answer**: §3 Approval Thresholds: ## 3. Approval Thresholds
| Invoice / PO Value (EUR) | Required Approver |
|---|---|
| Up to 5,000 | Cost Center Owner |
| 5,000.01 – 50,000 | Department Head |
| 50,000.01 – 250,000 | Finance Director |
| Above 250,000 | CFO + Procurement Excellence review |
6. **Policy: Policy applied in the answer**: §5.1: 5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.
7. **Policy: Not determinable**: §3 Approval thresholds (required approver tier by EUR value). Missing: record of each approver's role

### Not determinable (from clause registry)

- **§3** Approval thresholds (required approver tier by EUR value): missing record of each approver's role

### Policy citations (Citations API)

- **§3 Approval Thresholds**: “## 3. Approval Thresholds | Invoice / PO Value (EUR) | Required Approver | |---|---| | Up to 5,000 | Cost Center Owner | | 5,000.01 – 50,000 | Department Head | | 50,000.01 – 250,000 | Finance Director | | Above 250,000 | CFO + Procurement Excellence review |”
- **§5.1**: “5.1 The Group reporting currency is **EUR**. Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.”

### Data sources (tool calls run by the backend)

- `approval_tier` args `{"filters": {"invoice_numbers": ["INV-20133"]}, "report_currency": null, "approval_scope": null}` → 1 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by FROM invoices_eur i WHERE TRUE AND i.invoice_number IN ('INV-20133') ORDER BY i.invoice_number
  ```
  </details>
- `invoice_lookup` args `{"filters": {"invoice_numbers": ["INV-20133"]}, "report_currency": null, "approval_scope": null, "limit": 50}` → 1 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, v.status AS vendor_status_now, v.category AS vendor_category, (SELECT list(f.clause ORDER BY f.clause) FROM policy_flags f WHERE f.invoice_number = i.invoice_number) AS policy_flags FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE TRUE AND i.invoice_number IN ('INV-20133') ORDER BY i.invoice_number LIMIT 50
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: approval_tier | invoice_lookup
- ✅ tool arguments: [{'tool': 'approval_tier', 'filters': {'invoice_numbers': ['INV-20133']}}, {'tool': 'invoice_lookup', 'filters': {'invoice_numbers': ['INV-20133']}}]
- ✅ cites: §3
- ✅ cites: §5.1
- ✅ workflow shows policy before and after the data
- ✅ not_determinable: §3
- ✅ figure inv20133_eur = 34122.32
- ✅ figure inv20133_rate = 1.136
- ✅ mentions /department head/
- ✅ mentions /2025-04-17|17 Apr(il)?\b|Apr(il)? 17/
- ✅ plain language (no system jargon)
- ✅ no unverified figures
- ✅ answer checks clean
