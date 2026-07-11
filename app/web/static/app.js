const state = { lastSymbol: "600519" };

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

function watchRow(item) {
  const row = document.createElement("div"); row.className = "watch-row";
  const main = document.createElement("div"); const symbol = document.createElement("strong"); const note = document.createElement("span"); text(symbol, item.symbol); text(note, item.note || "未填写观察备注"); main.append(symbol, note);
  const quote = item.quote;
  const price = document.createElement("b"); const meta = document.createElement("small");
  if (quote?.data_status === "real_time") { text(price, quote.price?.toFixed(2)); price.className = quote.change_pct >= 0 ? "up" : "down"; text(meta, `${percentage(quote.change_pct)} · ${quote.trade_date || ""} ${quote.trade_time || ""}`); }
  else { text(price, "行情不可用"); price.className = "flat"; text(meta, quote?.error || "请刷新后重试"); }
  const advice = document.createElement("p"); text(advice, item.advice || "点击刷新实时行情以获取研究提示。");
  row.append(main, price, meta, advice); return row;
}

function renderWatchlist(items) { const root = $("watchlistRows"); root.replaceChildren(); if (!items.length) { const empty = document.createElement("div"); empty.className = "empty-state compact"; text(empty, "尚未加入自选股。"); root.append(empty); return; } items.forEach((item) => root.append(watchRow(item))); }

function renderPortfolio(snapshot) {
  const root = $("accountStats"); root.replaceChildren();
  [["可用余额", money(snapshot.cash_balance)], ["总资产", money(snapshot.total_assets)], ["持仓浮盈", money(snapshot.unrealized_pnl)], ["当日盈亏", money(snapshot.daily_pnl)]].forEach(([label, value]) => root.append(scoreTile(label, value)));
}

async function refreshMarket() {
  const button = $("refreshMarket"); button.disabled = true; text($("marketMessage"), "正在请求固定公开行情源…");
  try { const { data } = await api("/api/market/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); renderWatchlist(data.watchlist); renderPortfolio(data.portfolio); text($("marketMessage"), "已刷新。请注意行情源状态与时间戳；建议仅作研究依据。"); }
  catch (error) { text($("marketMessage"), `刷新失败：${error.message}`); } finally { button.disabled = false; }
}

function renderReport(report) {
  $("emptyReport").hidden = true; $("reportContent").hidden = false;
  text($("reportDate"), report.analysis_date); text($("reportSymbol"), report.symbol); text($("reportTitle"), report.name);
  const realtime = report.realtime_quote;
  text($("realtimeReport"), realtime ? `实时参考 · ${realtime.source || "unknown"} · ${realtime.price ?? "不可用"} · ${percentage(realtime.change_pct)} · ${realtime.trade_date || ""} ${realtime.trade_time || ""} · ${realtime.data_status}` : "未请求实时行情上下文");
  text($("verdict"), report.conclusion); $("verdict").dataset.risk = report.risk_level;
  const scores = $("scores"); scores.replaceChildren();
  [["基本", report.fundamental_score], ["技术", report.technical_score], ["资金", report.capital_flow_score], ["题材", report.theme_score]].forEach(([label, value]) => scores.append(scoreTile(label, value)));
  text($("actionPlan"), report.action_plan);
  const risks = $("risks"); risks.replaceChildren(); (report.risk_factors || []).slice(0, 4).forEach((risk) => { const li = document.createElement("li"); text(li, risk); risks.append(li); });
  const skills = $("skills"); skills.replaceChildren(); (report.skill_insights || []).forEach((skill) => {
    const row = document.createElement("div"); row.className = "skill-row";
    const left = document.createElement("div"); const title = document.createElement("strong"); const desc = document.createElement("span");
    text(title, skill.skill); text(desc, `${skill.conclusion} ${skill.strategy || ""}`); left.append(title, desc);
    const score = document.createElement("b"); text(score, `${skill.score} / ${skill.stage}`); row.append(left, score); skills.append(row);
  });
  const model = $("modelSection"); model.hidden = !report.model_interpretation; text($("modelInterpretation"), report.model_interpretation);
}

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
    state.lastSymbol = data.symbol; renderReport(data); text($("formMessage"), `已保存分析与问答摘要 · ${data.memory_event_id.slice(0, 8)}`); await loadDashboard();
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

$("watchlistForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const symbol = $("watchSymbol").value.trim(); if (!symbol) return;
  try { const { data } = await api("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, note: $("watchNote").value.trim() }) }); renderWatchlist(data.items); $("watchSymbol").value = ""; $("watchNote").value = ""; text($("marketMessage"), "已加入自选；点击刷新获取实时行情。"); }
  catch (error) { text($("marketMessage"), error.message); }
});

$("cashForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { const { data } = await api("/api/portfolio/cash", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cash_balance: $("cashBalance").value }) }); renderPortfolio({ ...data, total_assets: data.cash_balance, cost_value: 0, market_value: 0, unrealized_pnl: 0, daily_pnl: 0 }); text($("marketMessage"), "账户可用余额已保存到本地档案。"); } catch (error) { text($("marketMessage"), error.message); }
});

$("positionForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { await api("/api/portfolio/position", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: $("positionSymbol").value.trim(), quantity: $("positionQty").value, cost_price: $("positionCost").value }) }); text($("marketMessage"), "持仓已保存；刷新行情后可查看浮盈与当日盈亏。"); $("positionForm").reset(); } catch (error) { text($("marketMessage"), error.message); }
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
