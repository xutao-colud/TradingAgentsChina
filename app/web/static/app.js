const state = {
  lastSymbol: "600519", committee: null, modelProviders: [], activeProviderId: null,
  session: null, teamHealth: null,
  analysisProgressTimer: null, analysisStartedAt: null,
  tickerTimer: null, tickerInFlight: false, tickerTrackedCount: 0, marketRefreshInFlight: false,
  loginVisual: { back_messages: [], back_message_palette: [] },
  tickerConfig: {
    refresh_interval_ms: null, error_backoff_ms: null, animation_duration_ms: null,
    request_timeout_ms: null, request_max_attempts: 1, request_retry_backoff_ms: 0,
  },
};

const $ = (id) => document.getElementById(id);

function setToday() {
  $("analysisDate").value = new Date().toISOString().slice(0, 10);
}

async function api(path, options = {}, requestPolicy = {}) {
  const maximumAttempts = Math.max(1, Number(requestPolicy.maxAttempts || 1));
  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeoutMs = Number(requestPolicy.timeoutMs || 0);
    const timeout = timeoutMs > 0 ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const response = await fetch(path, { ...options, signal: controller.signal });
      const raw = await response.text();
      let data = {};
      try { data = raw ? JSON.parse(raw) : {}; }
      catch { throw new Error(`服务返回了无法解析的数据（HTTP ${response.status}）`); }
      if (!response.ok) {
        const legacyRoute = response.status === 404 && data.error === "Unknown API route";
        const error = new Error(legacyRoute
          ? "后端服务仍是旧版本，请重启项目后刷新页面。"
          : (data.error || `请求失败（HTTP ${response.status}）`));
        error.retryable = response.status >= 500;
        error.serviceVersionMismatch = legacyRoute;
        error.loginRequired = response.status === 401 && data.login_required === true;
        if (error.loginRequired) showLoginView();
        throw error;
      }
      return { data, response };
    } catch (error) {
      const retryable = error.name !== "AbortError" && (error instanceof TypeError || error.retryable);
      if (!retryable || attempt >= maximumAttempts) {
        if (error.name === "AbortError") throw new Error(`请求超过 ${Math.round(timeoutMs / 1000)} 秒，已停止等待`);
        if (error instanceof TypeError) throw new Error("本地服务连接中断，请确认服务仍在运行");
        throw error;
      }
      const backoffMs = Math.max(0, Number(requestPolicy.retryBackoffMs || 0)) * attempt;
      if (backoffMs > 0) await new Promise((resolve) => window.setTimeout(resolve, backoffMs));
    } finally {
      if (timeout != null) window.clearTimeout(timeout);
    }
  }
  throw new Error("请求未完成");
}

function text(element, value) { element.textContent = value ?? "—"; }

function renderAccessCapacity(payload = {}) {
  const capacity = payload.capacity || {};
  const active = Number(capacity.active_users || 0);
  const maximum = Number(capacity.maximum_active_users || 0);
  const loginCapacity = $("loginCapacity");
  if (loginCapacity) {
    loginCapacity.replaceChildren();
    const seats = document.createElement("span");
    const dataMode = document.createElement("span");
    text(seats, maximum > 0 ? `测试席位 ${active}/${maximum}` : "测试席位读取中");
    text(dataMode, "仅生产数据 / 核验缓存");
    loginCapacity.append(seats, dataMode);
  }
}

function configureLoginVisual(payload = {}) {
  const visual = payload.login_visual || {};
  const messages = Array.isArray(visual.back_messages)
    ? visual.back_messages.filter((message) => typeof message === "string" && message.trim())
    : [];
  const palette = Array.isArray(visual.back_message_palette)
    ? visual.back_message_palette.filter((color) => typeof color === "string" && /^#[0-9a-f]{6}$/i.test(color))
    : [];
  state.loginVisual = { back_messages: messages, back_message_palette: palette };
  document.querySelector(".login-visual")?.dispatchEvent(new CustomEvent("login-visual-config"));
}

function renderTeamMetrics(health = {}) {
  state.teamHealth = health;
  const metrics = health.research_capacity || {};
  const access = health.test_access || {};
  text($("sessionUser"), state.session?.user?.display_name || "—");
  text($("analysisCount"), Number(metrics.analysis_jobs || 0));
  text($("modelReasoningCount"), Number(metrics.model_explanations || 0));
  renderAccessCapacity({
    capacity: {
      active_users: access.active_users,
      maximum_active_users: access.maximum_active_users,
    },
  });
}

function showLoginView(sessionPayload = null) {
  state.session = sessionPayload?.authenticated ? sessionPayload : null;
  $("loginView").hidden = false;
  $("appShell").hidden = true;
  $("committeeModal").hidden = true;
  document.body.classList.add("login-active");
  if (state.tickerTimer) window.clearTimeout(state.tickerTimer);
  state.tickerTimer = null;
  state.tickerTrackedCount = 0;
  if (sessionPayload) renderAccessCapacity(sessionPayload);
  if (sessionPayload) configureLoginVisual(sessionPayload);
  document.querySelector(".login-visual")?.dispatchEvent(new CustomEvent("login-characters-reset"));
  window.setTimeout(() => $("loginAccount")?.focus(), 30);
}

function showAppView(sessionPayload) {
  document.querySelector(".login-visual")?.dispatchEvent(new CustomEvent("login-characters-suspend"));
  state.session = sessionPayload;
  $("loginView").hidden = true;
  $("appShell").hidden = false;
  document.body.classList.remove("login-active");
  text($("sessionUser"), sessionPayload?.user?.display_name || "测试用户");
}

function initializeLoginCharacters() {
  const visual = document.querySelector(".login-visual");
  const stage = $("loginCharacterStage");
  const account = $("loginAccount");
  const password = $("loginPassword");
  const passwordToggle = $("togglePassword");
  if (!visual || !stage || !account || !password || !passwordToggle) return;

  const characters = [...stage.querySelectorAll("[data-character]")];
  const motionFactors = [0.72, 0.86, 1, 1.08];
  const motion = characters.map(() => ({ bodyX: 0, skew: 0, faceX: 0, faceY: 0 }));
  const pointer = { x: 0, y: 0 };
  let animationFrame = null;
  let blinkTimer = null;
  let blinkReleaseTimer = null;
  let previousBackMessages = new Set();
  let backMessageCycle = 0;

  const shuffled = (values) => {
    const copy = [...values];
    for (let index = copy.length - 1; index > 0; index -= 1) {
      const target = Math.floor(Math.random() * (index + 1));
      [copy[index], copy[target]] = [copy[target], copy[index]];
    }
    return copy;
  };

  const refreshBackMessages = () => {
    const pool = state.loginVisual.back_messages;
    const palette = state.loginVisual.back_message_palette;
    if (pool.length < characters.length || palette.length === 0) return;
    let candidates = shuffled(pool.filter((message) => !previousBackMessages.has(message)));
    if (candidates.length < characters.length) candidates = [...candidates, ...shuffled(pool)];
    const selected = candidates.slice(0, characters.length);
    previousBackMessages = new Set(selected);
    characters.forEach((character, index) => {
      const label = character.querySelector(".character-back b");
      if (!label) return;
      text(label, selected[index]);
      character.style.setProperty("--back-accent", palette[(backMessageCycle + index) % palette.length]);
      character.style.setProperty("--back-tilt", `${[-1.4, .8, -.6, 1.2][index] || 0}deg`);
      label.classList.remove("is-message-fresh");
      window.requestAnimationFrame(() => label.classList.add("is-message-fresh"));
    });
    backMessageCycle += 1;
  };

  const interactionPose = (index) => {
    const passwordPrivate = visual.classList.contains("is-password-private");
    const passwordVisible = visual.classList.contains("is-password-visible");
    if (passwordPrivate) {
      return [
        { bodyX: -3, skew: -1.1, faceX: 0, faceY: 0 },
        { bodyX: -2, skew: -.7, faceX: 0, faceY: 0 },
        { bodyX: 2, skew: .7, faceX: 0, faceY: 0 },
        { bodyX: 3, skew: 1.1, faceX: 0, faceY: 0 },
      ][index];
    }
    if (passwordVisible) {
      return [
        { bodyX: -1, skew: -.5, faceX: 0, faceY: 0 },
        { bodyX: -1, skew: -.35, faceX: 0, faceY: 0 },
        { bodyX: 1, skew: .35, faceX: 0, faceY: 0 },
        { bodyX: 1, skew: .5, faceX: 0, faceY: 0 },
      ][index];
    }
    if (visual.classList.contains("is-typing")) {
      return [
        { bodyX: 1, skew: 0.4, faceX: 2, faceY: 0 },
        { bodyX: 1, skew: 0.6, faceX: 2, faceY: 0 },
        { bodyX: 1, skew: 0.5, faceX: 2, faceY: 0 },
        { bodyX: 2, skew: 0.7, faceX: 2, faceY: 0 },
      ][index];
    }
    return { bodyX: 0, skew: 0, faceX: 0, faceY: 0 };
  };

  const renderMotion = () => {
    if ($("loginView").hidden || document.hidden) {
      animationFrame = null;
      return;
    }
    let unsettled = false;
    characters.forEach((character, index) => {
      const factor = motionFactors[index] || 1;
      const pose = interactionPose(index);
      const pointerWeight = visual.classList.contains("is-password-private") ? 0 : 1;
      const target = {
        bodyX: pointer.x * 7 * factor * pointerWeight + pose.bodyX,
        skew: -pointer.x * 3.1 * factor * pointerWeight + pose.skew,
        faceX: pointer.x * 9 * pointerWeight + pose.faceX,
        faceY: pointer.y * 5.2 * pointerWeight + pose.faceY,
      };
      Object.keys(target).forEach((key) => {
        const delta = target[key] - motion[index][key];
        motion[index][key] += delta * 0.105;
        if (Math.abs(delta) > 0.02) unsettled = true;
      });
      character.style.setProperty("--body-x", `${motion[index].bodyX.toFixed(2)}px`);
      character.style.setProperty("--body-skew", `${motion[index].skew.toFixed(2)}deg`);
      character.style.setProperty("--face-x", `${motion[index].faceX.toFixed(2)}px`);
      character.style.setProperty("--face-y", `${motion[index].faceY.toFixed(2)}px`);
    });
    stage.style.setProperty("--look-x", `${(pointer.x * 3.8).toFixed(2)}px`);
    stage.style.setProperty("--look-y", `${(pointer.y * 2.8).toFixed(2)}px`);
    animationFrame = unsettled ? window.requestAnimationFrame(renderMotion) : null;
  };

  const requestMotionFrame = () => {
    if ($("loginView").hidden || document.hidden) return;
    if (animationFrame == null) animationFrame = window.requestAnimationFrame(renderMotion);
  };

  const updatePointer = (event) => {
    pointer.x = Math.max(-1, Math.min(1, (event.clientX / window.innerWidth) * 2 - 1));
    pointer.y = Math.max(-1, Math.min(1, (event.clientY / window.innerHeight) * 2 - 1));
    requestMotionFrame();
  };

  const syncPrivacyState = () => {
    const wasPrivate = visual.classList.contains("is-password-private");
    const concealingPassword = password.type === "password"
      && (document.activeElement === password || password.value.length > 0);
    visual.classList.toggle("is-password-private", concealingPassword);
    if (concealingPassword && !wasPrivate) refreshBackMessages();
  };
  const syncFocusState = () => {
    const focused = document.activeElement === account || document.activeElement === password;
    visual.classList.toggle("is-typing", focused);
    visual.classList.toggle("is-password-focus", document.activeElement === password);
    syncPrivacyState();
    requestMotionFrame();
  };
  const syncPasswordState = () => {
    visual.classList.toggle("has-password", password.value.length > 0);
    visual.classList.toggle("is-password-visible", password.type === "text" && password.value.length > 0);
    syncPrivacyState();
    requestMotionFrame();
  };

  password.type = "password";
  passwordToggle.setAttribute("aria-pressed", "false");
  passwordToggle.setAttribute("aria-label", "显示密码");
  window.addEventListener("pointermove", updatePointer, { passive: true });
  [account, password].forEach((input) => {
    input.addEventListener("focus", syncFocusState);
    input.addEventListener("blur", () => window.setTimeout(syncFocusState, 0));
  });
  password.addEventListener("input", syncPasswordState);
  visual.addEventListener("login-password-visibility", syncPasswordState);
  visual.addEventListener("login-visual-config", refreshBackMessages);

  const clearBlink = () => {
    if (blinkTimer != null) window.clearTimeout(blinkTimer);
    if (blinkReleaseTimer != null) window.clearTimeout(blinkReleaseTimer);
    blinkTimer = null;
    blinkReleaseTimer = null;
    characters.forEach((character) => character.classList.remove("is-blinking"));
  };

  const scheduleBlink = () => {
    clearBlink();
    if ($("loginView").hidden || document.hidden) return;
    const delay = 2400 + Math.random() * 3600;
    blinkTimer = window.setTimeout(() => {
      blinkTimer = null;
      if (!visual.classList.contains("is-password-visible") && characters.length) {
        const character = characters[Math.floor(Math.random() * characters.length)];
        character.classList.add("is-blinking");
        blinkReleaseTimer = window.setTimeout(() => {
          character.classList.remove("is-blinking");
          blinkReleaseTimer = null;
          scheduleBlink();
        }, 150);
      } else {
        scheduleBlink();
      }
    }, delay);
  };

  const suspendCharacters = () => {
    if (animationFrame != null) window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
    clearBlink();
  };

  const resumeCharacters = ({ resetPassword = false } = {}) => {
    suspendCharacters();
    if (resetPassword) {
      password.type = "password";
      passwordToggle.setAttribute("aria-pressed", "false");
      passwordToggle.setAttribute("aria-label", "显示密码");
    }
    syncFocusState();
    syncPasswordState();
    requestMotionFrame();
    scheduleBlink();
  };

  visual.addEventListener("login-characters-suspend", suspendCharacters);
  visual.addEventListener("login-characters-reset", () => resumeCharacters({ resetPassword: true }));
  window.addEventListener("pageshow", () => {
    if (!$("loginView").hidden) resumeCharacters();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) suspendCharacters();
    else if (!$("loginView").hidden) resumeCharacters();
  });

  syncPasswordState();
  scheduleBlink();
}

function applyModelConfigurationPolicy(health) {
  const allowed = health?.test_access?.browser_model_configuration === true;
  ["modelProvider", "modelName", "modelKey", "clearModelKey"].forEach((id) => {
    const element = $(id);
    if (element) element.disabled = !allowed;
  });
  const submit = $("modelForm")?.querySelector('button[type="submit"]');
  if (submit) submit.disabled = !allowed;
  if (!allowed) {
    text($("modelStatus"), "团队测试模式由服务器环境变量统一配置模型与密钥；页面不接收或保存 API Key。");
  }
}

function appendModelInlineContent(element, value) {
  const pattern = /(\*\*[^*\n]+\*\*|【[^】\n]+】)/g;
  const content = String(value ?? "");
  let cursor = 0;
  for (const match of content.matchAll(pattern)) {
    if (match.index > cursor) element.append(document.createTextNode(content.slice(cursor, match.index)));
    const token = match[0];
    const part = document.createElement(token.startsWith("**") ? "strong" : "cite");
    if (token.startsWith("**")) {
      text(part, token.slice(2, -2));
    } else {
      part.className = "model-citation";
      text(part, token);
    }
    element.append(part);
    cursor = match.index + token.length;
  }
  if (cursor < content.length) element.append(document.createTextNode(content.slice(cursor)));
}

function renderModelInterpretation(value) {
  const root = $("modelInterpretation");
  root.replaceChildren();
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  let list = null;
  let listType = null;
  const closeList = () => { list = null; listType = null; };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line || line === "<!-- TRADINGOS_EXPLANATION_COMPLETE -->") {
      closeList();
      return;
    }
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    if (heading) {
      closeList();
      const section = document.createElement("h5");
      appendModelInlineContent(section, heading[1]);
      root.append(section);
      return;
    }
    const bullet = line.match(/^(?:[-*+]\s+)(.+)$/);
    const numbered = line.match(/^(?:\d+[.)、]\s*)(.+)$/);
    if (bullet || numbered) {
      const desiredType = numbered ? "ol" : "ul";
      if (!list || listType !== desiredType) {
        list = document.createElement(desiredType);
        listType = desiredType;
        root.append(list);
      }
      const item = document.createElement("li");
      appendModelInlineContent(item, (bullet || numbered)[1]);
      list.append(item);
      return;
    }
    closeList();
    const paragraph = document.createElement("p");
    appendModelInlineContent(paragraph, line);
    root.append(paragraph);
  });
}

function stockSymbolInput(value) {
  const symbol = value
    .normalize("NFKC")
    .replace(/[\s\u200B\u200C\u200D\u2060\uFEFF]+/g, "")
    .toUpperCase();
  const match = symbol.match(/^(\d{6})(?:\.?([A-Z]{2}))?$/);
  if (!match) {
    throw new Error("股票代码格式无效：请输入6位数字，例如 600519 或 301526.SZ。");
  }
  return match[2] ? `${match[1]}.${match[2]}` : match[1];
}

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
  state.modelProviders = status.providers;
  state.activeProviderId = status.active_provider;
  status.providers.forEach((provider) => {
    const option = document.createElement("option"); option.value = provider.id; text(option, provider.name); option.selected = provider.id === status.active_provider; select.append(option);
  });
  $("modelName").value = status.active_model || "";
  const active = status.providers.find((provider) => provider.id === status.active_provider);
  renderModelProviderIdentity(active);
  const last = status.last_execution;
  const executionText = last ? ` 最近执行：${last.provider_name}/${last.model} · ${last.status}。` : "";
  text($("modelStatus"), (active?.configured ? `${active.name} 已配置（密钥来源：${active.key_source}）。可勾选报告解释。` : `${active?.name || "当前模型"} 未配置。页面输入的密钥只保存到当前服务会话；重启后请重新输入或使用 ${active?.env_key || "环境变量"}。`) + executionText);
}

function renderModelProviderIdentity(provider) {
  text($("modelProviderName"), provider?.name || "未选择服务商");
  text($("modelProviderDefault"), provider ? `默认模型 · ${provider.default_model}` : "默认模型未提供");
}

function selectedModelProvider() {
  return state.modelProviders.find((provider) => provider.id === $("modelProvider").value);
}

function formatElapsed(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function setAnalysisPhases(statuses) {
  document.querySelectorAll("[data-progress-phase]").forEach((phase) => {
    phase.classList.remove("is-active", "is-complete", "is-failed");
    const status = statuses[phase.dataset.progressPhase];
    if (status) phase.classList.add(`is-${status}`);
  });
}

function startAnalysisProgress(payload) {
  const root = $("analysisProgress");
  const track = $("analysisProgressTrack");
  if (state.analysisProgressTimer) clearInterval(state.analysisProgressTimer);
  state.analysisStartedAt = Date.now();
  root.hidden = false;
  root.dataset.state = "running";
  track.removeAttribute("aria-valuenow");
  track.removeAttribute("aria-invalid");
  track.setAttribute("aria-valuetext", "服务端研判处理中");
  text($("analysisProgressTitle"), "证据链研判中");
  text($("analysisProgressElapsed"), "00:00");
  $("analysisProgressElapsed").setAttribute("datetime", "PT0S");
  text(
    $("analysisProgressDetail"),
    `已提交 ${payload.symbol} · 数据采集 → 确定性 Skills → 法庭质证${payload.model_explain ? " → 模型解释" : ""}。服务端完成后进入归档。`,
  );
  setAnalysisPhases({ prepare: "complete", research: "active" });
  state.analysisProgressTimer = setInterval(() => {
    const elapsed = Date.now() - state.analysisStartedAt;
    text($("analysisProgressElapsed"), formatElapsed(elapsed));
    $("analysisProgressElapsed").setAttribute("datetime", `PT${Math.floor(elapsed / 1000)}S`);
  }, 1000);
}

function finishAnalysisProgress(outcome, detail) {
  const root = $("analysisProgress");
  const track = $("analysisProgressTrack");
  if (state.analysisProgressTimer) clearInterval(state.analysisProgressTimer);
  state.analysisProgressTimer = null;
  const elapsed = state.analysisStartedAt ? Date.now() - state.analysisStartedAt : 0;
  text($("analysisProgressElapsed"), formatElapsed(elapsed));
  $("analysisProgressElapsed").setAttribute("datetime", `PT${Math.floor(elapsed / 1000)}S`);
  root.dataset.state = outcome;
  if (outcome === "success") {
    track.setAttribute("aria-valuenow", "100");
    track.setAttribute("aria-valuetext", "研判和归档已完成");
    text($("analysisProgressTitle"), "研判完成 · 已归档");
    text($("analysisProgressDetail"), detail);
    setAnalysisPhases({ prepare: "complete", research: "complete", present: "complete" });
  } else {
    track.removeAttribute("aria-valuenow");
    track.setAttribute("aria-invalid", "true");
    track.setAttribute("aria-valuetext", "研判未完成");
    text($("analysisProgressTitle"), "研判中断 · 未写入结论");
    text($("analysisProgressDetail"), detail);
    setAnalysisPhases({ prepare: "complete", research: "failed" });
  }
}

function setAnalyzeButton(running) {
  const button = $("analyzeButton");
  button.replaceChildren(document.createTextNode(running ? "研判进行中 " : "开始研判 "));
  const mark = document.createElement("b");
  text(mark, running ? "···" : "↗");
  button.append(mark);
}

function scoreTile(label, value) {
  const tile = document.createElement("div"); const title = document.createElement("span"); const number = document.createElement("strong");
  text(title, label); text(number, value); tile.append(title, number); return tile;
}

function money(value) { return value == null ? "—" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 }).format(value); }
function percentage(value) { return value == null ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`; }
function yi(value) { return value == null ? "—" : `${(Number(value) / 100000000).toFixed(2)}亿`; }
function shares(value) { return value == null ? "—" : new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value); }
function quoteStatusLabel(status) { return status === "real_time" ? "实时" : status === "latest_available" ? "最近交易日收盘" : "不可用"; }

function hasUsableQuote(item) {
  const quote = item?.quote;
  return (
    (quote?.data_status === "real_time" || quote?.data_status === "latest_available")
    && Number.isFinite(Number(quote?.price))
    && Number(quote.price) > 0
    && Boolean(quote?.trade_date)
  );
}

function watchRow(item, openDetail = false) {
  const row = document.createElement("div"); row.className = "watch-row";
  row.dataset.symbol = item.symbol;
  const main = document.createElement("div"); const symbol = document.createElement("strong"); const note = document.createElement("span");
  const snapshot = item.snapshot;
  text(symbol, `${item.symbol}${snapshot?.name ? ` · ${snapshot.name}` : ""}`);
  text(note, item.note || "未填写观察备注"); main.append(symbol, note);
  const quote = item.quote;
  if (!snapshot?.name && quote?.name) text(symbol, `${item.symbol} · ${quote.name}`);
  const price = document.createElement("b"); const meta = document.createElement("small");
  if (quote?.data_status === "real_time" || quote?.data_status === "latest_available") { text(price, quote.price?.toFixed(2)); price.className = quote.change_pct >= 0 ? "up" : "down"; text(meta, `${percentage(quote.change_pct)} · ${quoteStatusLabel(quote.data_status)} · ${quote.trade_date || ""}`); }
  else { text(price, "行情不可用"); price.className = "flat"; text(meta, quote?.error || "请刷新后重试"); }
  const advice = document.createElement("p"); text(advice, item.advice || "点击刷新实时行情以获取研究提示。");
  initializeRollingPrice(price, quote);
  price.classList.add("watch-live-price"); meta.dataset.role = "quote-meta";
  row.append(main, price, meta);
  if (snapshot) row.append(watchDetail(snapshot, openDetail));
  const actions = document.createElement("div"); actions.className = "watch-actions";
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "watch-remove-button";
  remove.setAttribute("aria-label", `将 ${item.symbol} 移出自选股`);
  text(remove, "移出自选");
  remove.addEventListener("click", () => deleteWatchlistItem(item.symbol, remove));
  actions.append(remove);
  row.append(advice, actions); return row;
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

async function deleteWatchlistItem(symbol, button) {
  if (!window.confirm(`将 ${symbol} 移出自选股？持仓、研判记录和复盘数据不会被删除。`)) return;
  button.disabled = true; text(button, "正在移出…");
  try {
    const { data } = await api(
      "/api/watchlist/remove",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
      },
    );
    if ((data.items || []).some((item) => item.symbol === symbol)) {
      throw new Error("服务端未确认删除，请稍后重试");
    }
    Array.from(document.querySelectorAll(".watch-row[data-symbol]"))
      .filter((row) => row.dataset.symbol === symbol)
      .forEach((row) => row.remove());
    if (!$("watchlistRows").querySelector(".watch-row")) renderWatchlist([]);
    syncTickerTrackingFromDom();
    text($("marketMessage"), `${symbol} 已移出自选股；持仓和历史研判保持不变。`);
  } catch (error) {
    button.disabled = false; text(button, "移出自选");
    text($("marketMessage"), `移出自选失败：${error.message}`);
  }
}

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
  row.dataset.symbol = position.symbol;
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
  const positionPrice = metrics.querySelector("em");
  if (positionPrice) initializeRollingPrice(positionPrice, quote);
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
  if (state.marketRefreshInFlight) return;
  state.marketRefreshInFlight = true;
  if (state.tickerTimer) window.clearTimeout(state.tickerTimer);
  const button = $("refreshMarket"); button.disabled = true; text($("marketMessage"), "正在请求固定公开行情源…");
  const requestPolicy = {
    timeoutMs: state.tickerConfig.request_timeout_ms,
    maxAttempts: state.tickerConfig.request_max_attempts,
    retryBackoffMs: state.tickerConfig.request_retry_backoff_ms,
  };
  try {
    const { data } = await api(
      "/api/market/refresh",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      requestPolicy,
    );
    const watchlist = data.watchlist || [];
    const keepPreviousSnapshot = (
      watchlist.length > 0
      && !watchlist.some(hasUsableQuote)
      && Boolean($("watchlistRows").querySelector(".watch-row"))
    );
    if (!keepPreviousSnapshot) {
      renderWatchlist(watchlist);
      renderPortfolio(data.portfolio);
    }
    const cacheNote = Number(data.cache_replay_count || 0) > 0
      ? `；${data.cache_replay_count} 只股票回放完整性校验通过的最近交易日快照，未标记为实时`
      : "";
    const retainedNote = keepPreviousSnapshot
      ? "；本轮未取得可核验的新快照，页面保留上次已显示结果"
      : "";
    text($("marketMessage"), `已刷新 · ${data.source}${cacheNote}${retainedNote}。请核对行情日期与时间。`);
  } catch (error) {
    text($("marketMessage"), `刷新未完成：${error.message}；页面保留上次结果并将自动重试。`);
  } finally {
    state.marketRefreshInFlight = false; button.disabled = false; scheduleTicker();
  }
}

function initializeRollingPrice(element, quote) {
  element.classList.add("live-price");
  const initialText = element.textContent;
  const value = document.createElement("span"); value.className = "rolling-number__value is-current";
  text(value, initialText); element.replaceChildren(value);
  if (quote?.price != null && Number.isFinite(Number(quote.price))) element.dataset.price = String(Number(quote.price));
  element.setAttribute("aria-live", "polite");
}

function animateRollingPrice(element, quote) {
  if (!element || quote?.price == null || !Number.isFinite(Number(quote.price))) return;
  const nextPrice = Number(quote.price); const previousPrice = Number(element.dataset.price);
  const direction = Number.isFinite(previousPrice) && nextPrice !== previousPrice ? (nextPrice > previousPrice ? "up" : "down") : "flat";
  const tone = direction === "flat" ? (Number(quote.change_pct) > 0 ? "up" : Number(quote.change_pct) < 0 ? "down" : "flat") : direction;
  element.classList.remove("up", "down", "flat", "is-rolling"); element.classList.add(tone);
  element.dataset.price = String(nextPrice); element.setAttribute("aria-label", `${nextPrice.toFixed(2)}，${direction === "up" ? "较上一笔上涨" : direction === "down" ? "较上一笔下跌" : "较上一笔不变"}`);
  if (!Number.isFinite(previousPrice) || direction === "flat" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const current = document.createElement("span"); current.className = "rolling-number__value is-current"; text(current, nextPrice.toFixed(2)); element.replaceChildren(current); return;
  }
  const outgoing = document.createElement("span"); outgoing.className = "rolling-number__value is-current"; text(outgoing, previousPrice.toFixed(2));
  const incoming = document.createElement("span"); incoming.className = "rolling-number__value is-incoming"; text(incoming, nextPrice.toFixed(2));
  element.dataset.roll = direction; element.replaceChildren(outgoing, incoming);
  requestAnimationFrame(() => element.classList.add("is-rolling"));
  window.setTimeout(() => {
    const current = document.createElement("span"); current.className = "rolling-number__value is-current"; text(current, nextPrice.toFixed(2));
    element.replaceChildren(current); element.classList.remove("is-rolling"); delete element.dataset.roll;
  }, Number(state.tickerConfig.animation_duration_ms));
}

function configureTicker(config) {
  if (!config) return;
  state.tickerConfig = { ...state.tickerConfig, ...config };
  if (Number.isFinite(Number(config.animation_duration_ms))) document.documentElement.style.setProperty("--ticker-roll-duration", `${Number(config.animation_duration_ms)}ms`);
}

function scheduleTicker(delay = null) {
  if (state.tickerTimer) window.clearTimeout(state.tickerTimer);
  state.tickerTimer = null;
  if (document.hidden || state.tickerTrackedCount < 1 || !Number.isFinite(Number(state.tickerConfig.refresh_interval_ms))) return;
  const wait = delay == null ? Number(state.tickerConfig.refresh_interval_ms) : Math.max(0, Number(delay));
  state.tickerTimer = window.setTimeout(refreshTicker, wait);
}

async function refreshTicker() {
  if (state.tickerInFlight || state.marketRefreshInFlight || document.hidden) { scheduleTicker(); return; }
  state.tickerInFlight = true; setTickerStatus("正在同步轻量报价", "loading");
  try {
    const { data } = await api("/api/market/ticker", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    state.tickerTrackedCount = Number(data.tracked_count || 0);
    if (state.tickerTrackedCount < 1) { setTickerStatus("加入自选或持仓后自动报价", "paused"); return; }
    updateTrackedQuotes(data.quotes || {}); updatePortfolioTicker(data.portfolio);
    const tickerMessage = data.source === "unavailable"
      ? "实时源暂不可用，未使用历史收盘价冒充当前价；正在自动重试"
      : data.live_session
        ? `${Math.round(Number(data.refresh_interval_ms) / 1000)} 秒实时更新 · ${data.source}`
        : `最近交易日收盘价 · ${data.source} · ${Math.round(Number(data.refresh_interval_ms) / 1000)} 秒校验`;
    setTickerStatus(tickerMessage, data.source === "unavailable" ? "error" : data.live_session ? "live" : "paused");
    scheduleTicker(data.source === "unavailable" ? state.tickerConfig.error_backoff_ms : data.refresh_interval_ms);
  } catch (error) {
    setTickerStatus(`自动报价失败：${error.message}`, "error"); scheduleTicker(state.tickerConfig.error_backoff_ms);
  } finally { state.tickerInFlight = false; }
}

function updateTrackedQuotes(quotes) {
  Object.entries(quotes).forEach(([symbol, quote]) => {
    const row = Array.from(document.querySelectorAll(".watch-row[data-symbol]")).find((item) => item.dataset.symbol === symbol);
    if (!row) return;
    animateRollingPrice(row.querySelector(".watch-live-price"), quote);
    const name = row.querySelector("div > strong"); if (name && quote.name) text(name, `${symbol} · ${quote.name}`);
    const meta = row.querySelector('[data-role="quote-meta"]');
    if (meta) text(meta, `${percentage(quote.change_pct)} · ${quoteStatusLabel(quote.data_status)} · ${quote.trade_date || ""} ${quote.trade_time || ""}`);
  });
}

function updatePortfolioTicker(portfolio) {
  if (!portfolio) return;
  const fullyPriced = Number(portfolio.position_count || 0) === 0 || Number(portfolio.priced_positions || 0) === Number(portfolio.position_count || 0);
  if (fullyPriced) {
    const accountValues = [portfolio.cash_balance, portfolio.total_assets, portfolio.unrealized_pnl, portfolio.daily_pnl];
    document.querySelectorAll("#accountStats > div strong").forEach((element, index) => text(element, money(accountValues[index])));
  }
  (portfolio.positions || []).forEach((position) => {
    if (position.quote?.price == null || !Number.isFinite(Number(position.quote.price))) return;
    const row = Array.from(document.querySelectorAll(".position-row[data-symbol]")).find((item) => item.dataset.symbol === position.symbol);
    if (!row) return;
    animateRollingPrice(row.querySelector(".position-metrics em"), position.quote || {});
    const pnl = row.children[1]; if (pnl) { pnl.className = position.unrealized_pnl > 0 ? "up" : position.unrealized_pnl < 0 ? "down" : "flat"; text(pnl, `${money(position.unrealized_pnl)} / ${percentage(position.unrealized_pnl_pct)}`); }
    const metrics = row.querySelectorAll(".position-metrics em");
    if (metrics[1]) text(metrics[1], money(position.market_value));
    if (metrics[2]) text(metrics[2], money(position.cost_value));
    if (metrics[3]) text(metrics[3], money(position.daily_pnl));
  });
}

function setTickerStatus(message, tone) {
  const root = $("tickerStatus"); if (!root) return;
  root.dataset.state = tone; const label = root.querySelector("span"); text(label || root, message);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { if (state.tickerTimer) window.clearTimeout(state.tickerTimer); state.tickerTimer = null; setTickerStatus("页面已隐藏，自动报价暂停", "paused"); }
  else scheduleTicker(0);
});

function radarRow(title, meta, value, tone = "flat") {
  const row = document.createElement("div"); row.className = "radar-row";
  const main = document.createElement("div"); const name = document.createElement("strong"); const sub = document.createElement("span");
  text(name, title); text(sub, meta); main.append(name, sub);
  const score = document.createElement("b"); score.className = tone; text(score, value);
  row.append(main, score); return row;
}

function trackedMoverRow(item) {
  const flow = item.main_net_inflow == null ? "主力净流入：该源未提供" : `主力净流入 ${yi(item.main_net_inflow)} · 占比 ${percentage(item.main_net_inflow_ratio)}`;
  const speed = item.speed_pct == null ? "涨速：该源未提供" : `涨速 ${percentage(item.speed_pct)}`;
  const meta = `现价 ${money(item.price)} · 涨跌 ${percentage(item.change_pct)} · 成交额 ${yi(item.amount)} · ${flow} · ${speed} · ${item.trigger_reason}`;
  return radarRow(`${item.name || "未命名个股"} · ${item.symbol}`, meta, money(item.price), item.change_pct >= 0 ? "up" : "down");
}

function radarUnavailableRow(message) {
  const row = document.createElement("div"); row.className = "empty-state compact"; text(row, message); return row;
}

function renderMorningRadar(snapshot) {
  text($("morningRadarStatus"), `${snapshot.data_status} · ${snapshot.market_phase} · ${snapshot.as_of}`);
  text($("morningRadarMessage"), `${snapshot.shortline_read}${snapshot.error ? ` 数据源提示：${snapshot.error}` : ""}`);
  const inflow = $("sectorInflow"); const outflow = $("sectorOutflow"); const movers = $("fastMovers");
  const trackedOnly = snapshot.data_status === "tracked_universe";
  const postMarketSectorFallback = snapshot.source === "tushare_moneyflow_ind_ths";
  inflow.replaceChildren(); outflow.replaceChildren(); movers.replaceChildren();
  const sectorMeta = (item) => postMarketSectorFallback
    ? `最近完整交易日 · 涨跌 ${percentage(item.change_pct)} · 净额`
    : `涨跌 ${percentage(item.change_pct)} · 占比 ${percentage(item.main_net_inflow_ratio)}`;
  (snapshot.top_inflow_sectors || []).forEach((item) => inflow.append(radarRow(item.name, sectorMeta(item), yi(item.main_net_inflow), "up")));
  (snapshot.top_outflow_sectors || []).forEach((item) => outflow.append(radarRow(item.name, sectorMeta(item), yi(item.main_net_inflow), "down")));
  (snapshot.fast_movers || []).forEach((item) => movers.append(radarRow(`${item.name} ${item.symbol}`, `${percentage(item.change_pct)} · 涨速 ${percentage(item.speed_pct)} · ${item.trigger_reason}`, yi(item.amount), item.change_pct >= 0 ? "up" : "down")));
  if (!inflow.children.length) inflow.append(emptyRadar());
  if (!outflow.children.length) outflow.append(emptyRadar());
  if (!movers.children.length) movers.append(emptyRadar());
  if (trackedOnly) {
    inflow.replaceChildren(radarUnavailableRow("全市场板块资金流接口暂不可用；不展示或推断流入板块。"));
    outflow.replaceChildren(radarUnavailableRow("全市场板块资金流接口暂不可用；不展示或推断流出板块。"));
    movers.replaceChildren();
    (snapshot.fast_movers || []).forEach((item) => movers.append(trackedMoverRow(item)));
    if (!movers.children.length) movers.append(radarUnavailableRow("当前自选、持仓与机会池中没有可核验报价。"));
  }
  if (postMarketSectorFallback && !movers.children.length) {
    movers.replaceChildren(radarUnavailableRow("备选源为盘后行业资金，不提供盘中急拉个股。"));
  }
}

function emptyRadar() { const empty = document.createElement("div"); empty.className = "empty-state compact"; text(empty, "暂无数据。"); return empty; }

async function refreshMorningRadar() {
  const button = $("refreshMorningRadar"); button.disabled = true; text($("morningRadarMessage"), "正在刷新实时板块资金流与急拉个股…");
  try { const { data } = await api("/api/morning/radar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 6 }) }); renderMorningRadar(data); }
  catch (error) { text($("morningRadarMessage"), `刷新失败：${error.message}`); } finally { button.disabled = false; }
}

function renderReport(report) {
  $("emptyReport").hidden = true; $("reportContent").hidden = false;
  renderScenarioPanel(report);
  text($("reportDate"), report.analysis_date); text($("reportSymbol"), report.symbol); text($("reportTitle"), report.name);
  const realtime = report.realtime_quote;
  const dataLabel = `研究数据：${report.data_status || "未知"}`;
  text($("realtimeReport"), realtime ? `${dataLabel} · 实时参考 · ${realtime.source || "unknown"} · ${realtime.price ?? "不可用"} · ${percentage(realtime.change_pct)} · ${realtime.trade_date || ""} ${realtime.trade_time || ""} · ${realtime.data_status}` : `${dataLabel} · 未请求实时行情上下文`);
  text($("verdict"), report.conclusion); $("verdict").dataset.risk = report.risk_level;
  const scores = $("scores"); scores.replaceChildren();
  [["基本", report.fundamental_score], ["技术", report.technical_score], ["资金", report.capital_flow_score], ["题材", report.theme_score]].forEach(([label, value]) => scores.append(scoreTile(label, value)));
  renderDecisionBrief(report.decision_brief);
  text($("actionPlan"), report.action_plan);
  const risks = $("risks"); risks.replaceChildren(); (report.risk_factors || []).slice(0, 4).forEach((risk) => { const li = document.createElement("li"); text(li, risk); risks.append(li); });
  const skills = $("skills"); skills.replaceChildren(); (report.skill_insights || []).filter((skill) => !["next_session_scenario", "price_observation_zones"].includes(skill.details?.mode)).forEach((skill) => {
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
  const committee = (report.skill_insights || []).find((skill) => skill.category === "committee");
  state.committee = normalizeCommitteeCourt(committee);
  $("committeeButton").hidden = !state.committee;
  if (state.committee) renderCommitteeCourt(state.committee);
  const model = $("modelSection"); model.hidden = !report.model_interpretation;
  const execution = report.model_execution;
  text($("modelInterpretationTitle"), execution ? `${execution.provider_name} · ${execution.model} 解释` : "模型解释");
  renderModelInterpretation(report.model_interpretation);
}

function renderDecisionBrief(brief) {
  const root = $("decisionBrief");
  root.replaceChildren();
  root.hidden = !brief || typeof brief !== "object";
  if (root.hidden) return;

  const boundary = brief.data_boundary || {};
  const head = document.createElement("div"); head.className = "evidence-brief__head";
  const heading = document.createElement("div");
  const eyebrow = document.createElement("span"); eyebrow.className = "evidence-brief__eyebrow"; text(eyebrow, "EVIDENCE BRIEF");
  const title = document.createElement("h4"); text(title, brief.headline || "证据裁决简报");
  const thesis = document.createElement("p"); text(thesis, brief.thesis || "暂无论据摘要。");
  heading.append(eyebrow, title, thesis);
  const badge = document.createElement("b"); badge.className = "evidence-brief__badge";
  text(badge, `${boundary.status || "数据未知"} · ${boundary.traceable_finding_count ?? 0}/${boundary.total_finding_count ?? 0} 可追溯`);
  head.append(heading, badge); root.append(head);

  const evidenceGrid = document.createElement("div"); evidenceGrid.className = "evidence-claim-grid";
  const claims = Array.isArray(brief.decisive_evidence) ? brief.decisive_evidence : [];
  if (!claims.length) evidenceGrid.append(evidenceBriefEmpty("没有具备来源和时间的决定性证据。"));
  claims.forEach((claim, index) => evidenceGrid.append(renderEvidenceClaim(claim, index)));
  root.append(evidenceGrid);

  const challengeGrid = document.createElement("div"); challengeGrid.className = "evidence-challenge-grid";
  challengeGrid.append(
    evidenceBriefList("最强反证", (brief.strongest_counter_evidence || []).map((item) => `${item.domain}：${item.claim}${item.why_it_matters ? `；${item.why_it_matters}` : ""}`), "暂无可追溯反证。"),
    evidenceBriefList("失效条件", brief.invalidation_conditions || [], "尚未形成可观察失效条件。"),
  );
  root.append(challengeGrid);

  const court = brief.court || {};
  const profile = brief.profile_fit || {};
  const synthesis = document.createElement("div"); synthesis.className = "evidence-synthesis";
  const courtTitle = document.createElement("strong"); text(courtTitle, court.status === "decided" ? `${court.winner || "当前路线"}领先` : "委员会未形成路线优势");
  const courtMeta = document.createElement("span");
  text(courtMeta, court.status === "decided" ? `${court.runner_up || "第二路线未知"} · 领先 ${court.score_gap ?? "—"} 分 · ${court.reliability || "可靠性未标注"}` : court.verdict || "证据门禁拒绝比较。");
  const courtText = document.createElement("p"); text(courtText, court.action || court.verdict || "等待补齐证据。");
  const profileText = document.createElement("p"); profileText.className = "profile-fit-line"; text(profileText, `画像适配：${profile.conclusion || "未取得用户画像适配结论"}`);
  synthesis.append(courtTitle, courtMeta, courtText, profileText); root.append(synthesis);

  const gaps = brief.critical_data_gaps || [];
  if (gaps.length) {
    const gapPanel = document.createElement("details"); gapPanel.className = "evidence-gaps";
    const summary = document.createElement("summary"); text(summary, `关键数据缺口 · ${gaps.length} 项（已去重）`);
    const list = document.createElement("ul");
    gaps.forEach((gap) => { const li = document.createElement("li"); text(li, `${gap.dataset} · ${gap.status}${gap.as_of ? ` · ${gap.as_of}` : ""}：${gap.reason}`); list.append(li); });
    gapPanel.append(summary, list); root.append(gapPanel);
  }
}

function renderEvidenceClaim(claim, index) {
  const card = document.createElement("article"); card.className = `evidence-claim ${claim.direction === "约束" ? "is-caution" : "is-support"}`;
  const meta = document.createElement("span"); text(meta, `0${index + 1} · ${claim.domain || "未知维度"} · ${claim.direction || "观察"}`);
  const title = document.createElement("strong"); text(title, claim.claim || "未形成结论");
  const score = document.createElement("b"); text(score, `${claim.score ?? "—"} 分 · 置信 ${formatConfidence(claim.confidence)}`);
  const observations = document.createElement("ul");
  (claim.observations || []).forEach((item) => { const li = document.createElement("li"); text(li, item); observations.append(li); });
  const sources = document.createElement("p"); sources.className = "evidence-source-line";
  text(sources, (claim.sources || []).map((source) => `${source.id}｜${source.as_of}｜${source.title}`).join("；") || "无可追溯来源");
  card.append(meta, title, score, observations, sources); return card;
}

function evidenceBriefList(titleText, items, emptyText) {
  const section = document.createElement("section"); const title = document.createElement("h5"); const list = document.createElement("ul");
  text(title, titleText); (items.length ? items : [emptyText]).forEach((item) => { const li = document.createElement("li"); text(li, item); list.append(li); });
  section.append(title, list); return section;
}

function evidenceBriefEmpty(message) {
  const empty = document.createElement("p"); empty.className = "evidence-brief__empty"; text(empty, message); return empty;
}

function formatConfidence(value) {
  const numeric = Number(value); return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : "—";
}

function renderScenarioPanel(report) {
  const panel = $("scenarioPanel");
  const insights = report.skill_insights || [];
  const scenario = insights.find((item) => item.details?.mode === "next_session_scenario");
  const zones = insights.find((item) => item.details?.mode === "price_observation_zones");
  panel.replaceChildren();
  panel.hidden = !scenario && !zones;
  if (panel.hidden) return;

  const header = document.createElement("div"); header.className = "scenario-panel__head";
  const heading = document.createElement("div");
  const eyebrow = document.createElement("span"); eyebrow.className = "scenario-panel__eyebrow"; text(eyebrow, "SCENARIO LAB");
  const title = document.createElement("h4"); text(title, "明日情景与价格观察区");
  heading.append(eyebrow, title);
  const badge = document.createElement("b"); badge.className = "scenario-panel__badge"; text(badge, "历史观察 ≠ 涨跌预测");
  header.append(heading, badge); panel.append(header);

  const grid = document.createElement("div"); grid.className = "scenario-grid";
  grid.append(renderNextSessionCard(scenario), renderPriceZoneCard(zones));
  panel.append(grid);
}

function renderNextSessionCard(insight) {
  const card = document.createElement("article"); card.className = "scenario-card next-session-card";
  card.append(scenarioCardHead("01", "同状态历史次日分布"));
  const details = insight?.details || {};
  if (!insight || details.available === false || !Number.isFinite(Number(details.sample_size)) || Number(details.sample_size) < 1) {
    card.append(scenarioEmpty(insight?.conclusion || "没有达到最小历史样本门槛，不显示百分比。"));
    return card;
  }
  const red = Number(details.red_rate_pct || 0); const flat = Number(details.flat_rate_pct || 0); const green = Number(details.green_rate_pct || 0);
  const values = document.createElement("div"); values.className = "scenario-rates";
  values.append(rateBlock("历史红盘频率", red, "up"), rateBlock("历史平盘频率", flat, "flat"), rateBlock("历史绿盘频率", green, "down"));
  const bar = document.createElement("div"); bar.className = "scenario-distribution"; bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", `历史样本中红盘 ${red.toFixed(1)}%，平盘 ${flat.toFixed(1)}%，绿盘 ${green.toFixed(1)}%`);
  [["up", red], ["flat", flat], ["down", green]].forEach(([kind, value]) => {
    const segment = document.createElement("i"); segment.className = kind; segment.style.width = `${Math.max(0, value)}%`; bar.append(segment);
  });
  const meta = document.createElement("p"); meta.className = "scenario-meta";
  text(meta, `${insight.stage} · n=${details.sample_size} · ${details.sample_start || "—"} 至 ${details.sample_end || "—"} · 来源 ${formatSourceIds(details.source_ids)}`);
  const audit = document.createElement("p"); audit.className = "scenario-meta";
  text(audit, `计数 红/平/绿=${details.red_count}/${details.flat_count}/${details.green_count} · 平盘阈值 ±${Number(details.flat_band_pct || 0).toFixed(2)}% · 红盘 Wilson 区间 ${formatPercentInterval(details.red_wilson_interval_pct)}`);
  const note = document.createElement("p"); note.className = "scenario-caveat";
  text(note, "仅表示相同状态在历史样本中的结果分布，不代表明日发生概率；未收盘日线不会参与统计。");
  card.append(values, bar, meta, audit, note); return card;
}

function renderPriceZoneCard(insight) {
  const card = document.createElement("article"); card.className = "scenario-card price-zone-card";
  card.append(scenarioCardHead("02", "多周期价格观察区"));
  const details = insight?.details || {};
  if (!insight || details.available === false || !details.short_term) {
    card.append(scenarioEmpty(insight?.conclusion || "价格历史或波动尺度不足，未生成区间。"));
    return card;
  }
  const price = document.createElement("div"); price.className = "zone-current";
  const priceLabel = document.createElement("span"); text(priceLabel, "当前收盘参考");
  const priceValue = document.createElement("strong"); text(priceValue, formatPrice(details.current_price)); price.append(priceLabel, priceValue);
  const zoneGrid = document.createElement("div"); zoneGrid.className = "zone-grid";
  zoneGrid.append(
    zoneBlock("短线低位观察区", details.short_term.support_zone, "support"),
    zoneBlock("短线反弹压力区", details.short_term.resistance_zone, "resistance"),
    zoneBlock("中期支撑观察区", details.medium_term?.support_zone, "support"),
    zoneBlock("中期压力观察区", details.medium_term?.resistance_zone, "resistance")
  );
  const conditions = document.createElement("div"); conditions.className = "zone-conditions";
  const invalid = document.createElement("span"); text(invalid, `跌破失效参考 ${formatPrice(details.short_term.invalidation_below)}`);
  const confirm = document.createElement("span"); text(confirm, `突破确认参考 ${formatPrice(details.short_term.confirmation_above)}`);
  conditions.append(invalid, confirm);
  const longTerm = document.createElement("p"); longTerm.className = "scenario-caveat";
  text(longTerm, details.long_term?.available ? `长期估值观察区 ${formatZone(details.long_term.target_zone)}` : `长期：${details.long_term?.reason || "估值历史不足，不生成目标价。"}`);
  const meta = document.createElement("p"); meta.className = "scenario-meta";
  text(meta, `ATR ${Number(details.atr || 0).toFixed(3)} · 截止 ${details.as_of || "—"} · 来源 ${formatSourceIds(details.source_ids)}`);
  card.append(price, zoneGrid, conditions, longTerm, meta); return card;
}

function scenarioCardHead(index, titleText) {
  const head = document.createElement("div"); head.className = "scenario-card__head";
  const indexElement = document.createElement("span"); text(indexElement, index);
  const title = document.createElement("h5"); text(title, titleText); head.append(indexElement, title); return head;
}

function rateBlock(label, value, kind) {
  const block = document.createElement("div"); block.className = `scenario-rate ${kind}`;
  const name = document.createElement("span"); text(name, label);
  const number = document.createElement("strong"); text(number, `${Number(value).toFixed(1)}%`); block.append(name, number); return block;
}

function formatPercentInterval(interval) {
  return Array.isArray(interval) && interval.length === 2 && interval.every((item) => Number.isFinite(Number(item)))
    ? `${Number(interval[0]).toFixed(1)}%–${Number(interval[1]).toFixed(1)}%` : "不可用";
}

function zoneBlock(label, zone, kind) {
  const block = document.createElement("div"); block.className = `zone-block ${kind}`;
  const name = document.createElement("span"); text(name, label);
  const value = document.createElement("strong"); text(value, formatZone(zone)); block.append(name, value); return block;
}

function scenarioEmpty(message) {
  const empty = document.createElement("div"); empty.className = "scenario-empty";
  const title = document.createElement("strong"); text(title, "证据不足，拒绝估计");
  const detail = document.createElement("p"); text(detail, message); empty.append(title, detail); return empty;
}

function formatZone(zone) {
  return Array.isArray(zone) && zone.length === 2 && zone.every((item) => Number.isFinite(Number(item)))
    ? `${Number(zone[0]).toFixed(2)} – ${Number(zone[1]).toFixed(2)}` : "暂不可用";
}

function formatPrice(value) { return value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "暂不可用"; }
function formatSourceIds(sourceIds) { return Array.isArray(sourceIds) && sourceIds.length ? sourceIds.join("、") : "未取得"; }

function normalizeCommitteeCourt(committee) {
  if (!committee) return null;
  const details = committee.details && typeof committee.details === "object" ? committee.details : {};
  const judge = details.judge && typeof details.judge === "object" ? details.judge : {};
  return {
    ...details,
    mode: "court",
    judge: {
      ...judge,
      verdict: judge.verdict || committee.conclusion || "委员会未形成可展示的裁决。",
      action: judge.action || committee.strategy || "等待可追溯的证据补齐后重新审查。",
    },
    factions: Array.isArray(details.factions) ? details.factions : [],
    cross_examination: Array.isArray(details.cross_examination) ? details.cross_examination : [],
    evidence: Array.isArray(committee.evidence) ? committee.evidence : [],
    risks: Array.isArray(committee.risks) ? committee.risks : [],
  };
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
  const judgeBox = $("committeeJudge");
  const root = $("committeeFactions");
  if (!judgeBox || !root) return;
  judgeBox.replaceChildren();
  const title = document.createElement("strong"); text(title, `${judge.role_label || "主审判官"}裁决：${judge.winner || "暂无优势"}`);
  const topic = document.createElement("em"); text(topic, `研讨问题：${judge.discussion_topic || "当前个股是否值得继续研究"}`);
  const meta = document.createElement("span"); text(meta, `${judge.winner_route || "—"} · 可靠性 ${judge.reliability || "—"} · 领先 ${judge.score_gap ?? "—"} 分`);
  const method = document.createElement("span"); text(method, judge.score_summary ? `${judge.score_summary}｜${judge.score_method || ""}` : judge.score_method || "");
  const verdict = document.createElement("p"); text(verdict, judge.verdict || "证据不足，保持观察。");
  const action = document.createElement("p"); action.className = "judge-action"; text(action, judge.action || "等待更高质量证据。");
  judgeBox.append(title, topic, meta, method, verdict, action);

  root.replaceChildren();
  const factions = Array.isArray(details.factions) ? details.factions : [];
  if (!factions.length) {
    root.append(committeeRefusalPanel(details));
    return;
  }
  factions.forEach((faction) => {
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

function committeeRefusalPanel(details) {
  const panel = document.createElement("article"); panel.className = "committee-refusal";
  const title = document.createElement("strong"); text(title, "本次未进入流派比较");
  const explanation = document.createElement("p");
  text(explanation, "这是数据质量门禁的裁决结果，不代表委员会数据丢失，也不会用默认分数补齐。请根据下列缺口补数后重新研判。");
  const readiness = details.data_readiness || {};
  const evidence = Array.isArray(readiness.evidence) && readiness.evidence.length ? readiness.evidence : details.evidence || [];
  const risks = Array.isArray(readiness.risks) && readiness.risks.length ? readiness.risks : details.risks || [];
  const status = document.createElement("span");
  text(status, `数据审查：${readiness.stage || "未通过或未提供"}${readiness.score == null ? "" : ` · ${readiness.score} 分`}`);
  panel.append(title, explanation, status, courtList("待核验证据", evidence), courtList("阻断原因 / 风险", risks));
  return panel;
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
    configureTicker(health.realtime_ticker);
    text($("serverStatus"), `${health.real_data_only ? "真实数据门禁" : "研究引擎"}已就绪 · ${health.data_provider}`);
    renderProfile(profile); renderTools(tools.tools); renderPlaybooks(playbooks); renderWatchlist(watchlist.items); renderPortfolio(portfolio); renderModels(models); renderTeamMetrics(health); applyModelConfigurationPolicy(health);
  } catch (error) { text($("serverStatus"), `连接失败：${error.message}`); }
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("loginButton");
  button.disabled = true;
  text($("loginMessage"), "正在建立独立测试档案…");
  try {
    const { data } = await api("/api/session/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account: $("loginAccount").value.trim(),
        password: $("loginPassword").value,
        remember: $("rememberSession").checked,
      }),
    });
    $("loginPassword").value = "";
    document.querySelector(".login-visual")?.dispatchEvent(new CustomEvent("login-password-visibility"));
    text($("loginMessage"), "");
    showAppView(data);
    await loadDashboard();
  } catch (error) {
    text($("loginMessage"), error.message);
  } finally {
    button.disabled = false;
  }
});

$("togglePassword").addEventListener("click", () => {
  const input = $("loginPassword");
  const button = $("togglePassword");
  const reveal = input.type === "password";
  input.type = reveal ? "text" : "password";
  button.setAttribute("aria-pressed", String(reveal));
  button.setAttribute("aria-label", reveal ? "隐藏密码" : "显示密码");
  document.querySelector(".login-visual")?.dispatchEvent(new CustomEvent("login-password-visibility"));
  input.focus();
});

$("logoutButton").addEventListener("click", async () => {
  const button = $("logoutButton");
  button.disabled = true;
  try {
    const { data } = await api("/api/session/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    showLoginView(data);
    text($("loginMessage"), "已退出当前测试档案。");
    try {
      const { data: status } = await api("/api/session");
      renderAccessCapacity(status);
    } catch {}
  } catch (error) {
    text($("serverStatus"), `退出失败：${error.message}`);
  } finally {
    button.disabled = false;
  }
});

$("analysisForm").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = $("analyzeButton"); button.disabled = true; setAnalyzeButton(true); text($("formMessage"), "正在运行市场、技术、资金、风险与个人画像 Skills…");
  let payload;
  try {
    payload = { symbol: stockSymbolInput($("symbol").value), analysis_date: $("analysisDate").value, question: $("question").value.trim(), model_explain: $("modelExplain").checked, include_realtime: true };
    if (payload.model_explain) {
      payload.model_provider_id = $("modelProvider").value;
      payload.model_name = $("modelName").value.trim();
    }
    startAnalysisProgress(payload);
    const { data } = await api("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    state.lastSymbol = data.symbol; renderReport(data); finishAnalysisProgress("success", `${data.name}（${data.symbol}）报告已生成，分析与问答摘要已写入本地记忆。`); openCommittee(); text($("formMessage"), `已保存分析与问答摘要 · ${data.memory_event_id.slice(0, 8)}`); await loadDashboard();
  } catch (error) { finishAnalysisProgress("error", error.message); text($("formMessage"), `未完成：${error.message}`); } finally { button.disabled = false; setAnalyzeButton(false); }
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

$("modelProvider").addEventListener("change", () => {
  const provider = selectedModelProvider();
  renderModelProviderIdentity(provider);
  if (provider) $("modelName").value = provider.default_model;
  const active = state.modelProviders.find((item) => item.id === state.activeProviderId);
  text($("modelStatus"), `${provider?.name || "所选服务商"} 尚未保存；当前生效仍为 ${active?.name || "后端配置"}。请先配置并保存，再开始研判。`);
});

$("refreshMarket").addEventListener("click", refreshMarket);
$("refreshMorningRadar").addEventListener("click", refreshMorningRadar);
$("committeeButton").addEventListener("click", openCommittee);
$("closeCommittee").addEventListener("click", closeCommittee);
$("committeeModal").addEventListener("click", (event) => { if (event.target === $("committeeModal")) closeCommittee(); });

$("watchlistForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { const symbol = stockSymbolInput($("watchSymbol").value); const { data } = await api("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, note: $("watchNote").value.trim() }) }); renderWatchlist(data.items); $("watchSymbol").value = ""; $("watchNote").value = ""; text($("marketMessage"), "已加入自选；点击刷新获取实时行情。"); }
  catch (error) { text($("marketMessage"), error.message); }
});

$("cashForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { const { data } = await api("/api/portfolio/cash", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cash_balance: $("cashBalance").value }) }); renderPortfolio({ ...data, total_assets: data.cash_balance, cost_value: 0, market_value: 0, unrealized_pnl: 0, daily_pnl: 0 }); text($("marketMessage"), "账户可用余额已保存到本地档案。"); } catch (error) { text($("marketMessage"), error.message); }
});

$("positionForm").addEventListener("submit", async (event) => {
  event.preventDefault(); try { await api("/api/portfolio/position", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: stockSymbolInput($("positionSymbol").value), quantity: $("positionQty").value, cost_price: $("positionCost").value }) }); $("positionForm").reset(); await refreshMarket(); text($("marketMessage"), "持仓已保存并刷新估值。"); } catch (error) { text($("marketMessage"), error.message); }
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

function syncTickerTrackingFromDom() {
  state.tickerTrackedCount = new Set([
    ...Array.from(document.querySelectorAll(".watch-row[data-symbol]"), (row) => row.dataset.symbol),
    ...Array.from(document.querySelectorAll(".position-row[data-symbol]"), (row) => row.dataset.symbol),
  ]).size;
  if (state.tickerTrackedCount > 0) scheduleTicker(0);
  else setTickerStatus("加入自选或持仓后自动报价", "paused");
}

["watchlistRows", "positionRows"].forEach((id) => {
  const root = $(id); if (root) new MutationObserver(syncTickerTrackingFromDom).observe(root, { childList: true });
});

async function bootstrap() {
  setToday();
  try {
    const { data } = await api("/api/session");
    renderAccessCapacity(data);
    if (data.authenticated) {
      showAppView(data);
      await loadDashboard();
    } else {
      showLoginView(data);
    }
  } catch (error) {
    showLoginView();
    text($("loginMessage"), `服务连接失败：${error.message}`);
  }
}

initializeLoginCharacters();
bootstrap();
