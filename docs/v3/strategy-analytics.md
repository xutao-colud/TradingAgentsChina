# 战法与收益分析边界

`StrategyOutcomeRecord` links one research report, selected playbook, playbook-fit score, realized/recorded return, and holding period. The aggregated metric may show mean/median return, win rate, and the Pearson association between fit score and outcome return.

## What it can say

- “在 N 条已授权、同一战法结果中，适配分数与收益存在正/负的观察性关联。”
- “当前样本不足，结果仅供探索。”
- “应按市场状态、持有期、标的池和成本模型进一步分组验证。”

## What it cannot say

- “该战法导致收益。”
- “某个用户比其他用户更优秀。”
- “未记录的失败交易不存在。”
- “手工录入收益等同于券商核验收益。”

默认最小样本为 30；在达到阈值后仍需样本外验证、滚动回测、交易成本/滑点、涨跌停与不可成交情形。账户余额和持仓明细不参与跨用户分析。
