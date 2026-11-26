// The ask panel (#/ask, #/ask/<conversation>): a question goes to the server, a model there
// answers it through the catalog tools, and this view polls the run's events and draws
// them as they arrive. The page never runs SQL and never changes the catalog: the only
// write is a 待确认 gap the reader chooses to record -- one click on 「记入待确认」 beside a
// placeholder, with a definition when the reader types one -- sent to the pending file
// through POST /api/pending when the server has one (the model has no tool that writes it;
// a gap someone already recorded is reported, not appended again). Model text and catalog text are untrusted:
// they only ever become text nodes. When the server lists several models, a picker lets
// the reader choose the one that answers each question; the last choice is remembered in
// this browser (localStorage, when the browser allows it).

import { api, badge, code, fold, grid, h, joined, text } from "./dom.js";
import {
  REASON_TEXT, SEVERITY_TEXT, STATUS_TEXT, TOOL_TEXT, modelOptionText, pendingPayload, pendingResult,
  pickModel, questionLength, usageText, viewModel,
} from "./askview.js";

const MODEL_KEY = "scope-lineage-service.ask.model";

function remembered() {
  try {
    return window.localStorage.getItem(MODEL_KEY);
  } catch (error) {
    return null;
  }
}

function remember(id) {
  try {
    window.localStorage.setItem(MODEL_KEY, id);
  } catch (error) {
    // private window or blocked storage: the picker just starts on the default next time
  }
}

const KIND_TEXT = { concept: "概念", metric: "指标", attribute: "属性", identifier: "标识", code_set: "码值集", table: "表" };

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }
  return { status: response.status, body };
}

function message(body, status) {
  return body && body.error ? body.error.message : `请求失败（HTTP ${status}）`;
}

function setHash(conversation) {
  const target = conversation ? `#/ask/${encodeURIComponent(conversation)}` : "#/ask";
  if (window.location.hash !== target) window.history.replaceState(null, "", target);
}

// ------------------------------------------------------------------ the view

export async function ask(id) {
  const { status, body } = await api("/api/ask/status");
  if (status === 404) return notConfigured(body);
  if (status !== 200) throw new Error(message(body, status));
  if (!body.available) return unavailable(body);
  const panel = new Panel(body);
  if (id) await panel.resume(id);
  return [panel.root];
}

function notConfigured(body) {
  return [
    h("h1", {}, "问数"),
    h("p", { class: "error" }, "问数面板没有启用。"),
    h("p", {}, "启动服务时加 ", code("--ask"), " 才会启用：每个问题都会在服务器上调用模型，产生费用，",
      "并把问题和工具返回的目录文字发给模型提供方；凭据从服务器的环境里取，不经过浏览器。"),
    h("p", {}, "没有密钥时，可以加 ", code("--ask-dev-fake-model"), " 预览这个页面：假模型按脚本调用目录工具，",
      "不调用任何模型，答案不能当真。"),
    body && body.error ? h("p", { class: "muted" }, body.error.message) : null,
  ];
}

function unavailable(info) {
  return [
    h("h1", {}, "问数"),
    h("p", { class: "error" }, "问数面板现在用不了：", text(info.reason)),
    h("p", { class: "muted" }, "浏览目录不受影响。补上原因里说的东西后重启服务。"),
  ];
}

class Panel {
  constructor(info) {
    this.info = info;
    this.conversation = null;
    this.running = null;
    this.runs = h("div", { class: "ask-runs" });
    // No maxlength: the browser would cut a long paste silently; the length note says when
    // it is over the server's limit and send() refuses it.
    this.maxChars = info.max_question_chars;
    this.question = h("textarea", { id: "ask-question", rows: "3",
      placeholder: "问一个数据问题，比如：上个月新增了多少客户？也可以贴一段 SQL 让它审查或解释。",
      "aria-label": "数据问题" });
    this.length = h("p", { class: "muted ask-length", "aria-live": "polite" },
      questionLength("", this.maxChars).text);
    this.question.addEventListener("input", () => this.showLength());
    this.submit = h("button", { type: "submit" }, "提问");
    this.stop = h("button", { type: "button", onclick: () => this.cancel() }, "停止");
    this.fresh = h("button", { type: "button", onclick: () => this.restart() }, "新对话");
    this.status = h("p", { class: "muted", role: "status" });
    this.stop.disabled = true;
    this.models = info.models || [];
    this.picker = this.models.length > 1 ? modelPicker(this.models) : null;
    const form = h("form", { class: "ask-form", onsubmit: (event) => { event.preventDefault(); this.send(); } },
      this.question, this.length, h("div", { class: "ask-buttons" },
        this.picker ? h("label", { class: "ask-model" }, "模型 ", this.picker) : null,
        this.submit, this.stop, this.fresh, this.status));
    this.question.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); this.send(); }
    });
    this.root = h("div", { class: "ask" },
      h("h1", {}, "问数", info.fake ? badge("假模型", "warn") : null),
      info.fake ? h("div", { class: "fake-banner", role: "alert" },
        h("strong", {}, "开发用假模型。"),
        "服务以 --ask-dev-fake-model 启动：没有调用任何模型，下面的过程和答案是脚本按目录拼出来的，不是答案。")
        : this.picker ? h("p", { class: "ask-notice" },
          "每个问题都会在服务器上调用所选的模型，产生费用，",
          "并把问题、工具返回的目录文字和写出的 SQL 发给那个模型的提供方。不同模型的回答质量不同。")
        : h("p", { class: "ask-notice" },
          `每个问题都会在服务器上调用模型（${text(info.model)}，effort ${text(info.effort)}），产生费用，`,
          "并把问题、工具返回的目录文字和写出的 SQL 发给模型提供方。"),
      h("p", { class: "muted" },
        "模型按目录工具（检索、取数包、查询、SQL 检查）写 SQL；不执行 SQL，也不改目录。",
        info.pending ? "模型不会替你记待确认：要记就在答案的「待确认」下点「记入待确认」。" : "",
        "追问带上一题的简报，不带全部记录。",
        `对话只存在服务内存里：服务重启或闲置超过 ${Math.round(info.conversations.max_idle_seconds / 60)} 分钟就没了。`,
        `每题上限：${info.limits.max_turns} 轮、${info.limits.max_tool_calls} 次工具调用、`,
        `${info.limits.max_output_tokens} 个输出 token、${info.limits.max_seconds} 秒。`),
      form, this.runs);
  }

  showLength() {
    const length = questionLength(this.question.value, this.maxChars);
    this.length.textContent = length.text;
    this.length.className = length.over ? "error ask-length" : "muted ask-length";
    return length;
  }

  setBusy(busy) {
    this.submit.disabled = busy;
    this.stop.disabled = !busy;
    this.status.textContent = busy ? "回答中……" : "";
  }

  restart() {
    if (this.running) return;
    this.conversation = null;
    this.runs.replaceChildren();
    setHash(null);
    this.question.focus();
  }

  async resume(conversation) {
    const { status, body } = await api("/api/ask/conversation", { conversation });
    if (status !== 200) {
      this.runs.append(h("p", { class: "error" }, message(body, status), " 可以直接开始新对话。"));
      setHash(null);
      return;
    }
    this.conversation = conversation;
    for (const run of body.runs) this.follow(run.run, run.question);
  }

  async send() {
    const question = this.question.value.trim();
    if (!question || this.running) return;
    if (this.showLength().over) {
      this.question.focus();
      return;
    }
    this.setBusy(true);
    const payload = { question };
    if (this.conversation) payload.conversation = this.conversation;
    if (this.picker && this.picker.value) payload.model = this.picker.value;
    const { status, body } = await postJson("/api/ask", payload);
    if (status !== 202) {
      this.setBusy(false);
      this.status.textContent = message(body, status);
      if (status === 404 && this.conversation) {
        this.conversation = null;
        setHash(null);
        this.status.textContent += "（下一问会开新对话）";
      }
      return;
    }
    this.conversation = body.conversation;
    setHash(body.conversation);
    this.question.value = "";
    this.showLength();
    this.follow(body.run, question);
  }

  async cancel() {
    if (!this.conversation) return;
    this.stop.disabled = true;
    const { status, body } = await postJson("/api/ask/cancel", { conversation: this.conversation });
    if (status !== 200) this.status.textContent = message(body, status);
  }

  async follow(runId, question) {
    const box = h("section", { class: "ask-run" }, h("h2", {}, question));
    this.runs.prepend(box); // newest first: the answer just asked for sits right under the form
    const events = [];
    let after = 0;
    for (;;) {
      const { status, body } = await api("/api/ask/events",
        { conversation: this.conversation, run: runId, after, wait: 20 });
      if (!this.root.isConnected && after > 0) return; // the reader went to another view
      if (status !== 200) {
        box.append(h("p", { class: "error" }, message(body, status)));
        break;
      }
      events.push(...body.events);
      after = body.next;
      const vm = viewModel(events);
      if (!body.done) { this.running = runId; this.setBusy(true); }
      drawRun(box, vm, this);
      if (body.done) break;
    }
    if (this.running === runId || this.running === null) {
      this.running = null;
      this.setBusy(false);
    }
  }
}

function modelPicker(models) {
  const picked = pickModel(models, remembered());
  const select = h("select", { id: "ask-model", "aria-label": "回答这个问题的模型",
    onchange: () => remember(select.value) },
  models.map((model) => h("option", {
    value: model.id, disabled: !model.available, selected: model.id === picked,
    title: model.available ? null : text(model.reason),
  }, modelOptionText(model))));
  return select;
}

// ------------------------------------------------------------------ one run

function drawRun(box, vm, panel) {
  const head = h("h2", {}, text(vm.question),
    vm.followUp ? badge("追问") : null,
    panel.picker && vm.modelLabel ? badge(vm.modelLabel) : null,
    panel.info.fake ? badge("假模型", "warn") : null,
    badge(STATUS_TEXT[vm.status] || vm.status, vm.status === "done" ? "ok" : vm.status === "running" ? null : "warn"));
  const steps = h("ol", { class: "ask-steps" }, vm.steps.map((step) => h("li", {}, drawStep(step))));
  // Once there is an answer the steps fold away, so it sits right under the question; a
  // run still going, or one that ended without an answer, keeps them in view.
  const folded = vm.answer && vm.status !== "running" && vm.steps.length;
  const parts = [head, folded ? fold(`过程（${vm.steps.length} 步）`, false, steps) : steps];
  if (vm.status === "running") parts.push(h("p", { class: "muted" }, `回答中…… 已用 ${vm.elapsed} 秒`));
  if (vm.answer) parts.push(drawAnswer(vm, panel));
  if (vm.status !== "running") parts.push(drawEnd(vm));
  box.replaceChildren(...parts);
}

function drawStep(step) {
  if (step.kind === "note") return h("div", { class: "ask-note" }, step.text);
  if (step.kind === "fallback") return h("p", { class: "muted" }, `${text(step.from)} 拒答，改由 ${text(step.to)} 接着回答。`);
  if (step.kind === "retry") return h("p", { class: "muted" }, "模型给的工具参数不是合法 JSON，重问了这一轮。");
  const title = h("div", { class: "ask-step-title" }, h("strong", {}, TOOL_TEXT[step.name] || step.name),
    step.round ? ` 第 ${step.round} 轮` : null, " ", describeInput(step));
  if (!step.done) return [title, h("p", { class: "muted" }, "进行中……")];
  if (!step.ok) return [title, h("p", { class: "error" }, text(step.error))];
  return [title, drawResult(step)];
}

function describeInput(step) {
  const input = step.input || {};
  if (step.name === "search_catalog") {
    return h("span", { class: "muted" }, `「${text(input.text)}」`, input.kinds && input.kinds.length
      ? `，只看 ${input.kinds.map((kind) => KIND_TEXT[kind] || kind).join("、")}` : null);
  }
  if (step.name === "query_catalog") return h("span", {}, code(input.kind), " ", code(input.term));
  if (step.name === "catalog_context") {
    const flags = [input.brief ? "brief" : null, input.focus ? "focus" : null].filter(Boolean);
    return flags.length ? h("span", { class: "muted" }, flags.join(" · ")) : null;
  }
  return null;
}

function drawResult(step) {
  const data = step.data || {};
  if (step.name === "search_catalog") {
    if (!data.hits || !data.hits.length) return h("p", { class: "muted" }, "没有候选。");
    return grid(["种类", "名称", "id", "在"], data.hits.map((hit) => [
      KIND_TEXT[hit.kind] || text(hit.kind), text(hit.name), code(hit.id), text(hit.where)]));
  }
  if (step.name === "query_catalog") {
    return data.matches && data.matches.length
      ? h("p", {}, "命中：", joined(data.matches.map((item) => code(item))))
      : h("p", { class: "muted" }, "没有命中。");
  }
  if (step.name === "catalog_context") {
    return h("div", { class: "ask-idents" },
      line("表", data.tables), line("列", data.columns), line("概念", data.concepts),
      data.missing && data.missing.length ? h("p", { class: "error" }, "没找到：", data.missing.join("、")) : null);
  }
  if (step.name === "check_sql") {
    const counts = `错误 ${data.errors || 0}，警告 ${data.warnings || 0}，提示 ${data.infos || 0}`;
    return [
      h("p", {}, counts),
      data.findings && data.findings.length ? h("ul", { class: "plain" }, data.findings.map((finding) =>
        h("li", {}, badge(SEVERITY_TEXT[finding.severity] || finding.severity,
          finding.severity === "info" ? null : "warn"), " ", code(finding.rule), " ", text(finding.message)))) : null,
      data.sql ? fold("这一轮检查的 SQL", false, h("pre", { class: "sql" }, data.sql)) : null,
    ];
  }
  return null;
}

function line(label, items) {
  if (!items || !items.length) return null;
  return h("p", {}, `${label}：`, joined(items.map((item) => code(item))));
}

function drawAnswer(vm, panel) {
  const answer = vm.answer;
  const parsed = answer.parsed;
  const parts = [h("h3", {}, "答案")];
  if (parsed.conclusion) parts.push(h("p", {}, h("strong", {}, "结论："), parsed.conclusion));
  if (answer.sql) parts.push(h("pre", { class: "sql" }, answer.sql));
  else parts.push(h("p", { class: "muted" }, "这题没有写 SQL。"));
  if (parsed.tables.length) {
    parts.push(h("h3", {}, "表和关联"), grid(["表", "一行是"], parsed.tables.map((item) => [code(item.text), item.basis])));
    if (parsed.joins.length) parts.push(h("ul", { class: "plain" }, parsed.joins.map((item) => h("li", {}, item))));
  }
  if (parsed.conditions.length) {
    parts.push(h("h3", {}, "条件和依据"),
      grid(["条件", "依据"], parsed.conditions.map((item) => [code(item.text, true), item.basis || "（没写依据）"])));
  }
  if (parsed.assumptions.length) {
    parts.push(h("h3", {}, "假设"), h("ul", { class: "plain" }, parsed.assumptions.map((item) => h("li", {}, item))));
  }
  parts.push(drawPlaceholders(vm, panel));
  if (answer.briefMissing) parts.push(h("p", { class: "error" }, "模型没有交回简报：追问会带上答案的开头。"));
  parts.push(fold("答案全文", false, h("div", { class: "ask-note" }, answer.text)));
  parts.push(fold("带给下一题的简报", false, h("pre", {}, answer.brief)));
  return h("div", { class: "ask-answer" }, parts);
}

function drawPlaceholders(vm, panel) {
  const holes = vm.answer.placeholders || [];
  const parts = [h("h3", {}, "待确认")];
  if (!holes.length) {
    parts.push(h("p", { class: "muted" }, "SQL 里没有待确认的占位。"));
    return parts;
  }
  if (!panel.info.pending) {
    parts.push(h("p", { class: "muted" }, "服务没有待确认文件（--pending），这里只能看，不能记入。"));
  } else {
    parts.push(h("p", { class: "muted" },
      "模型没有记这些缺口。要交给目录负责人的，点「记入待确认」（定义可以不填）；不点不记。"));
  }
  parts.push(h("ul", { class: "plain ask-holes" }, holes.map((hole) => h("li", {}, drawHole(hole, vm, panel)))));
  return parts;
}

function drawHole(hole, vm, panel) {
  const where = hole.table && hole.column ? `${hole.table}.${hole.column}` : null;
  const head = h("div", {}, h("span", { class: "badge warn" }, "待确认"), " ", text(hole.text),
    where ? [" — ", code(where)] : h("span", { class: "muted" }, "（不归某一列）"));
  if (!panel.info.pending) return head;
  const input = h("input", { type: "text", maxlength: "2000",
    placeholder: "（可不填）你知道的定义，比如：只算状态为 A 的", "aria-label": `${hole.text} 的定义（可不填）` });
  const button = h("button", { type: "submit" }, "记入待确认");
  const note = h("span", { class: "muted", role: "status" });
  const form = h("form", { class: "ask-fill", onsubmit: async (event) => {
    event.preventDefault();
    button.disabled = true;
    const { status, body } = await postJson("/api/pending", pendingPayload(hole, vm.question, input.value));
    const result = pendingResult(status, body);
    note.textContent = result.text || message(body, status);
    if (result.done) input.disabled = true;
    else button.disabled = false;
  } }, input, button, note);
  return [head, form];
}

function drawEnd(vm) {
  const parts = [h("strong", {}, STATUS_TEXT[vm.status] || vm.status)];
  if (vm.reason && vm.status !== "done") parts.push("：", REASON_TEXT[vm.reason] || vm.reason);
  let detail = null;
  if (vm.detail && typeof vm.detail === "object") {
    detail = [vm.detail.category, vm.detail.explanation].filter(Boolean).join("：");
  } else if (vm.detail && vm.status !== "max_tokens") {
    detail = String(vm.detail);
  }
  return h("div", { class: vm.status === "done" ? "ask-end" : "ask-end error" },
    h("p", {}, parts, detail ? ["（", detail, "）"] : null,
      vm.status === "max_tokens" && vm.detail ? h("span", { class: "ask-note" }, vm.detail) : null),
    vm.usage ? h("p", { class: "muted" }, usageText(vm.usage), ` · ${vm.elapsed} 秒`) : null);
}
