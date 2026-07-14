# Opportunity Scanner Audit and Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将现有机会池改造成时点一致、入口一致、批量高效、可回放且严格遵守市场优先原则的生产级三级扫描流水线。

**Architecture:** 以不可变 `ScanRunContext` 固化分析日期、运行模式、市场状态、配置版本和 TradingProfile 版本；候选发现、调度优先级、机会证据、战法适配和生命周期分别建模。L1 使用批量快照，L2 按战法数据契约执行定向研究，L3 只消费已通过质量门槛的不可变研究包并进行法庭式质证。

**Tech Stack:** Python 3.13、dataclasses、现有 `MarketDataProvider`、Tushare/AkShare/Eastmoney、JSONL 本地记忆、PostgreSQL 15+ RLS、`unittest`。

---

## 1. 审计范围与结论

审计链路：

```text
CLI / Web / MCP
  -> OpportunityPipeline.run
  -> 市场状态 + 候选来源
  -> L1 快照与评分
  -> L2 全量 ResearchWorkflow
  -> L3 投资委员会
  -> 本地机会池 / 分析事件 / SaaS 迁移结构
```

结论：现有实现已经具备可运行骨架和严格的 L3 数据不足阻断，但还不是生产级扫描器。最严重的问题不是缺少更多指标，而是时点、评分语义、入口一致性和批量数据契约没有完全闭环。

### 已经正确的部分

- L1 不调用 LLM；L2 与 L3 复用同一 `ResearchState`，避免 L3 重复拉数。
- 市场数据为 `unavailable`、`insufficient` 或 `sample` 时会阻止 L3。
- L2/L3 报告和机会池均可持久化，机会分明确声明不是胜率。
- L3 调用现有法庭式委员会，而不是简单等权投票。
- 生产 Provider 不回退到 Sample Provider。
- 204 项现有回归测试通过。

## 2. 风险清单

### P0-1：历史扫描可能混入当前实时数据

证据：

- `OpportunityPipeline.run()` 接收任意 `analysis_date`，但快照客户端使用 `datetime.now()`。
- 雷达同样使用当前时间，没有校验与 `analysis_date` 是否属于同一交易日。
- Web、CLI、MCP 没有统一解析日期、未来日期和 live/historical 模式。

影响：历史回放或补跑可能把今天的价格、资金流和雷达候选写进过去日期的机会池，形成前视偏差。

### P0-2：机会分、调度优先级和生命周期语义混在一起

证据：L1 总分同时包含 `source_priority`、数据覆盖、流动性、资金、涨跌和用户主题偏好；`_lifecycle()` 再把该总分命名为 watch/start/accelerate/climax/retreat。

影响：用户将股票加入持仓、修改自选或改变偏好，也可能造成“启动/高潮/退潮”；这不是市场生命周期，不能作为真实行情证据。

### P0-3：三个入口的扫描行为不一致

证据：

- CLI 和 Web 注入 `EastmoneyStockSnapshotClient`。
- MCP 创建 Pipeline 时没有注入快照客户端，L1 直接退化为逐股 Provider 查询。
- sample 模式的 CLI/Web 仍可能先调用真实 Eastmoney 快照，造成真实 L1 与样例 L2 混合。

影响：同样参数从不同入口调用，响应时间、来源和结果可能不同。

### P0-4：市场优先只在 L3 完整生效

证据：市场状态进入 L1 证据和风险提示，但不参与 L1 机会质量与战法路由；市场不可用时仍执行昂贵 L2，真正的市场战法门槛直到 L2 Skills 阶段才运行。

影响：候选排序没有按当前市场允许的战法改变，且市场不可用时仍浪费深度数据请求。

### P0-5：L1 证据链不足以证明数据来源

证据：L1 使用合成的 `opportunity-snapshot:*` 和 `opportunity-market:*` 标识；Provider fallback 把价格、资料和资金数据压进一个快照，却没有保留各自的原始快照 ID、质量报告和独立时间。

影响：用户可以看到数值，但不能可靠追溯每个数值来自哪个接口、原始快照和交易时间。

### P1-1：当前不是全市场机会扫描

候选只来自持仓、自选、手工输入和雷达 `fast_movers`。没有覆盖全市场的批量预筛，也没有行业强度、涨停梯队、异常成交或公告事件候选适配器。

### P1-2：L1 最坏可产生 2N 公共请求

`EastmoneyStockSnapshotClient` 每只股票请求一次行情和一次资金流；配置上限 160 只意味着最多约 320 次公共请求。快照失败后，Pipeline 又按股票顺序调用价格、资料和资金 Provider。

### P1-3：L2 是固定的全量数据扇出

每个 L2 候选都会调用完整 `_collect_data()`，至少触发 14 个 Provider 方法；市场状态也会按候选重复查询。当前最多 12 个候选且串行执行，没有运行预算、超时截止、缓存命中指标或按战法裁剪数据集。

### P1-4：L1 数据质量门槛过粗

覆盖率只要求价格、涨跌幅、成交额和换手率。资金流可以缺失，实时快照也没有逐字段质量与时间容差；Provider fallback 只要有日线就标记为 `latest_available`。

### P1-5：持久化不是一个完整事务

- L2/L3 分析事件先写，机会池最后写，失败时会出现孤儿分析事件。
- run id 在末尾创建，L2/L3 metadata 没有稳定的 pool run id。
- 最新快照原子替换，但 JSONL append 没有文件锁；Web 使用线程服务器，并发扫描可能交错写入。
- replay 只返回池快照，不联取 L2/L3 原始报告，因此不是完整证据回放。

### P1-6：同步 API 缺少作业语义和严格校验

- Web 请求线程同步等待整个 L1/L2/L3。
- 没有 queued/running/cancelled、进度、截止时间或幂等键。
- `maximum_level=0` 会被 `or 3` 转成三级。
- 日期没有统一 ISO/交易日校验；单个非法股票可能中断整个 universe 构建。

### P1-7：SaaS 迁移尚未接入运行路径

代码仍使用本地 JSON/JSONL；PostgreSQL 迁移只有目标结构。分析报告的 `opportunity_pool_run_id` 没有在当前运行链路填充，RLS、成员关系与迁移重入也没有集成测试。

### P2：产品与学习闭环缺口

- Web 前端没有机会池面板，只存在 API。
- 扫描排序没有使用“按市场状态统计的策略表现”和 Agent 信誉。
- 生命周期只读取最近一次池，无时间窗口、规则版本或 Profile 版本一致性检查。
- 缺少北交所雷达、可转债、新股/次新候选适配器。
- 缺少历史无前视、入口一致性、请求预算、并发写入和迁移 RLS 测试。

## 3. 目标架构

```text
ScanRequest
  -> ScanRunContext
       analysis_date / live|historical / run_id
       market_context / profile_version / rule_version / deadline
  -> CandidateSource adapters
       positions | watchlist | explicit | bulk-market | radar | events
  -> UniverseScheduler
       queue_priority + source quotas (不参与机会质量)
  -> BatchSnapshotGateway
       point-in-time snapshots + raw source ids + quality + cache
  -> L1 Feature Engine
       market_signal_score / evidence_quality / profile_fit / risk_gate
       lifecycle from multi-period market facts only
  -> Promotion Gate
       market-eligible playbooks + data contract
  -> L2 ResearchPlanner
       仅拉取候选战法需要的数据；共享市场数据；有预算和截止时间
  -> Immutable ResearchBundle
  -> L3 Court Committee
  -> ScanRunRepository
       run + candidates + linked reports + config/profile/source manifests
```

### ADR-1：拆分四类评分

**Decision:** 不再输出一个混合“机会分”承担所有语义，改为：

- `queue_priority`：持仓、自选、用户显式关注和来源优先级。
- `market_evidence_score`：仅由同一时点的价格、流动性、资金和市场相对强弱产生。
- `playbook_fit_score`：当前市场允许的战法与个股证据适配度。
- `profile_fit_score`：TradingProfile 个性化匹配，仅用于用户排序，不改变市场事实。

生命周期使用多期市场事实单独计算；用户来源与偏好不得进入生命周期。

### ADR-2：实时与历史模式严格隔离

**Decision:** `analysis_date < current_trade_date` 时必须进入 historical 模式，禁止调用当前雷达、盘口和实时快照。任何跨时点字段都标记为 unavailable，不允许重贴历史日期。

### ADR-3：所有入口只调用一个应用服务

**Decision:** 新增 `OpportunityScanService`，CLI/Web/MCP 只负责参数解析和身份上下文；Provider、快照网关、缓存和持久化依赖统一注入。

### ADR-4：L2 从“全量工作流”改为“战法数据计划”

**Decision:** 根据市场允许战法和候选类型生成 `ResearchPlan.required_datasets`。公共市场数据每个 run 只取一次；个股数据批量预取或受限并发。

### ADR-5：SaaS 使用异步 run，本地 CLI 可同步等待

**Decision:** Web/MCP 创建扫描后返回 `run_id`；查询状态或流式读取阶段结果。CLI 可默认等待，但底层仍使用相同 run 状态机。

## 4. 非功能验收目标

- 时间正确性：历史模式零实时/未来来源；所有时敏字段有 `source_id`、`as_of`、`received_at` 和质量状态。
- L1 性能：缓存命中时 160 只 p95 小于 2 秒；新鲜批量数据 p95 小于 8 秒。
- 请求预算：L1 批量行情/资金请求总数不随股票数线性达到 2N；市场状态每个 run 最多获取一次。
- L2 性能：最多 12 只，有界并发和总截止时间；单股失败不终止其他候选。
- 稳定性：相同 ResearchBundle、规则版本和 Profile 版本得到相同确定性结果。
- 可回放：一次 run 能还原市场状态、候选来源、所有门槛、L2/L3 报告和配置/Profile 哈希。
- 并发安全：同一用户同一幂等键只产生一个 run；本地文件写入有锁，SaaS 使用数据库事务。
- 隐私：扫描结果默认仅当前用户可见；不进入群体聚合，除非单独取得明确同意。

## 5. 实施任务

### Task 1: 建立时点与运行上下文

**Files:**
- Create: `app/opportunities/context.py`
- Create: `app/opportunities/time_policy.py`
- Modify: `app/opportunities/pipeline.py`
- Test: `tests/test_opportunity_time_policy.py`

**Steps:**

1. 写失败测试：历史日期拒绝实时快照/雷达，未来日期拒绝运行，同日实时模式保留真实时间。
2. 运行 `python -m unittest discover -s tests -p "test_opportunity_time_policy.py"`，确认失败。
3. 实现 `ScanRunContext`：`run_id`、`analysis_date`、`mode`、`market_context`、`profile_version`、`rule_version`、`deadline_at`。
4. 实现统一 `parse_analysis_date()` 与 source time policy。
5. 让 Pipeline 在任何候选请求前创建 context，并禁止 historical 模式调用 radar/live snapshot。
6. 运行测试和全量回归。
7. 建议提交：`refactor(scanner): enforce point-in-time scan context`。

### Task 2: 拆分调度、证据、适配与生命周期

**Files:**
- Modify: `app/opportunities/models.py`
- Modify: `app/opportunities/scanner.py`
- Modify: `config/tradingos.default.json`
- Modify: `app/config/runtime.py`
- Test: `tests/test_opportunity_scoring_contracts.py`

**Steps:**

1. 写失败测试：改变 watchlist/position/profile 不得改变 `market_evidence_score` 和 lifecycle。
2. 增加 `queue_priority`、`market_evidence_score`、`evidence_quality_score`、`playbook_fit_score`、`profile_fit_score`、`eligibility_status`。
3. 删除 source/profile 对市场机会质量和生命周期的影响。
4. 生命周期只使用至少三个时间点的资金、相对强弱、成交额和板块阶段；不足时输出 `unknown`。
5. 配置并验证各评分权重和生命周期最小观察数。
6. 运行测试和全量回归。
7. 建议提交：`refactor(scanner): separate priority evidence fit and lifecycle`。

### Task 3: 建立批量快照数据契约

**Files:**
- Modify: `app/data/providers/base.py`
- Create: `app/data/providers/batch_snapshot.py`
- Modify: `app/market/stock_snapshot.py`
- Modify: `app/data/providers/production_provider.py`
- Test: `tests/test_batch_snapshot_gateway.py`

**Steps:**

1. 写调用计数测试：160 只股票不能产生 320 个独立行情/资金请求。
2. 定义 `BatchSnapshotGateway.fetch(symbols, context)`，返回逐字段 provenance、质量、原始快照 ID 和错误。
3. 优先使用批量市场快照；仅对少量关键缺口执行有预算的单股 fallback。
4. 为行情、资金、行业标签分别保留 `as_of`，不再伪装成单一来源。
5. 增加 TTL、交易时段和历史模式缓存键。
6. 运行测试和全量回归。
7. 建议提交：`feat(scanner): add batch point-in-time snapshot gateway`。

### Task 4: 重构候选发现和 universe 调度

**Files:**
- Create: `app/opportunities/sources.py`
- Create: `app/opportunities/universe.py`
- Modify: `app/opportunities/pipeline.py`
- Test: `tests/test_opportunity_universe.py`

**Steps:**

1. 写测试覆盖持仓、自选、显式、全市场预筛、雷达和事件候选去重。
2. 每个来源实现独立 adapter，并输出来源证据与数据状态。
3. 用来源配额与风险优先规则代替简单总排序截断，确保持仓风控不会被挤出，同时保留市场新机会。
4. 接入批量全市场预筛；只用 Python/SQL 因子，不调用 LLM。
5. 对非法 symbol 逐项记录 rejection，不中止整个 run。
6. 运行测试和全量回归。
7. 建议提交：`feat(scanner): add bounded multi-source opportunity universe`。

### Task 5: 市场状态先决定战法和数据计划

**Files:**
- Create: `app/opportunities/research_plan.py`
- Modify: `app/skills/market_strategy_gate.py`
- Modify: `app/opportunities/pipeline.py`
- Modify: `app/graph/workflow.py`
- Test: `tests/test_opportunity_research_plan.py`

**Steps:**

1. 写失败测试：市场不足时不得启动全量 L2；退潮环境不得为短线接力拉取无用深度数据。
2. 在 L1 后先执行共享市场门槛，生成允许战法。
3. 按战法声明 `required_datasets`、freshness 和 blocking quality rules。
4. L2 只加载必要数据；共享 market context，禁止每股重复获取。
5. 将 L1 与 L2 同字段做 reconciliation；冲突时降级而不是覆盖。
6. 运行测试和全量回归。
7. 建议提交：`refactor(scanner): plan L2 research from market-eligible playbooks`。

### Task 6: 有界并发、预算和可观测性

**Files:**
- Create: `app/opportunities/execution.py`
- Create: `app/opportunities/telemetry.py`
- Modify: `app/opportunities/pipeline.py`
- Modify: `config/tradingos.default.json`
- Test: `tests/test_opportunity_execution_budget.py`

**Steps:**

1. 写测试覆盖最大并发、总 deadline、单股失败隔离和 provider rate limit。
2. 对 L2 使用有界 worker；Provider 按自身限制使用 semaphore。
3. 超时候选标记 `deferred/partial`，不得伪装完成。
4. 记录阶段耗时、provider 调用数、缓存命中、数据年龄、fallback 和晋级/淘汰原因。
5. 错误输出做脱敏，禁止泄露 token、完整 URL 参数或本地敏感路径。
6. 运行测试和全量回归。
7. 建议提交：`feat(scanner): add execution budgets and scan telemetry`。

### Task 7: 统一 CLI、Web、MCP 应用服务

**Files:**
- Create: `app/opportunities/service.py`
- Modify: `app/cli.py`
- Modify: `app/web/server.py`
- Modify: `app/mcp/server.py`
- Modify: `app/mcp/tool_schemas.py`
- Test: `tests/test_opportunity_entrypoint_parity.py`

**Steps:**

1. 写入口一致性测试：相同依赖、输入和 context 必须得到相同 run 结果。
2. 所有入口通过同一个 `OpportunityScanService`，不在 handler 内重新拼装 Pipeline。
3. 严格验证 `maximum_level`、日期、symbols、include_radar 和 mode。
4. Web/MCP 改为创建 run 并返回状态；增加 get/cancel 接口。
5. CLI 调用相同服务，可选择等待完成或仅打印 run id。
6. 运行测试和全量回归。
7. 建议提交：`refactor(scanner): unify scan entrypoints and job semantics`。

### Task 8: 原子持久化和完整回放

**Files:**
- Modify: `app/memory/local_store.py`
- Create: `app/opportunities/repository.py`
- Modify: `database/migrations/002_opportunity_pool_pipeline.sql`
- Test: `tests/test_opportunity_repository.py`
- Test: `tests/test_opportunity_postgres_rls.py`

**Steps:**

1. 写失败测试：并发 append 不丢事件；pool 写入失败不产生孤儿 L2/L3；重复幂等键只创建一个 run。
2. run id 在扫描开始时生成，并写入所有分析事件 metadata。
3. 本地存储增加进程内锁、临时文件和可恢复 journal；SaaS 使用单事务写 run/candidates/report links。
4. 保存 profile/config/source manifest hash 和所有 gate decisions。
5. replay 联取 L2/L3 原始报告，而不是只返回候选摘要。
6. 增加 tenant membership 一致性、RLS 和迁移重复执行测试。
7. 运行测试和全量回归。
8. 建议提交：`feat(scanner): make opportunity runs transactional and fully replayable`。

### Task 9: 前端机会池与诚实状态展示

**Files:**
- Modify: `app/web/static/index.html`
- Modify: `app/web/static/app.js`
- Modify: `app/web/static/styles.css`
- Test: `tests/test_web_server.py`

**Steps:**

1. 增加机会池 run 状态、阶段耗时、数据状态和候选门槛展示。
2. 分开展示调度优先级、市场证据、战法适配和用户适配，不展示“胜率”。
3. 对 insufficient/partial/deferred 显示原因和下一步补数建议。
4. 支持查看证据、反证、风险、失效条件和完整回放。
5. 运行 Web 测试和全量回归。
6. 建议提交：`feat(web): expose traceable opportunity pipeline states`。

### Task 10: 接入策略表现与 Agent 信誉，但不冒充胜率

**Files:**
- Create: `app/opportunities/historical_context.py`
- Modify: `app/opportunities/scanner.py`
- Modify: `app/saas/analytics.py`
- Test: `tests/test_opportunity_historical_context.py`

**Steps:**

1. 只读取用户自己的结果；群体结果必须通过明确 consent gate。
2. 输出样本数、市场状态、观察窗口、盈亏比/回撤等描述统计和局限，不生成虚构概率。
3. Agent reputation 只影响“需要复核的证据权重”，不得覆盖当次数据质量和风险门槛。
4. 小样本、市场不匹配或选择偏差明显时输出 insufficient evidence。
5. 运行隐私、统计边界和全量回归测试。
6. 建议提交：`feat(scanner): add consent-gated observational history context`。

## 6. 推荐实施顺序

```text
P0 正确性：Task 1 -> Task 2 -> Task 3 -> Task 5 -> Task 7
P1 生产能力：Task 4 -> Task 6 -> Task 8
P2 产品闭环：Task 9 -> Task 10
```

在 Task 1、2、3、5 完成以前，不建议把当前机会池描述为“全市场高胜率筛选器”。准确定位应保持为：用户关注池与实时雷达上的分层研究调度器。

## 7. 完成定义

- live/historical 时点隔离测试通过，无前视数据。
- CLI/Web/MCP 入口一致性测试通过。
- 160 只 L1 不产生 2N 请求，达到明确 p95 和请求预算。
- 市场状态只获取一次，并在个股排序前决定允许战法。
- 用户来源或 Profile 变化不再伪造生命周期变化。
- 每个候选能解释晋级或淘汰的事实、来源、时间、反证、风险和失效条件。
- L2 数据按战法契约拉取；L3 只消费完整、不可变、可追溯的研究包。
- run、候选、L2/L3 报告可原子持久化并完整回放。
- 群体数据未经同意不会进入扫描排序或统计。
- 全量测试、性能预算测试、并发测试和 PostgreSQL RLS 集成测试通过。
