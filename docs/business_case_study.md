# Business Impact Simulation (SIMULATED / ESTIMATED — not real marketplace savings)

**Every number below is a simulation output, not a measured business result.** It shows what a detection-delay improvement would be worth IF the stated assumptions held. Assumptions are listed explicitly so each one can be challenged independently rather than trusting a blended headline number.

## Assumptions

- Reactive baseline detection delay (no proactive monitoring): **10 days** — the assumed time for a deteriorating seller to surface via customer complaints/support escalation.

- Investigator loaded cost: **$45/hour**.

- Reactive (complaint-driven) investigation time: **6 hours/case** (more context-gathering needed — no pre-assembled evidence).

- Proactive (system-flagged) investigation time: **3 hours/case** (anomaly evidence, baseline comparison, and peer-cohort context already assembled by the system).

- Estimated downstream cost per order shipped during an undetected defect episode: **$8** (refund handling, support contacts, goodwill credits).

## Scope note

This simulation covers **45 cases** out of 3,118 total resolved/escalated investigation tickets — only the subset that maps to a KNOWN injected ground-truth episode with a real start date. Applying this framing to every resolved ticket would fabricate a 'days saved' number for tickets that have no actual episode start date to measure against (most resolved tickets are either false positives that got closed, or genuine but non-injected variation); restricting to matched episodes keeps every number below traceable to a specific, known anomaly.

## Without Early Detection vs. With SellerPulse

| Metric | Value |
|---|---|
| Cases simulated | 45 |
| Mean detection days saved per case | 0.9 |
| Orders potentially protected | 208 |
| Customers potentially protected (proxy: 1 order ≈ 1 customer) | 208 |
| GMV exposure avoided (estimated) | $37,684.36 |
| Estimated downstream defect cost avoided | $1,664.00 |
| Investigation hours saved (proactive vs. reactive investigation time) | 135 |
| Investigation cost saved (estimated) | $6,075.00 |

## How to read this

This simulation deliberately does NOT claim these are real savings — there is no production baseline to compare against, only a stated assumption about reactive detection delay. Its value is as a **structured way to reason about the mechanism**: detection speed converts directly into orders/customers not exposed to a known-bad seller for as long, and pre-assembled evidence converts directly into less investigator time per case. A real deployment would replace `10 days`, `$45/hour`, and the investigation-hours assumptions with measured historical values before this framing could be presented as an actual business case.

## Why 'days saved' is modest in this run

Mean days saved is only **0.9** against a 10-day reactive baseline — smaller than a marketing pitch would want. This is a direct, visible consequence of the precision/recall/speed trade-off documented in `docs/evaluation_report.md`: the ensemble's persistence requirement (a signal must repeat across 2+ days before promotion) intentionally trades detection speed for fewer false positives, and mean Ensemble detection delay in the current tuning is ~9.5 days — already close to the assumed reactive baseline. A looser, faster-firing configuration would show a larger 'days saved' number here at the cost of the investigation queue being noisier — that trade-off is real and worth stating plainly rather than picking whichever threshold makes this section look better.
