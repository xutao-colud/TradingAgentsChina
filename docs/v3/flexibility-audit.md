# 灵活性审计与反推提示词整改

这份审计记录当前系统里不够灵活、容易写死、或后续应配置化的地方。目标不是把所有规则都交给 LLM，而是把事实、阈值、评分和 Prompt 合约做成可版本化、可复盘、可替换的 TradingOS 组件。

## 已落地

### 1. 模型解释升级为反推验证

位置：

- `app/llm/prompt_contracts.py`
- `app/llm/deepseek_client.py`

模型现在不再只顺着结论解释，而是必须输出：

- 当前结论被哪些证据支持
- 最强反证
- 反推失效条件
- 强化 / 观望 / 失效三种剧本
- 与用户打法的匹配和不匹配
- 下一步核验清单

约束：

- 不改确定性评分
- 不虚构实时数据
- 不输出隐藏思维链
- 不给确定性买卖指令

## 高优先级写死点

| 模块 | 当前问题 | 风险 | 建议 |
| --- | --- | --- | --- |
| `app/agents/*.py` | 技术、基本面、资金、市场等阈值散落在代码里 | 改一个阈值要动代码，无法按市场阶段切换 | 新增 `config/scoring_rules.json`，每个 Agent 读取版本化规则 |
| `app/skills/*.py` | 情绪、风险、主力行为、题材生命周期阈值写在函数里 | 不同用户/市场阶段无法调参 | 建立 `SkillRuleSet`，输出规则版本、命中条件和扣分来源 |
| `app/skills/investment_committee.py` | 流派模板、确认条件、失效条件写在 Python 字典里 | 以后加流派或改口径要改代码 | 迁移到 `config/factions/*.json`，保留 Python 校验器 |
| `app/playbooks/catalog.py` | Playbook 是 Python 常量 | SaaS 用户无法自定义战法 | 改成内置模板 + 用户自定义 Playbook，两者统一 schema |
| `app/playbooks/evaluator.py` | 战法评分规则用 if/else 匹配 playbook id | 战法越多越难维护 | 用声明式条件：指标、比较符、阈值、权重、失效条件 |
| `app/agents/portfolio_manager.py` | 最终评级阈值和行动文案固定 | 不能随用户风险偏好、市场温度、持仓周期调整 | 建立 `DecisionPolicy`，按用户画像和市场状态切换 |

## 中优先级写死点

| 模块 | 当前问题 | 建议 |
| --- | --- | --- |
| `SampleMarketDataProvider` | 样例股票、财务、公告和市场环境仍是固定样例 | 保留离线回归测试用途，但 UI 必须持续标注 `offline_sample` |
| `EastmoneyRealtimeMarketDataProvider` | 只有价格/分档资金较实时，财务/公告/市场宽度仍 fallback | 给每类数据单独展示 `source_type` 和 `as_of`，避免用户误以为全实时 |
| `app/llm/providers.py` | 模型服务商固定 | 出于安全可以固定基础地址，但模型清单应从版本化白名单读取 |
| `app/web/static/*.js/css` | 大量展示文案直接写在前端 | 先接受；后续做 i18n / copy registry，方便产品口径统一 |
| `app/memory/models.py` | 默认交易画像固定为趋势核心 | 新用户应走 onboarding 问卷，生成初始 TradingProfile |

## 故意固定且不建议放开

| 模块 | 固定原因 |
| --- | --- |
| 模型 provider base_url 白名单 | 防止把本地服务变成任意 URL 代理 |
| 风控不能被 LLM 改分 | 保证证据链可追溯，防止模型绕过风险门 |
| 自动交易/下单能力缺失 | 产品定位是投研辅助，不是自动交易系统 |
| `SampleMarketDataProvider` | 离线测试和演示必须稳定可复现 |

## 下一步建议

1. 先做 `config/scoring_rules.json`，覆盖技术、资金、风险、市场温度、情绪周期五类核心阈值。
2. 再把投资流派模板迁移到 `config/factions/*.json`，保留 schema 测试。
3. 把 Playbook 改成声明式规则，支持用户自定义战法和回测。
4. 给每次报告记录 `rule_version`、`prompt_contract_version`、`data_source_status`，方便复盘。
5. 引入“反推失败复盘”：如果后续走势或用户反馈证明判断错了，记录是哪条失效条件没有被及时触发。
