// Small helpers: build DOM nodes from data without ever parsing it as markup, fetch the
// server's JSON, and the Chinese words the command line's text output uses for the
// catalog's enum values. Catalog text is untrusted: it only ever becomes a text node or
// an attribute value set through the DOM.

export const KIND_TEXT = { entity: "实体", event: "事件", role: "角色" };
export const STATUS_TEXT = { drafted: "草拟", confirmed: "已确认", deprecated: "已废弃" };
export const REP_KIND_TEXT = {
  core: "核心", extension: "扩展", dependent: "从属", event_detail: "事件明细",
  state_history: "状态历史", identifier_map: "标识映射", role_view: "角色视图",
  summary: "汇总", intermediate: "中间",
};
export const TIME_TEXT = { snapshot: "快照", incremental: "增量", zipper: "拉链", unknown: "未知" };
export const GRAIN_SOURCE_TEXT = { declared: "声明", inferred: "推断", proven: "已证明" };
export const BINDING_TEXT = {
  attribute: "属性", identifier: "标识符", foreign_identifier: "外部标识符",
  foreign_attribute: "冗余属性", technical: "技术列", unmapped: "未映射",
};
export const RELATION_KIND_TEXT = {
  association: "关联", composition: "组成", generalization: "泛化", derivation: "派生",
  participation: "参与", role: "角色",
};
export const CONSTRAINT_KIND_TEXT = {
  unique: "唯一", cardinality: "基数", mandatory: "必填", value_domain: "值域",
  referential: "引用", temporal: "时间", state_transition: "状态迁移", derivation: "派生",
  business_rule: "业务规则",
};
export const STRENGTH_TEXT = { hard: "硬", soft: "软" };
export const TABLE_STATUS_TEXT = { active: "在用", deprecated: "已废弃" };
export const CATEGORY_TEXT = {
  identifier: "标识", foreign_identifier: "关联标识", descriptive: "描述", state: "状态",
  measure: "度量", time: "时间", technical: "技术",
};
export const QUESTION_STATUS_TEXT = { open: "待确认", answered: "已回答" };

/** The word for an enum value, or the value itself when it has none. */
export function word(map, value) {
  if (value === null || value === undefined || value === "") return "—";
  return Object.prototype.hasOwnProperty.call(map, value) ? map[value] : String(value);
}

/**
 * h("a", {href: "#/x", class: "c"}, "text", child, [more]) -> an element.
 * Children that are strings or numbers become text nodes; null/false are skipped.
 */
export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on") && typeof value === "function") {
      node.addEventListener(name.slice(2), value);
    } else {
      node.setAttribute(name, value === true ? "" : String(value));
    }
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function text(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

const SITE = "本体目录";

/**
 * The document title: the view's heading (or, without one, the view's name) and the site
 * name once -- a heading that already starts with the site name stands alone. While a view
 * loads, "正在加载" leads, so a title never names the view that was left.
 */
export function pageTitle(heading, viewName, loading) {
  const main = String(heading || "").trim() || String(viewName || "").trim();
  if (loading) return main && main !== SITE ? `正在加载：${main} · ${SITE}` : `正在加载 · ${SITE}`;
  if (!main || main === SITE) return SITE;
  return main.startsWith(SITE) ? main : `${main} · ${SITE}`;
}

/** An identifier as code; with ``expression`` true, a code expression that may wrap. */
export function code(value, expression = false) {
  return h("code", { class: expression ? "expr" : null }, text(value));
}

/** A hash link: route parts are encoded, so a name cannot leave its place in the URL. */
export function href(view, id, params) {
  let url = "#/" + view;
  if (id !== undefined && id !== null) url += "/" + encodeURIComponent(id);
  const query = params ? new URLSearchParams(cleanParams(params)).toString() : "";
  return query ? url + "?" + query : url;
}

export function cleanParams(params) {
  const out = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") out[key] = String(value);
  }
  return out;
}

export function link(view, id, label, params) {
  return h("a", { href: href(view, id, params) }, text(label));
}

export function conceptLink(ref) {
  return ref ? link("concept", ref.id, ref.name || ref.id) : "—";
}

export function tableLink(name) {
  return link("table", name, name);
}

export function badge(label, kind) {
  return h("span", { class: kind ? "badge " + kind : "badge" }, label);
}

/** <dl> of [label, value] pairs; a pair whose value is empty is left out. */
export function kv(pairs) {
  const list = h("dl", { class: "kv" });
  for (const [label, value] of pairs) {
    if (value === null || value === undefined || value === "" ||
        (Array.isArray(value) && value.length === 0)) continue;
    list.append(h("dt", {}, label), h("dd", {}, value));
  }
  return list;
}

/** A table of rows; each cell is text or a node. */
export function grid(headers, rows) {
  const head = h("tr", {}, headers.map((name) => h("th", { scope: "col" }, name)));
  const body = rows.map((cells) => h("tr", {}, cells.map((cell) => h("td", {}, cell))));
  return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, body)));
}

export function section(title, ...children) {
  return [h("h2", {}, title), ...children];
}

export function fold(title, open, ...children) {
  return h("details", { open: open || null }, h("summary", {}, title), h("div", { class: "body" }, children));
}

export function joined(items, separator = "、") {
  const out = [];
  items.forEach((item, index) => {
    if (index) out.push(separator);
    out.push(item);
  });
  return out;
}

/** Fetch one endpoint; resolves to {status, body} (body parsed JSON, or null). */
export async function api(path, params) {
  const query = params ? new URLSearchParams(cleanParams(params)).toString() : "";
  const response = await fetch(query ? path + "?" + query : path, {
    headers: { Accept: "application/json" },
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

/** The body of a 200, or of a 404 that is an answer; throws with the server's sentence. */
export async function answer(path, params, { notFoundOk = false } = {}) {
  const { status, body } = await api(path, params);
  if (status === 200 || (notFoundOk && status === 404 && body && !body.error)) return body;
  const message = body && body.error ? body.error.message : `请求失败（HTTP ${status}）`;
  throw new Error(message);
}

/** Previous / next buttons over a page answer ({total, offset, limit}). */
export function pager(page, go) {
  const last = page.offset + page.items.length;
  const box = h("div", { class: "pager" },
    h("span", { class: "muted" },
      page.total ? `第 ${page.offset + 1}–${last} 条，共 ${page.total} 条` : "共 0 条"));
  const prev = h("button", { type: "button", onclick: () => go(Math.max(0, page.offset - page.limit)) }, "上一页");
  const next = h("button", { type: "button", onclick: () => go(page.offset + page.limit) }, "下一页");
  prev.disabled = page.offset <= 0;
  next.disabled = last >= page.total;
  box.prepend(prev);
  box.append(next);
  return box;
}
