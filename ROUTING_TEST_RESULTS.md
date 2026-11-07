# Routing test results

Run: 2026-11-07T11:51:50 · model `claude-sonnet-5-5` · settings: report_currency=EUR, approval_scope=all (GUI defaults) · **5/5 passed**

Each question needs both the **policy** (FIN-POL-014, cited via the Citations API) and the **database** (DuckDB tool calls). Expected figures come from `tests/evals/ground_truth.py` (independent pandas computation), not from the app.

| # | Question | Tools called | Result |
|---|---|---|---|
| 1 | How much maverick spend did we have in Q3, and who does the policy say it must be flagged and reported to? | maverick_spend | ✅ pass |
| 2 | Which invoices are missing an approver, what do they total in EUR, and have any of them already been paid? | missing_approval, clause_info | ✅ pass |
| 3 | Which vendors' invoices need to be escalated to Procurement Excellence, and was PharmaPrint already inactive when it invoiced us in March? | invoices_by_vendor_status, invoices_by_vendor_status, clause_info | ✅ pass |
| 4 | Have our credit notes been matched against the original invoices, and what is our net spend after credit notes? | clause_info, spend_summary, credit_notes | ✅ pass |
| 5 | Who had to approve INV-20133 under the approval thresholds, and which exchange rate was used to convert it to EUR? | approval_tier, invoice_lookup | ✅ pass |

---

## 1. How much maverick spend did we have in Q3, and who does the policy say it must be flagged and reported to?

**Expected routing:** Data: maverick_spend (§2.2 flags, Q3 filter or grouping). Policy: §2.2 escalation path (citation). Gap: no Cost Center owner names.

**Tools called (in order):** `maverick_spend`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui"}`  
**Latency:** 6.8 s · **Tokens:** {"input_tokens": 1689, "output_tokens": 647, "cache_read_input_tokens": 26750, "cache_creation_input_tokens": 0}

### Answer

**Q3 maverick spend:** In Q3, **7 invoices** have no PO reference on file (§2.2 flag). Together they total **EUR 300,190.32**. Each is at or above the EUR 1,000 threshold. These are flags, not confirmed violations.

- **Recurring-service annotation:** 5 of the 7 are described as "Cloud hosting" or "Facilities services". They carry a "possible §2.3 recurring service" annotation. Blanket-PO status is not determinable from available data, so all 5 stay flagged.
- **Cost centers:** The flagged invoices sit in CC-FIN-100 (5 invoices) and CC-COM-440 (2 invoices).
- **Missing approver record:** INV-20123 (EUR 27,274.66) also has no approver record. It must be held per §3.1.

**Who it must go to:** Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.

- **Cost Center owner names:** The data has none, so I can't say who the individuals are.
- **Flagging and reporting:** Whether these flags were actually raised or reported is not determinable from available data. The missing records are the flagging record and the Finance Controls Committee reports.
- **Blanket POs:** Recurring services (e.g., cloud hosting, facilities) may operate under a blanket PO, renewed annually. No blanket-PO register is available to confirm this for any of the 5 annotated invoices.

### Not determinable (from clause registry)

- **§2.3** Recurring services may operate under a blanket PO renewed annually: missing blanket-PO register, blanket-PO renewal dates

### Policy citations (Citations API)

- **§2.2**: “2.2 Invoices received without a valid PO reference ("maverick spend") above the EUR 1,000 threshold must be flagged to the Cost Center owner and reported quarterly to the Finance Controls Committee.”
- **§2.3**: “2.3 Recurring services (e.g., cloud hosting, facilities) may operate under a blanket PO, renewed annually.”

### Data sources (tool calls run by the backend)

- `maverick_spend` args `{"filters": {"quarter": "Q3"}, "group_by": "none", "report_currency": null, "approval_scope": null}` → 7 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§2.2' AND TRUE AND i.quarter = 'Q3' ORDER BY i.invoice_number
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: maverick_spend
- ✅ figure maverick_q3_count = 7
- ✅ figure maverick_q3_eur = 300190.32
- ✅ mentions /cost cent(er|re) owner/
- ✅ mentions /finance controls committee/
- ✅ does not say /\b(is|are|constitutes?|were) (a )?(policy )?violations?\b/ (unhedged)
- ✅ does not say /confirmed maverick/ (unhedged)
- ✅ no unverified figures

---

## 2. Which invoices are missing an approver, what do they total in EUR, and have any of them already been paid?

**Expected routing:** Data: missing_approval (§3.1). Policy: §3.1 'must be held and may not be paid'. Gap: payment status → clause_info.

**Tools called (in order):** `missing_approval`, `clause_info`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui"}`  
**Latency:** 8.6 s · **Tokens:** {"input_tokens": 4113, "output_tokens": 1530, "cache_read_input_tokens": 26750, "cache_creation_input_tokens": 0}

### Answer

**25 invoices lack an approver record, totalling EUR 1,057,076.74.** Invoices lacking an approver record must be held and may not be paid. Each of these is therefore "lacks approver record -> must be held per §3.1".

| Invoice | Date | Vendor | Cost center | Amount (EUR) |
|---|---|---|---|---|
| INV-20005 | 2025-03-21 | Helix Consulting AG | CC-FIN-100 | 50,827.14 |
| INV-20015 | 2025-04-18 | MedPack Logistics BV | CC-IT-550 | 13,472.09 |
| INV-20026 | 2025-08-27 | BioReagent Direct | CC-IT-550 | 21,317.61 |
| INV-20031 | 2025-07-26 | MedPack Logistics BV | CC-COM-440 | 14,152.10 |
| INV-20038 | 2025-02-13 | DataBridge Analytics Ltd | CC-OPS-330 | 20,249.63 |
| INV-20042 | 2025-10-14 | Quanta Cloud Services | CC-COM-440 | 52,320.77 |
| INV-20051 | 2025-06-03 | MedPack Logistics BV | CC-RND-210 | 380.92 |
| INV-20053 | 2025-12-10 | ClinSupply Iberia S.L. | CC-FIN-100 | 102,464.89 |
| INV-20055 | 2025-08-11 | BioReagent Direct | CC-FIN-100 | 63,722.06 |
| INV-20056 | 2025-08-04 | PharmaPrint Studios | CC-FIN-100 | 82,190.82 |
| INV-20058 | 2025-10-08 | Stellar Facilities Mgmt | CC-RND-210 | 43,934.49 |
| INV-20060 | 2025-05-18 | BioReagent Direct | CC-COM-440 | 39,046.70 |
| INV-20061 | 2025-09-16 | Labtech Solutions GmbH | CC-COM-440 | 36,787.99 |
| INV-20073 | 2025-01-18 | ClinSupply Iberia S.L. | CC-OPS-330 | 37,031.40 |
| INV-20078 | 2025-06-02 | Stellar Facilities Mgmt | CC-FIN-100 | 43,611.59 |
| INV-20080 | 2025-05-15 | Stellar Facilities Mgmt | CC-COM-440 | 35,241.66 |
| INV-20084 | 2025-06-21 | ClinSupply Iberia S.L. | CC-IT-550 | 10,402.32 |
| INV-20087 | 2025-07-01 | Helix Consulting AG | CC-FIN-100 | 71,011.88 |
| INV-20108 | 2025-07-26 | PharmaPrint Studios | CC-FIN-100 | 35,492.78 |
| INV-20123 | 2025-08-20 | Labtech Solutions GmbH | CC-FIN-100 | 27,274.66 |
| INV-20128 | 2025-04-19 | DataBridge Analytics Ltd | CC-FIN-100 | 16,082.90 |
| INV-20129 | 2025-06-11 | DataBridge Analytics Ltd | CC-OPS-330 | 50,005.74 |
| INV-20134 | 2025-01-14 | MedPack Logistics BV | CC-OPS-330 | 88,734.54 |
| INV-20135 | 2025-12-18 | Helix Consulting AG | CC-FIN-100 | 84,499.63 |
| INV-20136 | 2025-09-22 | PharmaPrint Studios | CC-RND-210 | 16,820.43 |

- **No PO as well:** three of these also have no PO reference on file: INV-20042, INV-20123 and INV-20128. These are §2.2 flags as well.
- **Payment status:** whether any of them have been paid is **not determinable from available data**. The missing fields are payment status and payment date. The data shows only whether an approver record exists, so I can't say whether any invoice was paid or not.

### Not determinable (from clause registry)

- **§3.1** Invoices lacking an approver record must be held and may not be paid: missing payment status, payment date

### Policy citations (Citations API)

- **§3.1**: “Invoices lacking an approver record must be held and may not be paid.”

### Data sources (tool calls run by the backend)

- `missing_approval` args `{"filters": {}, "report_currency": null, "approval_scope": null}` → 25 invoice IDs, 8 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§3.1' AND TRUE ORDER BY i.invoice_number
  ```
  </details>
- `clause_info` args `{"clause": "\u00a73.1"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  clause registry lookup: §3.1
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: missing_approval
- ✅ tool called: clause_info
- ✅ not_determinable: §3.1
- ✅ figure missing_appr_count = 25
- ✅ figure missing_appr_eur = 1057076.74
- ✅ mentions /not determinable/
- ✅ mentions /held/
- ✅ does not say /\b(were|was|has been|have been) paid\b/ (unhedged)
- ✅ does not say /\bunpaid\b/ (unhedged)
- ✅ no unverified figures

---

## 3. Which vendors' invoices need to be escalated to Procurement Excellence, and was PharmaPrint already inactive when it invoiced us in March?

**Expected routing:** Data: invoices_by_vendor_status / vendor_status (§4.1). Policy: §4.1 escalation rule. Gap: status has no effective date → present tense only.

**Tools called (in order):** `invoices_by_vendor_status`, `invoices_by_vendor_status`, `clause_info`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui"}`  
**Latency:** 5.1 s · **Tokens:** {"input_tokens": 3971, "output_tokens": 583, "cache_read_input_tokens": 26750, "cache_creation_input_tokens": 0}

### Answer

Two vendors currently need escalation. Invoices from vendors with status ON_HOLD or INACTIVE must be escalated to Procurement Excellence before processing.

| Vendor | Status now (Vendor Master snapshot, date unknown) | Invoices | Total (EUR) |
|---|---|---|---|
| Crown Travel Partners | ON_HOLD | 12 | 415,550.83 |
| PharmaPrint Studios | INACTIVE | 17 | 1,084,833.66 |

Together that is 29 invoices worth EUR 1,500,384.49.

**Was PharmaPrint already inactive when it invoiced in March?** This is not determinable from available data. The Vendor Master status is a present-day snapshot. It has no effective date or status history, and the missing fields are the vendor status effective date/history and payment records. PharmaPrint Studios is currently INACTIVE (Vendor Master snapshot, date unknown). I can't say when it became inactive.

The data also shows no PharmaPrint Studios invoices dated March 2025. Its invoices fall in other months, for example January, February and April onward. So there is no March invoice to check.

### Not determinable (from clause registry)

- **§4.1 history** Vendor status at invoice time / payments made: missing vendor status effective date / history, payment records
- **§4.1** Payments only to ACTIVE vendors; ON_HOLD / INACTIVE -> escalate to Procurement Excellence: missing vendor status effective date / history, payment records

### Policy citations (Citations API)

- **§4.1**: “Invoices from vendors with status **ON_HOLD** or **INACTIVE** must be escalated to Procurement Excellence before processing.”

### Data sources (tool calls run by the backend)

- `invoices_by_vendor_status` args `{"statuses": ["INACTIVE", "ON_HOLD"], "filters": {}, "report_currency": null, "approval_scope": null}` → 29 invoice IDs, 12 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, v.status AS vendor_status_now FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE v.status IN ('INACTIVE', 'ON_HOLD') AND TRUE ORDER BY i.invoice_number
  ```
  </details>
- `invoices_by_vendor_status` args `{"statuses": ["INACTIVE", "ON_HOLD"], "filters": {"vendor": "PharmaPrint", "date_from": "2025-03-01", "date_to": "2025-03-31"}, "report_currency": null, "approval_scope": null}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, v.status AS vendor_status_now FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE v.status IN ('INACTIVE', 'ON_HOLD') AND TRUE AND (i.vendor_id = 'PharmaPrint' OR i.vendor_name ILIKE '%PharmaPrint%') AND i.invoice_date >= '2025-03-01' AND i.invoice_date <= '2025-03-31' ORDER BY i.invoice_number
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
- ✅ figure esc_count = 29
- ✅ figure pharmaprint_count = 17
- ✅ figure crown_count = 12
- ✅ mentions /currently|current/
- ✅ mentions /snapshot|no effective date|date unknown|not determinable/
- ✅ does not say /PharmaPrint was (already )?inactive in March/ (unhedged)
- ✅ does not say /was inactive when/ (unhedged)
- ✅ no unverified figures

---

## 4. Have our credit notes been matched against the original invoices, and what is our net spend after credit notes?

**Expected routing:** Data: credit_notes + spend_summary (gross / credits / net). Policy: §6.1 matching rule. Gap: no original-invoice reference → clause_info.

**Tools called (in order):** `clause_info`, `spend_summary`, `credit_notes`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui"}`  
**Latency:** 4.1 s · **Tokens:** {"input_tokens": 1084, "output_tokens": 449, "cache_read_input_tokens": 26750, "cache_creation_input_tokens": 0}

### Answer

**Credit note matching:** This is not determinable from available data. Policy §6.1 says negative invoice amounts must be processed as credit notes and matched against the original invoice. It also says unmatched credit notes older than 90 days are escalated to the Finance Director. The data has no original invoice reference, matching status or credit note receipt date. I have not tried to match them by vendor, amount or PO.

There are 2 credit notes, both from Helix Consulting AG:
- INV-20029, dated 2025-11-13: -52,749.39 EUR.
- INV-20096, dated 2025-10-20: -29,534.55 USD, which is -25,340.67 EUR.

**Spend (EUR, all invoices):**
- Gross spend (138 positive invoices): 6,964,721.16 EUR
- Credit notes (2): -78,090.06 EUR
- **Net spend: 6,886,631.10 EUR**

### Not determinable (from clause registry)

- **§6.1 matching** Credit notes matched to original invoice; unmatched > 90 days escalated: missing original invoice reference, matching status, credit note receipt date

### Policy citations (Citations API)

- **§6 Credit Notes & Negative Amounts**: “## 6. Credit Notes & Negative Amounts 6.1 Negative invoice amounts must be processed as credit notes and matched against the original invoice.”
- **§6.1**: “Unmatched credit notes older than 90 days are escalated to the Finance Director.”

### Data sources (tool calls run by the backend)

- `clause_info` args `{"clause": "\u00a76.1 matching"}` → 0 invoice IDs, 0 FX rows  
  <details><summary>query</summary>

  ```sql
  clause registry lookup: §6.1 matching
  ```
  </details>
- `spend_summary` args `{"group_by": "none", "filters": {}, "report_currency": null, "approval_scope": null, "top_n": null}` → 140 invoice IDs, 51 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT count(*) AS invoice_count, count(*) FILTER (WHERE NOT i.is_credit_note) AS positive_invoice_count, count(*) FILTER (WHERE i.is_credit_note) AS credit_note_count, coalesce(sum(i.amount_eur) FILTER (WHERE NOT i.is_credit_note), 0) AS gross, coalesce(sum(i.amount_eur) FILTER (WHERE i.is_credit_note), 0) AS credit_notes, coalesce(sum(i.amount_eur), 0) AS net FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE TRUE ORDER BY 1
  ```
  </details>
- `credit_notes` args `{"filters": {}, "report_currency": null, "approval_scope": null}` → 2 invoice IDs, 1 FX rows  
  <details><summary>query</summary>

  ```sql
  SELECT i.invoice_number, i.invoice_date, i.vendor_id, i.vendor_name, i.description, i.amount_original, i.currency, i.fx_rate, i.fx_rate_date, i.amount_eur, i.is_credit_note, i.cost_center, i.po_number, i.approved_by, i.quarter, f.reason, f.annotation FROM policy_flags f JOIN invoices_eur i USING (invoice_number) WHERE f.clause = '§6.1' AND TRUE ORDER BY i.invoice_number
  ```
  </details>

### Checks

- ✅ status ok
- ✅ tool called: credit_notes | spend_summary
- ✅ tool called: clause_info
- ✅ not_determinable: §6.1 matching
- ✅ figure gross_eur = 6964721.16
- ✅ figure credits_eur = -78090.06
- ✅ figure net_eur = 6886631.1
- ✅ mentions /not determinable/
- ✅ mentions /original invoice reference|original-invoice reference/
- ✅ no unverified figures

---

## 5. Who had to approve INV-20133 under the approval thresholds, and which exchange rate was used to convert it to EUR?

**Expected routing:** Data: approval_tier / invoice_lookup (amount_eur, fx_rate, fx_rate_date). Policy: §3 tier table + §5.1 ECB rule. Gap: approver→role mapping; Good Friday → prior fixing.

**Tools called (in order):** `approval_tier`, `invoice_lookup`  
**Applied settings:** `{"report_currency": "EUR", "approval_scope": "all", "source": "gui"}`  
**Latency:** 4.9 s · **Tokens:** {"input_tokens": 908, "output_tokens": 496, "cache_read_input_tokens": 26750, "cache_creation_input_tokens": 0}

### Answer

**Required approver:** INV-20133 converts to EUR 34,122.32. That falls in the policy band of 5,000.01 – 50,000, so the required approver is the **Department Head**.

The record shows `approved_by` = r.okafor. Whether r.okafor holds the Department Head role is not determinable from available data. The missing field is an approver-to-role mapping.

**Exchange rate:**
- The invoice is for USD 38,762.96 and is dated 2025-04-18.
- The rate used was **1.136 USD per EUR**. That is the ECB fixing from **2025-04-17**, the most recent fixing before the invoice date. The invoice date falls on a weekend or TARGET holiday, so the prior fixing applies.
- This follows policy §5.1: Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.
- The conversion is 38,762.96 / 1.136 = EUR 34,122.32.

### Not determinable (from clause registry)

- **§3** Approval thresholds (required approver tier by EUR value): missing approver -> role mapping

### Policy citations (Citations API)

- **§3 Approval Thresholds**: “Approval Thresholds | Invoice / PO Value (EUR) | Required Approver | |---|---| | Up to 5,000 | Cost Center Owner | | 5,000.01 – 50,000 | Department Head | | 50,000.01 – 250,000 | Finance Director | | Above 250,000 | CFO + Procurement Excellence review |  3.1 Approval is evidenced by the `approved_by` field in the invoice processing system.”
- **§5.1**: “Invoices in other currencies are converted at the ECB reference rate on the invoice date for reporting purposes.”

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
- ✅ not_determinable: §3
- ✅ figure inv20133_eur = 34122.32
- ✅ figure inv20133_rate = 1.136
- ✅ mentions /department head/
- ✅ mentions /2025-04-17|17 April|April 17/
- ✅ no unverified figures
