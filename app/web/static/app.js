const state = { lastSymbol: "600519", committee: null };

const $ = (id) => document.getElementById(id);

function setToday() {
  $("analysisDate").value = new Date().toISOString().slice(0, 10);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return { data, response };
}

function text(element, value) { element.textContent = value ?? "—"; }

function renderProfile(profile) {
  const root = $("profileContent");
  root.replaceChildren();
  const rows = [
    ["风格", profile.style], ["风险", profile.risk_level], ["周期", profile.holding_period],
    ["偏好", (profile.preferred_setups || []).join(" · ")], ["回避", (profile.avoid_patterns || []).join(" · ")],
  ];
  rows.forEach(([label, value]) => {
    const row = document.createElement("div");
    const key = document.createElement("span"); const content = document.createElement("strong");
    text(key, label); text(content, value); row.append(key, content); root.append(row);
  });
}

function renderTools(tools) {
  const root = $("toolList"); root.replaceChildren();
  tools.forEach((tool) => { const item = document.createElement("li"); text(item, tool.name); root.append(item); });
}

function renderPlaybooks(payload) {
  const select = $("playbookSelect"); select.replaceChildren();
  payload.playbooks.forEach((playbook) => {
    const option = document.createElement("option"); option.value = playbook.id; text(option, `${playbook.group} · ${playbook.name}`); option.selected = playbook.id === payload.active_playbook; select.append(option);
  });
  const active = payload.playbooks.find((playbook) => playbook.id === payload.active_playbook);
  text($("playbookNote"), active ? `${active.summary} 优化重点：${active.optimization_focus}` : "未选择风格原型。");
}

function renderModels(status) {
  const select = $("modelProvider"); select.replaceChildren();
  status.providers.forEach((provider) => {
    const option = document.createElement("option"); option.value = provider.id; text(option, `${provider.name} · ${provider.default_model}`); option.selected = provider.id === status.active_provider; select.append(option);
  });
  $("modelName").value = status.active_model || "";
  const active = status.providers.find((provider) => provider.id === status.active_provider);
  text($("modelStatus"), active?.configured ? `${active.name} 已配置（密钥来源：${active.key_source}）。可勾选报告解释。` : `${active?.name || "当前模型"} 未配置。页面输入的密钥只保存到当前服务会话；重启后请重新输入或使用 ${active?.env_key || "环境变量"}。`);
}

function scoreTile(label, value) {
  const tile = document.createElement("div"); const title = document.createElement("span"); const number = document.createElement("strong");
  text(title, label); text(number, value); tile.append(title, number); return tile;
}

function money(value) { return value == null ? "—" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 }).format(value); }
function percentage(value) { return value == null ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`; }
function yi(value) { return value == null ? "—" : `${(Number(value) / 100000000).toFixed(2)}亿`; }
function shares(value) { return value == null ? "—" : new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value); }

function watchRow(item, openDetail = false) {
  const row = document.createElement("div"); row.className = "watch-row";
  const main = document.createElement("div"); const symbol = document.createElement("strong"); const note = document.createElement("span");
  const snapshot = item.snapshot;
  text(symbol, `${item.symbol}${snapshot?.name ? ` · ${snapshot.name}` : ""}`);
  text(note, item.note || "未填写观察备注"); main.append(symbol, note);
  const quote = item.quote;
  const price = document.createElement("b"); const meta = document.createElement("small");
  if (quote?.data_status === "real_time" || quote?.data_status === "latest_available") { text(price, quote.price?.toFixed(2)); price.className = quote.change_pct >= 0 ? "up" : "down"; text(meta, `${percentage(quote.change_pct)} · ${quote.data_status} · ${quote.trade_date || ""}`); }
  else { text(price, "行情不可用"); price.className = "flat"; text(meta, quote?.error || "请刷新后重试"); }
  const advice = document.createElement("p"); text(advice, item.advice || "点击刷新实时行情以获取研究提示。");
  row.append(main, price, meta);
  if (snapshot) row.append(watchDetail(snapshot, openDetail));
  row.append(advice); return row;
}

function watchDetail(snapshot, openDetail = false) {
  const panel = document.createElement("details"); panel.className = "watch-detail-panel"; panel.open = openDetail;
  const summary = document.createElement("summary");
  const concepts = snapshot.concepts || [];
  const fullConcepts = concepts.join(" · ") || "—";
  const shortConcepts = concepts.length > 3 ? `${concepts.slice(0, 3).join(" · ")} +${concepts.length - 3}` : fullConcepts;
  text(summary, `所属板块 / 资金流 · ${snapshot.industry || snapshot.market_board || "待刷新"}`);
  const detail = document.createElement("div"); detail.className = "watch-detail";
  const flow = snapshot.money_flow || {};
  const chips = [
    ["行业", snapshot.industry || "—", undefined, snapshot.industry || "—"],
    ["上市板", snapshot.market_board || "—", undefined, snapshot.market_board || "—"],
    ["地域", snapshot.region || "—", undefined, snapshot.region || "—"],
    ["概念", shortConcepts, undefined, fullConcepts],
    ["成交额", yi(snapshot.amount)],
    ["换手", percentage(snapshot.turnover_rate)],
    ["主力净流", yi(flow.main_net_inflow), flow.main_net_inflow],
    ["超大单", yi(flow.super_large_net_inflow), flow.super_large_net_inflow],
    ["大单", yi(flow.large_net_inflow), flow.large_net_inflow],
    ["中单", yi(flow.medium_net_inflow), flow.medium_net_inflow],
    ["小单", yi(flow.small_net_inflow), flow.small_net_inflow],
    ["明盘大单", yi(flow.visible_large_net_inflow), flow.visible_large_net_inflow],
    ["暗盘跟随", yi(flow.hidden_follow_net_inflow), flow.hidden_follow_net_inflow],
  ];
  chips.forEach(([label, value, raw, fullText]) => {
    const chip = document.createElement("span"); const k = document.createElement("i"); const v = document.createElement("b");
    if (typeof raw === "number") v.className = raw > 0 ? "up" : raw < 0 ? "down" : "flat";
    if (fullText && fullText !== value) {
      chip.className = "has-tooltip";
      chip.dataset.tooltip = fullText;
      chip.title = fullText;
    }
    text(k, label); text(v, value); chip.append(k, v); detail.append(chip);
  });
  panel.append(summary, detail);
  return panel;
}

function renderWatchlist(items) { const root = $("watchlistRows"); root.replaceChildren(); if (!items.length) { const empty = document.createElement("div"); empty.className = "empty-state compact"; text(empty, "尚未加入自选股。"); root.append(empty); return; } items.forEach((item) => root.append(watchRow(item, items.length === 1))); }

function renderPortfolio(snapshot) {
  const root = $("accountStats"); root.replaceChildren();
  [["可用余额", money(snapshot.cash_balance)], ["总资产", money(snapshot.total_assets)], ["持仓浮盈", money(snapshot.unrealized_pnl)], ["当日盈亏", money(snapshot.daily_pnl)]].forEach(([label, value]) => root.append(scoreTile(label, value)));
  renderPositions(snapshot.positions || []);
}

function renderPositions(positions) {
  const root = $("positionRows"); root.replaceChildren();
  if (!positions.length) { const empty = document.createElement("div"); empty.className = "empty-state compact"; text(empty, "尚未记录持仓。"); root.append(empty); return; }
  positions.forEach((position) => root.append(positionRow(position)));
}

function positionRow(position) {
  const row = document.createElement("div"); row.className = "position-row";
  const head = document.createElement("div"); const symbol = document.createElement("strong"); const meta = document.createElement("span");
  const quote = position.quote || {};
  text(symbol, `${position.symbol}${quote.name ? ` · ${quote.name}` : ""}`);
  text(meta, `数量 ${shares(position.quantity)} · 成本 ${money(position.cost_price)} · ${quote.data_status || "未刷新"}`);
  head.append(symbol, meta);
  const pnl = document.createElement("b"); pnl.className = (position.unrealized_pnl ?? 0) > 0 ? "up" : (position.unrealized_pnl ?? 0) < 0 ? "down" : "flat";
  text(pnl, `${money(position.unrealized_pnl)} / ${percentage(position.unrealized_pnl_pct)}`);
  const metrics = document.createElement("div"); metrics.className = "position-metrics";
  [
    ["现价", quote.price == null ? "—" : quote.price.toFixed(2)],
    ["市值", money(position.market_value)],
    ["成本额", money(position.cost_value)],
    ["当日", money(position.daily_pnl)],
  ].forEach(([label, value]) => {
    const chip = document.createElement("span"); const k = document.createElement("i"); const v = document.createElement("em");
    text(k, label); text(v, value); chip.append(k, v); metrics.append(chip);
  });
  const advice = document.createElement("p"); text(advice, position.advice || "刷新实时行情后再判断是否调整。");
  const actions = document.createElement("div"); actions.className = "position-actions";
  const edit = document.createElement("button"); edit.type = "button"; text(edit, "回填编辑");
  edit.addEventListener("click", () => {
    $("positionSymbol").value = position.symbol;
    $("positionQty").value = position.quantity;
    $("positionCost").value = position.cost_price;
  });
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger-button"; text(remove, "删除");
  remove.addEventListener("click", () => deletePosition(position.symbol));
  actions.append(edit, remove);
  row.append(head, pnl, metrics, advice, actions);
  return row;
}

async function deletePosition(symbol) {
  if (!window.confirm(`删除本地持仓 ${symbol}？这只影响本机快照，不会连接券商。`)) return;
  try {
    await api("/api/portfolio/position/remove", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol }) });
    await refreshMarket();
    text($("marketMessage"), `${symbol} 已从本地账户快照删除。`);
  } catch (error) { text($("marketMessage"), `删除失败：${error.message}`); }
}

async function refreshMarket() {
  const button = $("refreshMarket"); button.disabled = true; text($("marketMessage"), "正在请求固定公开行情源…");
  try { const { data } = await api("/api/market/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); renderWatchlist(data.watchlist); renderPortfolio(data.portfolio); text($("marketMessage"), "已刷新。请注意行情源状态与时间戳；建议仅作研究依据。"); }
  catch (error) { text($("marketMessage"), `刷新失败：${error.message}`); } finally { button.disabled = false; }
}

function radarRow(title, meta, value, tone = "flat") {
  const row = document.createElement("div"); row.className = "radar-row";
  const main = document.createElement("div"); const name = document.createElement("strong"); const sub = document.createElement("span");
  text(name, title); text(sub, meta); main.append(name, sub);
  const score = document.createElement("b"); score.className = tone; text(score, value);
  row.append(main, score); return row;
}

function renderMorningRadar(snapshot) {
  text($("morningRadarStatus"), `${snapshot.data_status} · ${snapshot.market_phase} · ${snapshot.as_of}`);
  text($("morningRadarMessage"), `${snapshot.shortline_read}${snapshot.error ? ` 数据源提示：${snapshot.error}` : ""}`);
  const inflow = $("sectorInflow"); const outflow = $("sectorOutflow"); const movers = $("fastMovers");
  inflow.replaceChildren(); outflow.replaceChildren(); movers.replaceChildren();
  (snapshot.top_inflow_sectors || []).forEach((item) => inflow.append(radarRow(item.name, `涨跌 ${percentage(item.change_pct)} · 占比 ${percentage(item.main_net_inflow_ratio)}`, yi(item.main_net_inflow), "up")));
  (snapshot.top_outflow_sectors || []).forEach((item) => outflow.append(radarRow(item.name, `涨跌 ${percentage(item.change_pct)} · 占比 ${percentage(item.main_net_inflow_ratio)}`, yi(item.main_net_inflow), "down")));
  (snapshot.fast_movers || []).forEach((item) => movers.append(radarRow(`${item.name} ${item.symbol}`, `${percentage(item.change_pct)} · 涨速 ${percentage(item.speed_pct)} · ${item.trigger_reason}`, yi(item.amount), item.change_pct >= 0 ? "up" : "down")));
  if (!inflow.children.length) inflow.append(emptyRadar());
  if (!outflow.children.length) outflow.append(emptyRadar());
  if (!movers.children.length) movers.append(emptyRadar());
}

function emptyRadar() { const empty = document.createElement("div"); empty.className = "empty-state compact"; text(empty, "暂无数据。"); return empty; }

async function refreshMorningRadar() {
  const button = $("refreshMorningRadar"); button.disabled = true; text($("morningRadarMessage"), "正在刷新实时板块资金流与急拉个股…");
  try { const { data } = await api("/api/morning/radar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 6 }) }); renderMorningRadar(data); }
  catch (error) { text($("morningRadarMessage"), `刷新失败：${error.message}`); } finally { button.disabled = false; }
}

function renderReport(report) {
  $("emptyReport").hidden = true; $("reportContent").hidden = false;
  text($("reportDate"), report.analysis_date); text($("reportSymbol"), report.symbol); text($("reportTitle"), report.name);
  const realtime = report.realtime_quote;
  const dataLabel = `研究数据：${report.data_status || "未知"}`;
  text($("realtimeReport"), realtime ? `${dataLabel} · 实时参考 · ${realtime.source || "unknown"} · ${realtime.price ?? "不可用"} · ${percentage(realtime.change_pct)} · ${realtime.trade_date || ""} ${realtime.trade_time || ""} · ${realtime.data_status}` : `${dataLabel} · 未请求实时行情上下文`);
  text($("verdict"), report.conclusion); $("verdict").dataset.risk = report.risk_level;
  const scores = $("scores"); scores.replaceChildren();
  [["基本", report.fundamental_score], ["技术", report.technical_score], ["资金", report.capital_flow_score], ["题材", report.theme_score]].forEach(([label, value]) => scores.append(scoreTile(label, value)));
  text($("actionPlan"), report.action_plan);
  const risks = $("risks"); risks.replaceChildren(); (report.risk_factors || []).slice(0, 4).forEach((risk) => { const li = document.createElement("li"); text(li, risk); risks.append(li); });
  const skills = $("skills"); skills.replaceChildren(); (report.skill_insights || []).forEach((skill) => {
    const row = document.createElement("div"); row.className = "skill-row";
    const main = document.createElement("div"); main.className = "skill-row-main";
    const left = document.createElement("div"); const title = document.createElement("strong"); const desc = document.createElement("span");
    text(title, skill.skill); text(desc, `${skill.conclusion} ${skill.strategy || ""}`); left.append(title, desc);
    const right = document.createElement("div"); right.className = "skill-score-wrap";
    const score = document.createElement("b"); text(score, `${skill.score} / ${skill.stage}`); right.append(score);
    main.append(left, right); row.append(main);
    if (skill.details?.mode === "risk_scan") row.append(riskExplainPanel(skill));
    skills.append(row);
  });
  const committee = (report.skill_insights || []).find((skill) => skill.category === "committee" && skill.details?.mode === "court");
  state.committee = committee?.details || null;
  $("committeeButton").hidden = !state.committee;
  if (state.committee) renderCommitteeCourt(state.committee);
  const model = $("modelSection"); model.hidden = !report.model_interpretation; text($("modelInterpretation"), report.model_interpretation);
}

function riskExplainPanel(skill) {
  const panel = document.createElement("div"); panel.className = "risk-explain";
  const button = document.createElement("button"); button.type = "button"; button.className = "risk-toggle"; text(button, "展开原理");
  const body = document.createElement("div"); body.className = "risk-body"; body.hidden = true;
  const details = skill.details || {};
  const intro = document.createElement("p"); text(intro, `${details.grade || skill.stage}：${details.grade_explanation || skill.conclusion}`);
  body.append(intro);
  body.append(riskSection("等级说明", (details.grade_guide || []).map((item) => `${item.grade}（${item.range}）：${item.meaning}`)));
  body.append(riskSection("扣分项", (details.deductions || []).map((item) => `${item.category} · ${item.item}：-${item.points}，${item.reason}`), "暂无扣分项"));
  body.append(riskCheckGrid(details.checks || []));
  body.append(riskSection("下一步核验", details.next_checks || []));
  const principle = document.createElement("p"); principle.className = "risk-principle"; text(principle, details.principle || "风险扫描用于约束结论，不替代交易决策。"); body.append(principle);
  button.addEventListener("click", () => {
    body.hidden = !body.hidden;
    text(button, body.hidden ? "展开原理" : "收起原理");
  });
  panel.append(button, body); return panel;
}

function riskSection(titleText, items, emptyText = "暂无") {
  const section = document.createElement("section"); const title = document.createElement("h5"); const list = document.createElement("ul");
  text(title, titleText);
  (items.length ? items : [emptyText]).forEach((item) => { const li = document.createElement("li"); text(li, item); list.append(li); });
  section.append(title, list); return section;
}

function riskCheckGrid(checks) {
  const section = document.createElement("section"); const title = document.createElement("h5"); const grid = document.createElement("div");
  text(title, "检查原理"); grid.className = "risk-check-grid";
  (checks.length ? checks : [{ name: "暂无", threshold: "—", observed: "—", status: "—", explanation: "暂无检查项。" }]).forEach((item) => {
    const card = document.createElement("article"); card.className = `risk-check ${item.severity === "warning" ? "warn" : "ok"}`;
    const head = document.createElement("strong"); text(head, `${item.name} · ${item.status}`);
    const meta = document.createElement("span"); text(meta, `阈值：${item.threshold}｜当前：${item.observed}`);
    const explain = document.createElement("p"); text(explain, item.explanation);
    card.append(head, meta, explain); grid.append(card);
  });
  section.append(title, grid); return section;
}

function renderCommitteeCourt(details) {
  const judge = details.judge || {};
  const judgeBox = $("committeeJudge"); judgeBox.replaceChildren();
  const title = document.createElement("strong"); text(title, `Judge 裁决：${judge.winner || "暂无优势"}`);
  const topic = document.createElement("em"); text(topic, `研讨问题：${judge.discussion_topic || "当前个股是否值得继续研究"}`);
  const meta = document.createElement("span"); text(meta, `${judge.winner_route || "—"} · 可靠性 ${judge.reliability || "—"} · 领先 ${judge.score_gap ?? "—"} 分`);
  const method = document.createElement("span"); text(method, judge.score_summary ? `${judge.score_summary}｜${judge.score_method || ""}` : judge.score_method || "");
  const verdict = document.createElement("p"); text(verdict, judge.verdict || "证据不足，保持观察。");
  const action = document.createElement("p"); action.className = "judge-action"; text(action, judge.action || "等待更高质量证据。");
  judgeBox.append(title, topic, meta, method, verdict, action);

  const root = $("committeeFactions"); root.replaceChildren();
  (details.factions || []).forEach((faction) => {
    const card = document.createElement("article"); card.className = `faction-card${faction.winner ? " winner" : ""}`;
    const head = document.createElement("div"); const name = document.createElement("strong"); const score = document.createElement("b");
    text(name, `${faction.name} · ${faction.route}`); text(score, `${faction.score} / ${faction.stance}`); head.append(name, score);
    const response = document.createElement("p"); response.className = "faction-response"; text(response, faction.question_response || "本派暂无针对该问题的单独回应。");
    const advice = document.createElement("p"); advice.className = "faction-advice"; text(advice, faction.recommendation);
    const scoreDetail = courtScoreDetail(faction);
    const reasons = courtList("理由", faction.rationale);
    const risks = courtList("反证/风险", faction.risks);
    card.append(head, response, advice, scoreDetail, reasons, risks); root.append(card);
  });
}

function courtScoreDetail(faction) {
  const wrap = document.createElement("details"); wrap.className = "faction-score-detail"; wrap.open = Boolean(faction.winner);
  const summary = document.createElement("summary"); text(summary, "评分依据");
  const explanation = document.createElement("p"); text(explanation, faction.score_explanation || `最终分 ${faction.score}`);
  const basis = faction.score_basis || {};
  const basisLine = document.createElement("p"); basisLine.className = "score-basis-line";
  text(basisLine, `基础 ${basis.base_score ?? faction.base_score ?? "—"}｜正向 ${basis.positive_impact ?? "—"}｜负向 ${basis.negative_impact ?? "—"}｜原始 ${basis.raw_score ?? "—"}｜最终 ${basis.final_score ?? faction.score ?? "—"}`);
  const list = document.createElement("ul");
  (faction.score_adjustments || []).forEach((item) => {
    const li = document.createElement("li");
    const impact = Number(item.impact || 0);
    const title = document.createElement("strong");
    text(title, `${impact >= 0 ? "+" : ""}${impact}｜${item.item}｜${item.direction || (impact >= 0 ? "加分" : "扣分")}`);
    const meta = document.createElement("span");
    text(meta, `当前：${item.observed || "—"}｜阈值：${item.threshold || "—"}｜来源：${item.source || "—"}`);
    const reason = document.createElement("p");
    text(reason, item.reason || "暂无解释。");
    li.append(title, meta, reason);
    list.append(li);
  });
  if (!list.children.length) { const li = document.createElement("li"); text(li, `基础分 ${faction.base_score ?? "—"}，暂无额外加减分。`); list.append(li); }
  const checks = faction.playbook_checks || {};
  wrap.append(
    summary,
    explanation,
    basisLine,
    list,
    courtMiniSection("核心逻辑", checks.core_logic ? [checks.core_logic] : []),
    courtMiniSection("支持证据", checks.supports || []),
    courtMiniSection("反证/拖累", checks.blocks || []),
    courtMiniSection("下一步确认", checks.must_confirm || []),
    courtMiniSection("失效条件", checks.invalid_if || []),
  );
  return wrap;
}

function courtMiniSection(label, items = []) {
  const wrap = document.createElement("div"); wrap.className = "score-mini-section";
  const title = document.createElement("h5"); text(title, label);
  const list = document.createElement("ul");
  (items.length ? items : ["暂无"]).slice(0, 5).forEach((item) => { const li = document.createElement("li"); text(li, item); list.append(li); });
  wrap.append(title, list); return wrap;
}

function courtList(label, items = []) {
  const wrap = document.createElement("div"); const title = document.createElement("i"); const list = document.createElement("ul");
  text(title, label);
  (items.length ? items : ["暂无"]).slice(0, 4).forEach((item) => { const li = document.createElement("li"); text(li, item); list.append(li); });
  wrap.append(title, list); return wrap;
}

function openCommittee() { if (state.committee) $("committeeModal").hidden = false; }
function closeCommittee() { $("committeeModal").hidden = true; }

async function loadDashboard() {
  try {
    const [{ data: health }, { data: profile }, { data: tools }, { data: playbooks }, { data: watchlist }, { data: portfolio }, { data: models }] = await Promise.all([api("/api/health"), api("/api/profile"), api("/api/tools"), api("/api/playbooks"), api("/api/watchlist"), api("/api/portfolio"), api("/api/models")]);
    text($("serverStatus"), `本地引擎已就绪 · ${health.data_provider}`); renderProfile(profile); renderTools(tools.tools); renderPlaybooks(playbooks); renderWatchlist(watchlist.items); renderPortfolio(portfolio); renderModels(models);
  } catch (error) { text($("serverStatus"), `连接失败：${error.message}`); }
}

$("analysisForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = $("analyzeButton"); button.disabled = true; text($("formMessage"), "正在运行市场、技术、资金、风险与个人画像 Skills…");
  try {
    const payload = { symbol: $("symbol").value.trim(), analysis_date: $("analysisDate").value, question: $("question").value.trim(), model_explain: $("modelExplain").checked, include_realtime: true };
    const { data } = await api("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    state.lastSymbol = data.symbol; renderReport(data); openCommittee(); text($("formMessage"), `已保存分析与问答摘要 · ${data.memory_event_id.slice(0, 8)}`); await loadDashboard();
  } catch (error) { text($("formMessage"), `未完成：${error.message}`); } finally { button.disabled = false; }
});

$("feedbackForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const comment = $("feedback").value.trim(); if (!comment) return;
  try { const { data } = await api("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: state.lastSymbol, feedback_type: "preference", user_comment: comment }) }); renderProfile(data.trading_profile); $("feedback").value = ""; text($("memoryMessage"), "偏好已保存到本地个人档案。"); }
  catch (error) { text($("memoryMessage"), error.message); }
});

$("playbookSelect").addEventListener("change", async (event) => {
  try {
    const { data } = await api("/api/playbook/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playbook_id: event.target.value }) });
    renderProfile(data.trading_profile); text($("memoryMessage"), `已切换为：${data.active_playbook.name}。下一次分析会按该原型给出适配度与优化建议。`); await loadDashboard();
  } catch (error) { text($("memoryMessage"), error.message); }
});

$("modelForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const apiKey = $("modelKey").value;
  if (!apiKey) { text($("modelStatus"), "请输入 API Key；密钥只保留到当前本地服务会话。"); return; }
  try { const { data } = await api("/api/models/configure", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider_id: $("modelProvider").value, model: $("modelName").value.trim(), api_key: apiKey }) }); $("modelKey").value = ""; renderModels(data); }
  catch (error) { text($("modelStatus"), `配置失败：${error.message}`); }
});

$("clearModelKey").addEventListener("click", async () => {
  try { const { data } = await api("/api/models/clear", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider_id: $("modelProvider").value }) }); renderModels(data); }
  catch (error) { text($("modelStatus"), `清除失败：${error.message}`); }
});

$("refreshMarket").addEventListener("click", refreshMarket);
$("refreshMorningRadar").addEventListener("click", refreshMorningRadar);
$("committeeButton").addEventListener("click", openCommittee);
$("closeCommittee").addEventListener("click", closeCommittee);
$("committeeModal").addEventListener("click", (event) => { if (event.target === $("committeeModal")) closeCommittee(); });

$("watchlistForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const symbol = $("watchSymbol").value.trim(); if (!symbol) return;
  try { const { data } = await api("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, note: $("watchNote").value.trim() }) }); renderWatchlist(data.items); $("watchSymbol").value = ""; $("watchNote").value = ""; text($("marketMessage"), "已加入自选；点击刷新获取实时行情。"); }
  catch (error) { text($("marketMessage"), error.message); }
});

$("cashForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { const { data } = await api("/api/portfolio/cash", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cash_balance: $("cashBalance").value }) }); renderPortfolio({ ...data, total_assets: data.cash_balance, cost_value: 0, market_value: 0, unrealized_pnl: 0, daily_pnl: 0 }); text($("marketMessage"), "账户可用余额已保存到本地档案。"); } catch (error) { text($("marketMessage"), error.message); }
});

$("positionForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { await api("/api/portfolio/position", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: $("positionSymbol").value.trim(), quantity: $("positionQty").value, cost_price: $("positionCost").value }) }); $("positionForm").reset(); await refreshMarket(); text($("marketMessage"), "持仓已保存并刷新估值。"); } catch (error) { text($("marketMessage"), error.message); }
});

$("exportButton").addEventListener("click", async () => {
  try { const { data } = await api("/api/memory/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "trading-agents-memory.json"; link.click(); URL.revokeObjectURL(url); text($("memoryMessage"), "个人档案已导出，可复制到另一台电脑。 "); }
  catch (error) { text($("memoryMessage"), error.message); }
});

$("importInput").addEventListener("change", async (event) => {
  const file = event.target.files[0]; if (!file) return;
  try { const bundle = JSON.parse(await file.text()); const { data } = await api("/api/memory/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(bundle) }); text($("memoryMessage"), `已合并：分析 ${data.added_events.analysis}，反馈 ${data.added_events.feedback}，问答 ${data.added_events.interaction}`); await loadDashboard(); }
  catch (error) { text($("memoryMessage"), `导入失败：${error.message}`); } finally { event.target.value = ""; }
});

setToday(); loadDashboard();
