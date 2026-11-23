// The ask panel's pure functions: no DOM, no fetch, so node can test them. A run's events
// (what /api/ask/events returns) become one view model; the 待确认 placeholders are read
// from SQL the way check-sql reads them (comments outside strings); the brief the walk
// asks for is split into its labelled lines.

export const STATUS_TEXT = {
  running: "进行中", done: "完成", refused: "模型拒答", max_tokens: "输出被截断",
  cap_reached: "到达上限", cancelled: "已停止", error: "出错",
};
export const REASON_TEXT = {
  turns: "模型轮数到上限", tool_calls: "工具调用次数到上限", output_tokens: "输出 token 到上限",
  seconds: "用时到上限", credentials: "模型提供方拒绝了凭据", not_found: "模型不存在",
  rate_limited: "被限流", bad_request: "请求被拒", api_error: "模型服务出错",
  connection: "连不上模型服务", sdk_error: "SDK 出错", invalid_tool_input: "工具参数不是合法 JSON",
  internal: "服务内部错误", refusal: "模型拒答", max_tokens: "单轮输出被截断",
};
export const SEVERITY_TEXT = { error: "错误", warning: "警告", info: "提示" };
export const TOOL_TEXT = {
  search_catalog: "检索", query_catalog: "查询", catalog_context: "取数包",
  check_sql: "SQL 检查", add_pending: "记入待确认",
};

const BRIEF_KEYS = ["问题", "结论", "SQL", "表", "关联", "条件", "假设", "待确认", "check-sql"];
const BRIEF_LINE = new RegExp(`^(${BRIEF_KEYS.join("|")})[：:](.*)$`);

/**
 * The 待确认 placeholders in SQL: block or line comments, outside quoted text, whose body
 * starts with 待确认 and a colon (full or half width). [{text, offset}], in order.
 */
export function extractPlaceholders(sql) {
  const found = [];
  const source = String(sql || "");
  const n = source.length;
  const take = (body, offset) => {
    const match = /^\s*待确认\s*[：:]\s*([\s\S]*?)\s*$/.exec(body);
    if (match) found.push({ text: match[1], offset });
  };
  let i = 0;
  while (i < n) {
    const c = source[i];
    const next = source[i + 1];
    if (c === "'" || c === '"' || c === "`") {
      i += 1;
      while (i < n) {
        if (source[i] === "\\" && c !== "`") { i += 2; continue; }
        if (source[i] === c) {
          if (source[i + 1] === c) { i += 2; continue; }
          i += 1;
          break;
        }
        i += 1;
      }
    } else if (c === "-" && next === "-") {
      const end = source.indexOf("\n", i);
      take(source.slice(i + 2, end < 0 ? n : end), i);
      i = end < 0 ? n : end + 1;
    } else if (c === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);
      take(source.slice(i + 2, end < 0 ? n : end), i);
      i = end < 0 ? n : end + 2;
    } else {
      i += 1;
    }
  }
  return found;
}

function splitBasis(value) {
  const at = value.indexOf(" — ");
  return at < 0 ? { text: value.trim(), basis: "" }
    : { text: value.slice(0, at).trim(), basis: value.slice(at + 3).trim() };
}

function present(value) {
  const trimmed = String(value || "").trim();
  return trimmed && trimmed !== "无" ? trimmed : null;
}

/** The brief's labelled lines; a line without a label continues the one before it. */
export function parseBrief(brief) {
  const fields = [];
  for (const line of String(brief || "").split(/\r?\n/)) {
    const match = BRIEF_LINE.exec(line.trim());
    if (match) fields.push([match[1], match[2].trim()]);
    else if (fields.length) fields[fields.length - 1][1] += "\n" + line;
  }
  const all = (key) => fields.filter(([name]) => name === key).map(([, value]) => value.trim());
  const one = (key) => { const values = all(key); return values.length ? values[0] : null; };
  return {
    question: one("问题"),
    conclusion: present(one("结论")),
    sql: present(one("SQL")),
    // "表：<库.表> — 一行是 <粒度>": the grain without its lead-in
    tables: all("表").filter(present).map(splitBasis)
      .map((item) => ({ text: item.text, basis: item.basis.replace(/^一行是\s*/, "") })),
    joins: all("关联").filter(present),
    conditions: all("条件").filter(present).map(splitBasis),
    assumptions: all("假设").filter(present),
    pending: all("待确认").filter(present),
    checkSql: present(one("check-sql")),
  };
}

/** "输入 1200 · 缓存读 5000 · …" for a usage total (null: nothing yet). */
export function usageText(usage) {
  if (!usage) return "";
  const n = (value) => Number(value || 0).toLocaleString("en-US");
  const parts = [
    `输入 ${n(usage.input_tokens)}`, `缓存读 ${n(usage.cache_read_input_tokens)}`,
    `缓存写 ${n(usage.cache_creation_input_tokens)}`, `输出 ${n(usage.output_tokens)}`,
  ];
  if (usage.turns !== undefined) parts.push(`${usage.turns} 轮`);
  if (usage.tool_calls !== undefined) parts.push(`${usage.tool_calls} 次工具调用`);
  return parts.join(" · ");
}

/**
 * One run's events -> what the panel draws: the question, the steps in order (model notes,
 * tool calls with their results, fallbacks), what the searches found, what the context
 * packs took, each check-sql round, the answer with its placeholders and parsed brief,
 * and the end (status, reason, usage).
 */
export function viewModel(events) {
  const vm = {
    question: null, followUp: false, model: null, status: "running", reason: null,
    detail: null, usage: null, elapsed: 0, steps: [], answer: null,
    candidates: [], taken: { tables: [], columns: [] }, checks: [],
  };
  const calls = new Map();
  for (const event of events || []) {
    vm.elapsed = Math.max(vm.elapsed, Number(event.t || 0));
    if (event.type === "started") {
      vm.question = event.question;
      vm.followUp = Boolean(event.follow_up);
      vm.model = event.model || null;
    } else if (event.type === "turn") {
      if (String(event.text || "").trim()) vm.steps.push({ kind: "note", text: event.text, turn: event.turn });
    } else if (event.type === "fallback") {
      vm.steps.push({ kind: "fallback", from: event.from, to: event.to });
    } else if (event.type === "retry") {
      vm.steps.push({ kind: "retry", reason: event.reason });
    } else if (event.type === "tool_call") {
      const step = { kind: "tool", id: event.id, name: event.name, input: event.input || {}, done: false };
      if (event.name === "check_sql") step.round = vm.checks.length + 1;
      if (event.name === "check_sql") vm.checks.push(step);
      vm.steps.push(step);
      calls.set(event.id, step);
    } else if (event.type === "tool_result") {
      const step = calls.get(event.id);
      if (!step) continue;
      Object.assign(step, { done: true, ok: Boolean(event.ok), error: event.error || null,
        exitCode: event.exit_code, data: event.data || {} });
      if (step.ok && step.name === "search_catalog") vm.candidates.push(...(step.data.hits || []));
      if (step.ok && step.name === "catalog_context") {
        for (const name of step.data.tables || []) if (!vm.taken.tables.includes(name)) vm.taken.tables.push(name);
        for (const name of step.data.columns || []) if (!vm.taken.columns.includes(name)) vm.taken.columns.push(name);
      }
    } else if (event.type === "answer") {
      const last = vm.steps[vm.steps.length - 1];
      if (last && last.kind === "note" && last.text === event.text) vm.steps.pop();
      const fromServer = !event.placeholder_check_error && Array.isArray(event.placeholders);
      vm.answer = {
        text: event.text || "", sql: event.sql || null, brief: event.brief || "",
        briefMissing: Boolean(event.brief_missing),
        placeholders: fromServer ? event.placeholders
          : extractPlaceholders(event.sql).map((p) => ({ text: p.text, table: null, column: null })),
        parsed: parseBrief(event.brief),
      };
    } else if (event.type === "finished") {
      vm.status = event.status;
      vm.reason = event.reason || null;
      vm.detail = event.detail === undefined ? null : event.detail;
      vm.usage = event.usage || null;
    }
  }
  return vm;
}
