# How this was built

A human-AI collaboration: the author set direction, tested the app and made the calls; Claude Code wrote the code and proposed designs. Prompts below are quoted from the conversation, trimmed, with typos fixed.

## Workflow

| Stage | What happened |
|---|---|
| **1. Look at the data, outline the specs** | After a first look at the data, a brief chat with Claude set out the specs for a CSV-based app, which became a first `CLAUDE.md`: stack, data, endpoints, phased plan |
| **2. Read the policy against the data** | Back in the data, the author went through the policy clause by clause, noting what the data could and couldn't support (prompt below) |
| **3. Refine the spec** | Claude investigated the policy and data and pushed back. The result is the current `CLAUDE.md`: clause registry, guardrails, user settings, lineage |
| **4. Build** | Claude Code built phases 1–4 from the spec, generating five policy-plus-data test questions along the way |
| **5. Test by hand** | The author used the app as a finance user would and reported what felt wrong |
| **6. Design by questions** | Before any more code: how should this handle growing data? Options were debated until a design was agreed |
| **7. Build, verify, repeat** | Changes got tests and live evals, plus browser checks for anything on screen |

Decisions about how the system must behave went back into `CLAUDE.md`, so a future session inherits them.

## Key prompts

**Refining the spec, clause by clause**
> in the apropos project, i am trying to determine what questions that depend on the policy can be routed to functions. routing will also need to be specified in the app.
>
> 2\. for 2.2 the ones with a blank PO, it is sometimes unclear whether they fall under 2.3. please help me understand this ambiguity, and whether there is anything systematic. if it is ambiguous, we need to introduce guardrails.
>
> 3\. can be easily turned into a simple q&a that looks up euro amounts from the table using functions. for 3.1, the "may not be paid" is ambiguous as to whether or not it was paid. one option is to include an option in the GUI to check a box whether to include all or approved invoices only
>
> 4\. 4.1 can be used to write a function that looks up inactive, on hold, or active, but there is no date associated with when they became active/inactive/on hold, so the question can only be answered in the present tense. 4.2-3 are uncheckable using the data and this should be mentioned in the skill
>
> 5\. we should get a sheet with the euro conversion for the dates of the invoices and have a checkbox that governs this -- report in EUR or original currency. the user should also be able to trigger this in the question. 5.2 we cannot get information on early payment discounts from the sheet
>
> 6\. negative amounts processed as credits. i would vote for credits and spends being reported separately. for 6.1 we have no information on escalation so this cannot be answered.
>
> 7\. the app cannot answer related questions because the sheet has no requester. this should be explicit in the answers.
>
> 8\. 8.2 is why we need to show exactly how the data has been transformed and aggregated when the app displays it
>
> 9\. there is no exception register available to us, and we cannot make an assumption if something was an emergency purchase
>
> please account for these in the Claude.Md plan. please investigate the policy and the data and let me know if you have questions and/or pushback.

**Kickoff**
> the CLAUDE.md file has a prototype for building an app based on what is in the data folder. as you're building it, please generate five sample questions about the data that would involve routing between the policy and the database and use them to test the app. please output the results to an md file. please ask for clarification at any point if unsure.

**Audience**
> the answers need to be readable by people not familiar with sql. think finance people. they do not care about the name of the table with euro values. it just needs to say something about conversions. the technical details are in the trace.

**Growing data**
> let me ask you more questions before you do anything. it's fine to build prototypes based on csv, but i do think it's misguided to assume the csv will stay the same. how can we make it scalable with csvs potentially expanding for now? and query system as compatible with a future snowflake deployment as possible?

> what about a hybrid system in which we assume that it's the csvs that will be updated and then loaded into duckdb?

> we should keep the current build-from-csv scheme but make it more flexible -- not needing a fixed number of rows, for example, and assuming that new files will have 2026 and the future. however, the schema must stay the same as is the policy. policy updates and schema updates will have to trigger a broader redesign. we want to make sure that the agent knows about this in the future. please feel free to push back

> quarter should include year by default, it's faulty to assume Q1 always means Q1 of 2025.

**Answer quality**
> whether for 2025 and 2026, are we missing anything on how to measure answer quality and catch hallucinations?

> let's not build anything for production -- this app is not meant to be production, but instead outline it. however, some quick hallucination catches can be built. what are some that are low-hanging fruit here?

> i think these false alarms unnecessarily deter the user from trusting the answer.

**Traceability**
> "aren't answers supposed to have a workflow of e.g. policy --> sql --> policy"? all i am asking here is that the workflow is documented correctly. at the moment, it just seems to state what policy is triggered but it is not in the workflow.

## Key decisions

| Decision | Came from | Outcome |
|---|---|---|
| Report only what the data supports; name what's missing | Author, clause by clause | "Not determinable" answers for §4.2, §4.3, §5.2, §6.1 matching, §7, §9 |
| Blank POs that may fall under §2.3 stay flagged, marked as possible blanket-PO cases | Author raised it; analysis of the data | No auto-exemption; a recurring-service pattern is reported as an observation only |
| Toggles for EUR or original currency and for approved invoices only, overridable in the question | Author | Header controls; the answer shows which applied |
| Credits and spend reported separately | Author | Gross, credit notes and net as three figures |
| Vendor status in the present tense only | Author | No claims about status at invoice time |
| Show exactly how figures were produced (§8.2) | Author | "How this was computed" on answers that used data or the policy |
| Keep rebuilding from CSVs; DuckDB is a disposable copy | Author, after comparing options | No incremental logic; corrections apply on the next load |
| Schema and policy changes require a redesign | Author | Enforced in `contract.py`, a test and `CLAUDE.md` |
| Vendor statuses are part of the contract | Claude's pushback | A new status would otherwise silently skip §4.1 escalation |
| Multi-year handling is the main risk, not row counts | Claude's pushback | Year-aware periods; "Q3" alone would have merged years |
| Drop live reload for now | Claude, retracting its own idea | Restart to load; much simpler |
| Quarters always carry a year | Author | Enforced in storage and the standard filters |
| Cleaning is upstream; the app checks rather than cleans | Author | Bad rows are set aside and reported |
| Production is outlined, not built | Author | See the README |
| Low-noise warnings over strict ones | Author | False alarms traced and removed one cause at a time |
| Trace records the real sequence; no fixed answer format | Author | Policy, data and policy steps in the order they happened |

## Course corrections

Where testing or review changed what had been built:
- **Jargon in answers:** found by using the app; led to a plain-language rule and an eval that fails on system vocabulary.
- **False warnings:** the figure check first flagged numbers the user had typed, then rank columns and simple arithmetic. Running varied questions in bulk exposed the causes.
- **A real catch:** the new checks flagged an answer with a wrong cost-center split, which led to the split always being computed by the backend.

## How the work was verified

- Expected figures come from an independent pandas script, not the app's own functions.
- Tests and evals run on a frozen copy of the data. Evals check the tools called, their arguments, citations and figures.
- Deliberately wrong answers prove the checks catch what they claim to.
- `ROUTING_TEST_RESULTS.md` holds the five policy-plus-data routing questions with answers, sources and the recorded workflow.
