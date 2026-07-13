# 战法与收益分析边界

`StrategyOutcomeRecord` links one research report, selected playbook, playbook-fit score, market regime, frozen Agent scores, recorded outcome, and holding period. Aggregation is consent-gated and grouped by playbook plus market regime. It may show mean/median return, a threshold-gated positive-outcome proportion, and the Pearson association between fit score and outcome return.

## What it can say

- “在 N 条已授权、同一战法结果中，适配分数与收益存在正/负的观察性关联。”
- “当前样本不足，结果仅供探索。”
- “应按市场状态、持有期、标的池和成本模型进一步分组验证。”

## What it cannot say

- “该战法导致收益。”
- “某个用户比其他用户更优秀。”
- “未记录的失败交易不存在。”
- “手工录入收益等同于券商核验收益。”

默认最小样本为 30；样本不足时不展示正收益比例或 Agent 方向一致率。在达到阈值后仍需样本外验证、滚动回测、交易成本/滑点、涨跌停与不可成交情形。账户余额和持仓明细不参与跨用户分析。

`summarize_agent_reputation` 仅描述冻结 Agent 分数方向与后续记录结果的一致性，并按市场状态分组；它不是预测准确率、不是因果证明，也不能自动改变 Agent 权重。
