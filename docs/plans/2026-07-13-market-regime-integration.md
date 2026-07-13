# Market regime integration repair

## Goal

Replace the empty Tushare market context with traceable whole-market breadth,
limit-pool history, dynamic sentiment, optional policy themes, and blocking data
quality semantics.

## Implementation

1. Add configuration for provider interfaces, observation window, limit codes,
   policy keywords, and quality minimums.
2. Collect index calendar rows, whole-market daily rows, and limit-pool rows for
   each selected trading day.
3. Calculate advance/decline breadth, turnover, failed-board rate, board height,
   prior limit-up premium, and second-board promotion without an LLM.
4. Persist raw responses, validate normalized observations, and withhold
   `market-001` when the sequence is incomplete.
5. Make market skills reject missing values rather than scoring them as zero.
6. Verify the successful and entitlement-failure paths with provider and full
   workflow tests.
