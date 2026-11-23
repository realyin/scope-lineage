// The browse views. Each takes the route's id and parameters, fetches the answers it
// shows and returns the nodes to put in <main>. Every catalog string goes in as text.

import {
  BINDING_TEXT, CATEGORY_TEXT, CONSTRAINT_KIND_TEXT, GRAIN_SOURCE_TEXT, KIND_TEXT,
  QUESTION_STATUS_TEXT, RELATION_KIND_TEXT, REP_KIND_TEXT, STATUS_TEXT, STRENGTH_TEXT,
  TABLE_STATUS_TEXT, TIME_TEXT,
  answer, api, badge, code, conceptLink, fold, grid, h, href, joined, kv, link, pager,
  section, tableLink, text, word,
} from "./dom.js";
import { EDGE_LABELS_UP_TO, drawGraph, relationTitle } from "./graph.js";

const PAGE = 50;

function crumbs(...parts) {
  const shown = parts.filter((part) => part !== null && part !== undefined && part !== "");
  return h("div", { class: "crumbs" }, joined([link("", null, "目录"), ...shown], " › "));
}

function go(view, id, params) {
  window.location.hash = href(view, id, params).slice(1);
}

function offsetOf(params, name = "offset") {
  const value = Number.parseInt(params.get(name) || "0", 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function statusBadge(status) {
  if (!status) return null;
  return badge(word(STATUS_TEXT, status), status === "confirmed" ? "ok" : null);
}

function list(items, render) {
  if (!items || items.length === 0) return h("p", { class: "muted" }, "（无）");
  return h("ul", { class: "plain" }, items.map((item) => h("li", {}, render(item))));
}

// ------------------------------------------------------------------ home

export async function home() {
  const index = await answer("/api/browse");
  const counts = index.counts || {};
  const summary = [
    ["概念", counts.concepts], ["属性", counts.attributes], ["关系", counts.relations],
    ["表现表", counts.representations], ["指标", counts.metrics], ["码值集", counts.code_sets],
  ].filter(([, n]) => n !== undefined).map(([label, n]) => `${n} 个${label}`);
  const cards = index.domains.map((domain) => h("div", { class: "card" },
    h("h3", {}, link("domain", domain.id, domain.name)),
    domain.description ? h("p", { class: "muted" }, domain.description) : null,
    h("div", {}, `${domain.concepts} 个概念 · `,
      link("tables", null, `${domain.tables} 张表`, { domain: domain.id }),
      domain.metrics ? [" · ", link("metrics", null, `${domain.metrics} 个指标`, { domain: domain.id })] : null)));
  return [
    h("h1", {}, `本体目录：${text(index.catalog.name)}`),
    index.catalog.description ? h("p", {}, index.catalog.description) : null,
    h("p", { class: "muted" }, summary.join(" · ")),
    ...useFirst(index.use_first),
    ...section("业务域", index.domains.length ? h("div", { class: "cards" }, cards)
      : h("p", { class: "muted" }, "目录里没有业务域。")),
  ];
}

/** The summary catalog render puts first in index.md, as the server counted it. */
function useFirst(block) {
  if (!block) return [];
  const rows = block.rows.map((row) => h("tr", {}, h("td", {}, row.name), h("td", { class: "num" }, row.value)));
  return section(block.heading,
    block.notes.map((note) => h("p", {}, note)),
    h("div", { class: "table-wrap" }, h("table", { class: "summary-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "缺口"), h("th", { scope: "col" }, "数量"))),
      h("tbody", {}, rows))),
    h("p", { class: "muted" }, "逐张表看见", link("tables", null, "表清单"), "。"));
}

// ------------------------------------------------------------------ domain

export async function domain(id, params) {
  const offset = offsetOf(params);
  const [index, page] = await Promise.all([
    answer("/api/browse"),
    answer("/api/list", { kind: "concepts", domain: id, offset, limit: PAGE }),
  ]);
  const found = index.domains.find((item) => item.id === id);
  if (!found) return [crumbs(), h("p", { class: "error" }, `目录里没有业务域 ${id}`)];
  const rows = page.items.map((concept) => [
    link("concept", concept.id, concept.name), word(KIND_TEXT, concept.kind),
    text(concept.definition), String(concept.tables), word(STATUS_TEXT, concept.status),
  ]);
  return [
    crumbs(found.name),
    h("h1", {}, found.name, badge(id)),
    found.description ? h("p", {}, found.description) : null,
    h("p", {}, link("tables", null, `本域的 ${found.tables} 张表`, { domain: id }),
      found.metrics ? [" · ", link("metrics", null, `${found.metrics} 个指标`, { domain: id })] : null),
    ...section("概念", grid(["概念", "种类", "定义", "表现表", "状态"], rows),
      pager(page, (next) => go("domain", id, { offset: next }))),
  ];
}

// ------------------------------------------------------------------ concept

export async function concept(id, params) {
  const offset = offsetOf(params);
  const [query, graph, tables, metrics] = await Promise.all([
    answer("/api/query", { kind: "concept", term: id }, { notFoundOk: true }),
    answer("/api/neighbourhood", { concept: id }, { notFoundOk: true }),
    answer("/api/list", { kind: "tables", concept: id, offset, limit: PAGE }),
    answer("/api/list", { kind: "metrics", concept: id, limit: 200 }),
  ]);
  const match = query.matches.find((item) => item.id === id) || query.matches[0];
  if (!match) return [crumbs(), h("p", { class: "error" }, `目录里没有概念 ${id}`)];
  const overview = match.overview || {};
  const identified = (overview.identified_by || []).map((item) =>
    `${item.name}${item.primary ? "（主）" : ""}：${item.scope}，${item.arises}`);
  // as catalog query prints them: the concept, then the role name the catalog gives it
  const participants = (overview.participants || []).map((p) => `${p.concept}（${p.role_name}）`);
  const tableRows = tables.items.map((rep) => [
    tableLink(rep.table), word(REP_KIND_TEXT, rep.kind), word(TIME_TEXT, rep.time),
    String(rep.columns), text(rep.about),
    [word(STATUS_TEXT, rep.status), rep.table_status === "deprecated" ? badge("已废弃", "warn") : null],
  ]);
  const attributeRows = (match.attributes || []).map((a) => [a.name, code(a.id), word(CATEGORY_TEXT, a.category)]);
  return [
    crumbs(link("domain", match.domain.id, match.domain.name), match.name),
    h("h1", {}, match.name, badge(word(KIND_TEXT, match.kind)), statusBadge(match.status)),
    h("p", { class: "muted" }, code(match.id)),
    ...section("一页纸", kv([
      ["是什么", overview.what || match.definition || "（目录未写定义）"],
      ["所属域", link("domain", match.domain.id, match.domain.name)],
      ["同义词", (match.synonyms || []).join("、")],
      ["怎么认出来", identified.length ? list(identified, (line) => line) : null],
      ["状态流转", overview.states],
      ["承担者", overview.player],
      ["成立条件", overview.condition],
      ["参与者", participants.join("；")],
      ["发生时间", overview.occurred_at],
      ["草拟占比", overview.drafted_percent !== undefined ? `${overview.drafted_percent}%` : null],
    ])),
    ...section("关系图", graphBlock(graph)),
    ...section(`表（${tables.total} 张）`,
      tables.total ? grid(["表", "种类", "时间形态", "绑定列", "说明", "状态"], tableRows)
        : h("p", { class: "muted" }, "这个概念没有表现表。"),
      tables.total > tables.limit ? pager(tables, (next) => go("concept", id, { offset: next })) : null),
    ...section("指标", list(metrics.items, (m) => [link("metric", m.id, m.name), " ",
      h("span", { class: "muted" }, text(m.definition))])),
    ...section("属性", attributeRows.length ? grid(["属性", "id", "类别"], attributeRows)
      : h("p", { class: "muted" }, "（无）")),
    ...section("标识符", list(match.identifiers, (i) => [i.name, i.primary ? badge("主") : null, " ", code(i.id)])),
    match.states && match.states.length ? section("状态", h("p", {}, match.states.join("、"))) : null,
    h("p", {}, link("questions", null, "这个概念的待确认问题", { concept: match.id })),
  ];
}

function graphBlock(graph) {
  if (!graph || !graph.centre) return h("p", { class: "muted" }, "（没有关系）");
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]));
  const rows = graph.edges.map((edge) => [
    edge.id ? code(edge.id) : "—",
    word(RELATION_KIND_TEXT, edge.kind),
    edge.kind === "role" || edge.kind === "participation"
      ? relationTitle(edge, names)
      : `${names.get(edge.from)} ${edge.name} ${names.get(edge.to)}` +
        (edge.inverse_name ? ` / ${names.get(edge.to)} ${edge.inverse_name} ${names.get(edge.from)}` : ""),
    edge.cardinality ? `${edge.cardinality.from} : ${edge.cardinality.to}` : "—",
    joinsCell(edge),
    keysCell(edge),
  ]);
  return [
    h("div", { class: "graph-box" }, drawGraph(graph)),
    graph.nodes.length > EDGE_LABELS_UP_TO
      ? h("p", { class: "muted" }, `图上概念多于 ${EDGE_LABELS_UP_TO} 个，线上不写关系名；每条关系见下表。`) : null,
    graph.truncated ? h("p", { class: "muted" }, `另有 ${graph.truncated} 个相邻概念没画出来。`) : null,
    graph.edges.length ? grid(["关系", "种类", "读法", "基数", "语料中的连接", "外键列"], rows) : null,
  ];
}

function joinsCell(edge) {
  const parts = [];
  if (edge.joins) {
    parts.push(h("div", {}, `目录表之间 ${edge.joins.count} 次`));
    for (const on of edge.joins.on) parts.push(h("div", {}, code(on, true)));
  }
  if (edge.source_joins && edge.source_joins.count) {
    parts.push(h("div", {}, `生产任务内 ${edge.source_joins.count} 次`));
    for (const on of edge.source_joins.on) parts.push(h("div", {}, code(on, true)));
  }
  return parts.length ? parts : "—";
}

function keysCell(edge) {
  if (!edge.keys || edge.keys.length === 0) return "—";
  const parts = edge.keys.map((key) => h("div", {}, code(key.column), " → ",
    key.to.length ? joined(key.to.map((target) => code(target))) : "（没有以它为主键的表）",
    key.to_total > key.to.length ? ` 等 ${key.to_total} 列` : ""));
  if (edge.keys_total > edge.keys.length) parts.push(h("div", { class: "muted" }, `共 ${edge.keys_total} 列`));
  return parts;
}

// ------------------------------------------------------------------ metric

export async function metric(id) {
  const pack = await answer("/api/context", { concept: id }, { notFoundOk: true });
  const owner = pack.concepts.find((item) => item.via_metric && item.via_metric.id === id) || pack.concepts[0];
  const found = owner && owner.metrics.find((item) => item.id === id);
  if (!found) return [crumbs(), h("p", { class: "error" }, `目录里没有指标 ${id}`)];
  const measure = found.measure;
  return [
    crumbs(conceptLink(owner), found.name),
    h("h1", {}, found.name, badge("指标"), statusBadge(found.status)),
    h("p", { class: "muted" }, code(found.id)),
    kv([
      ["定义", found.definition],
      ["概念", conceptLink(owner)],
      ["度量", measure ? [measure.name, " ", code(measure.id), measure.columns.length
        ? h("div", {}, joined(measure.columns.map((column) => columnLink(column)))) : " （没有绑定的列）"] : null],
      ["聚合", found.aggregation],
      ["过滤", found.filter],
      ["时间窗", found.time_window],
      ["可加性", found.additivity],
      ["单位", found.unit],
      ["维度", found.dimensions.length ? joined(found.dimensions.map((d) => d.name)) : null],
      ["约束", found.constraints.length ? list(found.constraints, (c) => [code(c.id), " ", text(c.expression)]) : null],
    ]),
  ];
}

function columnLink(column) {
  const table = column.split(".").slice(0, -1).join(".");
  return h("a", { href: href("table", table) }, code(column));
}

// ------------------------------------------------------------------ table

export async function table(name) {
  const [query, pack, semantics, units] = await Promise.all([
    answer("/api/query", { kind: "table", term: name }, { notFoundOk: true }),
    answer("/api/context", { table: name, brief: "true" }, { notFoundOk: true }),
    answer("/api/semantics", { table: name }, { notFoundOk: true }),
    answer("/api/units", { table: name }, { notFoundOk: true }),
  ]);
  const match = query.matches[0];
  const entry = pack.tables[0];
  const doc = semantics.document;
  const title = (match && match.table) || semantics.table || name;
  const out = [
    crumbs(match && match.concept ? conceptLink(match.concept) : null, title),
    h("h1", {}, title,
      match && match.kind ? badge(word(REP_KIND_TEXT, match.kind)) : null,
      match && match.time ? badge(word(TIME_TEXT, match.time)) : null,
      match && match.table_status === "deprecated" ? badge("已废弃", "warn") : null,
      match ? statusBadge(match.status) : null),
  ];
  if (!match && !doc) return [...out, h("p", { class: "error" }, `目录和表语义里都没有表 ${name}`)];
  if (!match) out.push(h("p", { class: "muted" }, "目录里没有这张表；下面只有它的表语义。"));
  if (match && !entry) out.push(h("p", { class: "muted" }, "这张表是码值表：它存放码值，不承载概念。"));
  if (match) out.push(...catalogPart(match, entry, units));
  out.push(...section("表语义", doc ? semanticsDocument(doc)
    : h("p", { class: "muted" }, "这张表没有表语义文档：怎么读、注意事项和待确认问题都没有人写下来。")));
  out.push(h("p", {}, link("questions", null, "这张表的待确认问题", { table: title, status: "all" })));
  return out;
}

function catalogPart(match, entry, units) {
  const out = [];
  const grain = entry ? entry.grain : null;
  out.push(...section("目录", kv([
    ["承载概念", match.concept ? conceptLink(match.concept) : null],
    ["表的种类", match.kind ? word(REP_KIND_TEXT, match.kind) : null],
    ["粒度", grain && grain.columns.length
      ? `${grain.columns.join("、")}（${word(GRAIN_SOURCE_TEXT, grain.source)}）` : (entry ? "未声明" : null)],
    ["时间形态", match.time ? word(TIME_TEXT, match.time) : null],
    ["刷新", match.refresh],
    ["时间列", entry && entry.time_columns.length
      ? entry.time_columns.map((c) => `${c.column}（${c.role}）`).join("、") : null],
    ["分区", entry && entry.partition ? partitionText(entry.partition) : null],
    ["取数提示", match.usage],
    ["记录范围", match.scope && match.scope.length ? list(match.scope, (line) => line) : null],
    ["表状态", match.table_status ? word(TABLE_STATUS_TEXT, match.table_status) : null],
    ["替代表", match.replaced_by ? tableLink(match.replaced_by) : null],
    ["备注", match.notes],
    ["证据与目录矛盾", entry && entry.conflicts ? list(entry.conflicts, (c) => c.text) : null],
  ])));
  if (match.columns) {
    out.push(...section(`绑定列（${match.columns.length}）`, columnsGrid(match, units)));
  }
  if (entry) {
    out.push(...section("关联", entry.joins.length ? grid(["关联列", "标识", "指向", "可关联到", "语料中见过"],
      entry.joins.map((join) => [
        code(join.column), join.identifier.name, join.concept ? conceptLink(join.concept) : "—",
        join.to.length ? joined(join.to.map((t) => h("a", { href: href("table", t.table) }, code(`${t.table}.${t.column}`))))
          : "目录里没有以这个标识为主键的表",
        join.seen.length ? join.seen.map((s) => h("div", {},
          `${s.where === "inside_producing_task" ? "产出任务内部" : "目录表之间"} ${s.count} 次：`,
          joined(s.on.map((on) => code(on, true)), "；"))) : "—",
      ])) : h("p", { class: "muted" }, "（没有外键列）")));
  }
  // the concept's constraints (catalog context), then the rules citing this table that are
  // not among them (catalog query table)
  const constraints = [...(entry ? entry.constraints : [])];
  for (const rule of match.constraints || []) {
    if (!constraints.some((c) => c.id === rule.id)) constraints.push(rule);
  }
  out.push(...section("约束", constraints.length ? grid(["约束", "种类", "针对", "表达式", "强度"],
    constraints.map((c) => [code(c.id), word(CONSTRAINT_KIND_TEXT, c.kind),
      c.on && typeof c.on === "object" ? c.on.name : text(c.on), text(c.expression),
      c.strength ? word(STRENGTH_TEXT, c.strength) : "—"])) : h("p", { class: "muted" }, "（无）")));
  if (entry) {
    out.push(...section("这个概念上的指标", list(entry.metrics, (m) => link("metric", m.id, m.name))));
  }
  if (match.code_sets && match.code_sets.length) {
    out.push(...section("码值来源", list(match.code_sets, (s) => [s.name, " ", code(s.id)])));
  }
  return out;
}

function partitionText(item) {
  const columns = item.columns.join("、");
  if (item.reading === "full_copy") return `${columns}：每个分区一份全量，只取一个分区（跨分区相加会重复计数）`;
  if (item.reading === "write_batch") {
    const how = item.period_columns.length ? `按事件时间列 ${item.period_columns.join("、")} 过滤时段`
      : "时段按「取数」写明的日期列过滤";
    return `${columns}：写入批次，不是事件日期，${how}`;
  }
  return `${columns}：目录没记录每个分区是不是一份全量，按「取数」读`;
}

const GRID_COLUMNS = ["列", "绑定", "指向", "血缘", ""];

/** The code values a bound column carries, as text: its own map, then each code set. */
export function codeTexts(column) {
  const parts = [];
  if (column.code_map) parts.push(Object.entries(column.code_map).map(([k, v]) => `${k}=${v}`).join("、"));
  for (const set of column.code_sets || []) {
    parts.push(`${set.name}（${set.id}）` +
      (set.keys ? `：${set.keys.map((k) => `${k.key}→${k.value}=${k.meaning}`).join("、")}` : ""));
  }
  return parts;
}

/** Everything the filter box looks in for one bound column, folded to lower case. */
export function columnHaystack(column, unit) {
  return [
    column.column, word(BINDING_TEXT, column.to), column.to, column.ref_name, column.ref,
    column.concept ? column.concept.name : null, column.concept ? column.concept.id : null,
    column.via, column.derivation, ...codeTexts(column), unit ? unit.text : null,
  ].filter((part) => part !== null && part !== undefined && part !== "").join("\n").toLowerCase();
}

/** The positions of the columns a filter keeps: ``needle`` found in a column's words (case
 * ignored; blank keeps all) and, when ``binding`` is given, bound that way. */
export function filterColumns(columns, needle, binding, units) {
  const wanted = String(needle || "").trim().toLowerCase();
  const kept = [];
  columns.forEach((column, index) => {
    if (binding && column.to !== binding) return;
    if (wanted && !columnHaystack(column, units ? units.get(column.column) : null).includes(wanted)) return;
    kept.push(index);
  });
  return kept;
}

/** How many columns each binding kind has, in the order they first appear. */
export function bindingCounts(columns) {
  const counts = new Map();
  for (const column of columns) counts.set(column.to, (counts.get(column.to) || 0) + 1);
  return [...counts.entries()];
}

function columnsGrid(match, unitAnswer) {
  const units = new Map(((unitAnswer && unitAnswer.columns) || []).map((u) => [u.column, u]));
  const body = h("tbody", {});
  const rows = match.columns.map((column) => {
    const unit = units.get(column.column);
    const target = [column.ref_name ? [column.ref_name, " ", code(column.ref)] : null,
      column.concept ? [" · ", conceptLink(column.concept)] : null,
      column.via ? ` · 经由 ${column.via}` : null,
      column.self_reference ? " · 自关联" : null,
      unit && unit.text ? h("span", { class: "unit" }, `单位：${unit.text}`) : null];
    const more = h("button", { type: "button" }, "详情");
    const row = h("tr", {},
      h("td", {}, code(column.column)), h("td", {}, word(BINDING_TEXT, column.to)),
      h("td", {}, column.ref_name || column.concept || column.via || (unit && unit.text) ? target : "—"),
      h("td", {}, column.evidence && column.evidence.expression ? code(column.evidence.expression, true) : "—"),
      h("td", {}, more));
    // code values and 口径 only on the columns that have them, on a line under the column
    const extra = [];
    const codes = codeTexts(column);
    if (codes.length) extra.push(h("div", {}, "码值：", joined(codes, "；")));
    if (column.derivation) extra.push(h("div", {}, "口径：", column.derivation));
    const extraRow = extra.length
      ? h("tr", { class: "column-extra" }, h("td", {}), h("td", { colspan: String(GRID_COLUMNS.length - 1) }, extra))
      : null;
    if (extraRow) row.classList.add("has-extra");
    more.addEventListener("click", () => toggleColumn(extraRow || row, more, `${match.table}.${column.column}`, unit));
    body.append(row);
    if (extraRow) body.append(extraRow);
    return { row, extraRow };
  });
  const head = h("tr", {}, GRID_COLUMNS.map((n) => h("th", { scope: "col" }, n)));
  const table = h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, head), body));
  if (match.columns.length <= 12) return table;
  // a wide table: a filter over the columns
  const search = h("input", { type: "search", placeholder: "列名、指向的属性、码值、口径、单位", "aria-label": "筛选列" });
  const kinds = h("select", { "aria-label": "按绑定筛选" },
    h("option", { value: "" }, `全部绑定（${match.columns.length}）`),
    bindingCounts(match.columns).map(([kind, count]) => h("option", { value: kind }, `${word(BINDING_TEXT, kind)}（${count}）`)));
  const shown = h("span", { class: "muted" });
  const apply = () => {
    const kept = new Set(filterColumns(match.columns, search.value, kinds.value, units));
    rows.forEach(({ row, extraRow }, index) => {
      const hide = !kept.has(index);
      row.hidden = hide;
      if (extraRow) extraRow.hidden = hide;
      const detail = (extraRow || row).nextElementSibling;
      if (detail && detail.classList.contains("column-detail")) detail.hidden = hide;
    });
    shown.textContent = `显示 ${kept.size} / ${match.columns.length} 列`;
  };
  search.addEventListener("input", apply);
  kinds.addEventListener("change", apply);
  apply();
  return [h("div", { class: "column-filter" }, h("label", {}, "筛选列 ", search), kinds, shown), table];
}

/** One column in full (catalog context --column), in a row under the column's row. */
async function toggleColumn(row, button, address, unit) {
  const next = row.nextElementSibling;
  if (next && next.classList.contains("column-detail")) {
    next.remove();
    button.textContent = "详情";
    return;
  }
  button.disabled = true;
  const cell = h("td", { colspan: String(GRID_COLUMNS.length) }, h("span", { class: "muted" }, "正在加载……"));
  row.after(h("tr", { class: "column-detail" }, cell));
  try {
    const pack = await answer("/api/context", { column: address }, { notFoundOk: true });
    const column = pack.columns[0];
    cell.replaceChildren(column ? columnDetail(column, unit) : h("span", { class: "muted" }, "没有更多信息。"));
    button.textContent = "收起";
  } catch (error) {
    cell.replaceChildren(h("span", { class: "error" }, error.message));
  } finally {
    button.disabled = false;
  }
}

function columnDetail(column, unit) {
  const catalog = column.catalog || {};
  const sem = column.semantics || {};
  const values = (catalog.code_sets || []).map((set) => h("div", {}, code(set.code_set), "：",
    set.values.map((v) => `${v.value}=${v.meaning || "含义待确认"}${v.unconfirmed ? "（待确认）" : ""}`).join("、")));
  return kv([
    ["目录定义", catalog.definition],
    // the words the context pack prints, with its mark when the material does not give it
    ["单位", unit && unit.text ? unit.text : catalog.unit],
    ["目录码值", values.length ? values : null],
    ["时间角色", catalog.time_role],
    ["表语义含义", sem.meaning],
    ["类别", sem.category ? word(CATEGORY_TEXT, sem.category) : null],
    ["口径", sem.derivation],
    ["表语义码值", sem.code_values ? sem.code_values.map((v) => `${v.value}=${text(v.meaning)}`).join("、") : null],
    ["为空", sem.null_meaning],
    ["要注意", column.watch.length ? list(column.watch, (w) => w.text) : null],
    ["待确认问题", column.questions.length ? list(column.questions, (q) =>
      [`${q.id} `, badge(word(QUESTION_STATUS_TEXT, q.status)), " ", text(q.text)]) : null],
  ]);
}

// ---------------------------------------------------------- table semantics

const SUMMARY_LABELS = [
  ["what", "这张表是什么"], ["row", "一行是什么"], ["refresh", "更新与取数"], ["scope", "收哪些数据"],
  ["good_for", "适合用来"], ["not_for", "不适合"], ["watch", "要注意"], ["questions", "待确认问题"],
  ["upstream", "数据从哪来"], ["downstream", "谁在用"],
];
const VALUE_LABELS = {
  text: "说明", grain_columns: "粒度列", grain_source: "粒度来源", unique: "唯一", note: "备注",
  cycle: "周期", time: "时间形态", how_to_read: "取数", watch: "注意", rule_refs: "规则",
  kind: "种类", refs: "涉及", id: "编号", about: "涉及", status: "状态", table: "表", task: "任务",
  role: "作用", column: "字段", meaning: "含义", category: "类别", derivation: "口径",
  branches: "分支", code_values: "码值", null_meaning: "为空", sql: "SQL", name: "名称",
  purpose: "用途", sources: "来源", confidence: "置信", value: "值", branch: "分支",
};

// enum values of a table-semantics document, in the words its rendered page uses
const ENUM_WORDS = {
  grain_source: GRAIN_SOURCE_TEXT,
  unique: { yes: "全表唯一", no: "不能保证唯一", unknown: "是否唯一未知" },
  time: TIME_TEXT,
  cycle: { daily: "每天", hourly: "每小时", weekly: "每周", monthly: "每月" },
  sources: {
    comment: "注释", sql: "SQL", sql_comment: "SQL 注释", metadata: "元数据", task: "任务",
    inferred: "推断", confirmed: "确认",
  },
  confidence: { high: "高置信", medium: "中置信", low: "低置信" },
  kind: { conflict: "矛盾", risk: "风险", deprecated: "已废弃", coverage: "覆盖", other: "其他" },
  role: {
    main: "主表", enrich: "补充字段", filter: "过滤", dedup: "去重", union_branch: "合并分支",
    lookup: "查码", other: "其他",
  },
  category: CATEGORY_TEXT,
  status: QUESTION_STATUS_TEXT,
};
const RULE_KIND_TEXT = { filter: "过滤", join: "关联", dedup: "去重", derive: "派生", union: "合并", other: "其他" };

function semanticsDocument(doc) {
  const summary = doc.summary || {};
  const parts = [];
  parts.push(fold("一页纸", true, ...SUMMARY_LABELS.filter(([key]) => key in summary)
    .map(([key, label]) => fold(`${label}${countOf(summary[key])}`, key === "what" || key === "row" ||
      key === "questions", summaryValue(key, summary[key]))),
  ...Object.keys(summary).filter((key) => !SUMMARY_LABELS.some(([k]) => k === key))
    .map((key) => fold(key, false, value(summary[key])))));
  if (doc.columns) parts.push(fold(`字段（${doc.columns.length}）`, false, semanticsColumns(doc.columns)));
  const process = [];
  for (const task of doc.tasks || (doc.task ? [doc.task] : [])) process.push(h("div", {}, "产出任务：", value(task)));
  if (doc.steps && doc.steps.length) process.push(h("ol", {}, doc.steps.map((step) => h("li", {}, text(step)))));
  if (process.length) parts.push(fold("加工过程", false, process));
  if (doc.rules) {
    parts.push(fold(`规则（原文）（${doc.rules.length}）`, false, doc.rules.length
      ? doc.rules.map((rule) => h("div", {}, h("h3", {}, `${rule.id} ${rule.kind ? word(RULE_KIND_TEXT, rule.kind) : ""}`), h("p", {}, text(rule.text)),
        rule.sql ? h("pre", {}, rule.sql) : null))
      : h("p", { class: "muted" }, "（无）")));
  }
  const known = new Set(["summary", "columns", "rules", "steps", "task", "tasks", "table", "doc_format"]);
  const rest = Object.keys(doc).filter((key) => !known.has(key));
  if (rest.length) parts.push(fold("来源说明", false, kv(rest.map((key) => [key, value(doc[key])]))));
  return parts;
}

function countOf(item) {
  return Array.isArray(item) ? `（${item.length}）` : "";
}

function summaryValue(key, item) {
  if (key === "questions" && Array.isArray(item)) {
    return list(item, (q) => [`${q.id || ""} `, badge(word(QUESTION_STATUS_TEXT, q.status), q.status === "open" ? "warn" : null),
      " ", text(q.text), q.about && q.about.length ? h("span", { class: "muted" }, `（${q.about.join("、")}）`) : null]);
  }
  if (key === "upstream" || key === "downstream") {
    return list(item, (u) => [u.table ? tableLink(u.table) : null, u.task ? [" ", h("span", { class: "muted" }, `任务 ${u.task}`)] : null,
      u.role ? ` · ${word(ENUM_WORDS.role, u.role)}` : null, u.text ? ` · ${u.text}` : null]);
  }
  return value(item);
}

function semanticsColumns(columns) {
  return grid(["字段", "含义", "类别", "码值", "口径", "为空"], columns.map((c) => [
    code(c.column), text(c.meaning), word(CATEGORY_TEXT, c.category),
    c.code_values && c.code_values.length ? c.code_values.map((v) => `${v.value}=${text(v.meaning)}`).join("、") : "—",
    text(c.derivation), text(c.null_meaning),
  ]));
}

/** Any JSON value as text, lists and key/value pairs; nothing is markup. ``key`` names
 * the field the value is in, for its enum words. */
function value(item, key) {
  const words = key && ENUM_WORDS[key];
  if (item === null || item === undefined || item === "") return "—";
  if (Array.isArray(item)) {
    if (item.every((x) => typeof x !== "object" || x === null)) {
      return item.map((x) => (words ? word(words, x) : String(x))).join("、") || "（无）";
    }
    return list(item, (x) => value(x));
  }
  if (typeof item === "object") {
    return kv(Object.entries(item).map(([name, inner]) => [VALUE_LABELS[name] || name, value(inner, name)]));
  }
  return words ? word(words, item) : String(item);
}

// ------------------------------------------------------------------ lists

function filterForm(fields, onSubmit) {
  const form = h("form", { class: "filters" }, fields, h("button", { type: "submit" }, "筛选"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onSubmit(Object.fromEntries(new FormData(form).entries()));
  });
  return form;
}

function input(name, label, value, placeholder) {
  return h("label", {}, label, h("input", { name, value: value || "", placeholder: placeholder || "", type: "text" }));
}

// The orders the table list offers: by name, or by one by-table number (the server sorts
// the whole filtered list; a table without a table-semantics document comes last).
// Never a sum of several: there is no score.
export const TABLE_SORT_CHOICES = [
  ["", "表名"], ["-table", "表名（倒序）"],
  ["-measures", "度量列，多的在前"], ["measures", "度量列，少的在前"],
  ["-unit_unsupported", "单位无材料依据的列，多的在前"], ["unit_unsupported", "单位无材料依据的列，少的在前"],
  ["-unmapped", "未绑定列，多的在前"], ["unmapped", "未绑定列，少的在前"],
  ["-watch", "注意事项，多的在前"], ["watch", "注意事项，少的在前"],
  ["-watch_conflicts", "与材料矛盾的注意事项，多的在前"], ["watch_conflicts", "与材料矛盾的注意事项，少的在前"],
];

export async function tables(_, params) {
  const filters = {
    text: params.get("text"), domain: params.get("domain"), concept: params.get("concept"),
    sort: params.get("sort"),
  };
  const offset = offsetOf(params);
  const page = await answer("/api/list", { kind: "tables", ...filters, offset, limit: PAGE });
  const byTable = page.by_table || null;
  const columns = byTable ? byTable.columns : [];
  const rows = page.items.map((rep) => [
    tableLink(rep.table), conceptLink(rep.concept), word(REP_KIND_TEXT, rep.kind),
    word(TIME_TEXT, rep.time), String(rep.columns), text(rep.about),
    ...columns.map((column) => rep.by_table.cells[column.key]),
  ]);
  const sorts = byTable ? TABLE_SORT_CHOICES : TABLE_SORT_CHOICES.slice(0, 2);
  const fields = [input("text", "表名包含", filters.text), input("concept", "概念", filters.concept, "id 或名称"),
    input("domain", "业务域", filters.domain, "domain:…"), select("sort", "排序", sorts, filters.sort)];
  return [
    crumbs("表"),
    h("h1", {}, "表"),
    filterForm(fields, (values) => go("tables", null, values)),
    byTable ? h("p", { class: "muted" },
      "表名之后几列与 index.md「按表看」相同：度量列是绑定到度量属性的列；单位有没有材料依据按属性判断，" +
      "与取数包标注单位用的是同一条规则。默认按表名排列；按某一列排序时，没有表语义的表排在最后。")
      : h("p", { class: "muted" }, "服务启动时没有给表语义目录（--semantics），这里没有「按表看」的几列。"),
    byTable && byTable.note ? h("p", { class: "muted" }, byTable.note) : null,
    grid(["表", "概念", "种类", "时间形态", "绑定列", "说明", ...columns.map((column) => column.label)], rows),
    pager(page, (next) => go("tables", null, { ...filters, offset: next })),
  ];
}

function select(name, label, options, current) {
  return h("label", {}, label, h("select", { name }, options.map(([valueOf, labelOf]) =>
    h("option", { value: valueOf, selected: valueOf === (current || "") || null }, labelOf))));
}

export async function metrics(_, params) {
  const filters = { text: params.get("text"), domain: params.get("domain"), concept: params.get("concept") };
  const offset = offsetOf(params);
  const page = await answer("/api/list", { kind: "metrics", ...filters, offset, limit: PAGE });
  const rows = page.items.map((m) => [
    link("metric", m.id, m.name), m.on ? conceptLink(m.on) : "—", text(m.aggregation), text(m.definition),
    word(STATUS_TEXT, m.status),
  ]);
  return [
    crumbs("指标"),
    h("h1", {}, "指标"),
    filterForm([input("text", "名称包含", filters.text), input("concept", "概念", filters.concept, "id 或名称"),
      input("domain", "业务域", filters.domain, "domain:…")],
    (values) => go("metrics", null, values)),
    grid(["指标", "概念", "聚合", "定义", "状态"], rows),
    pager(page, (next) => go("metrics", null, { ...filters, offset: next })),
  ];
}

// ------------------------------------------------------------------ questions

const SOURCE_TEXT = { semantics: "表语义", pending: "待确认的定义" };

export async function questions(_, params) {
  const filters = {
    status: params.get("status") || "open", source: params.get("source"), table: params.get("table"),
    concept: params.get("concept"), text: params.get("text"),
  };
  const offset = offsetOf(params);
  const board = await answer("/api/questions", { ...filters, offset, limit: PAGE });
  const select = (name, label, options, current) => h("label", {}, label,
    h("select", { name }, options.map(([valueOf, labelOf]) =>
      h("option", { value: valueOf, selected: valueOf === (current || "") || null }, labelOf))));
  const conceptOptions = [["", "全部"], ...board.concepts.map((c) => [c.id, `${c.name}（${c.count}）`])];
  if (filters.concept && !board.concepts.some((c) => c.id === filters.concept)) {
    conceptOptions.push([filters.concept, filters.concept]);
  }
  const notes = [];
  if (!board.checked.semantics) notes.push("服务启动时没有给表语义目录（--semantics），这里没有表语义里的问题。");
  if (!board.checked.pending) notes.push("服务启动时没有给待确认文件（--pending），这里只列表语义里的问题。");
  const counts = board.counts;
  return [
    crumbs("待确认问题"),
    h("h1", {}, "待确认问题"),
    notes.map((note) => h("p", { class: "muted" }, note)),
    filterForm([
      select("status", "状态", [["open", "待确认"], ["answered", "已回答"], ["all", "全部"]], filters.status),
      select("source", "来源", [["", "全部"], ["semantics", "表语义"], ["pending", "待确认的定义"]], filters.source),
      select("concept", "概念", conceptOptions, filters.concept),
      input("table", "表", filters.table, "db.table"),
      input("text", "包含", filters.text),
    ], (values) => go("questions", null, values)),
    h("p", { class: "muted" },
      `表语义 ${counts.semantics} 条 · 待确认的定义 ${counts.pending} 项 · 目录里没有的 ${counts.not_in_catalog} 项`),
    board.items.length ? h("div", {}, board.items.map(questionCard)) : h("p", { class: "muted" }, "没有符合条件的问题。"),
    pager(board, (next) => go("questions", null, { ...filters, offset: next })),
    board.problems.length ? section("待确认文件里读不了的行",
      list(board.problems, (p) => `第 ${p.line} 行：${p.message}`)) : null,
  ];
}

function questionCard(item) {
  const marks = [badge(SOURCE_TEXT[item.source] || item.source)];
  if (!item.in_catalog) marks.push(badge("目录里没有", "warn"));
  const concepts = item.concepts.length ? joined(item.concepts.map(conceptLink)) : null;
  if (item.source === "semantics") {
    return h("div", { class: "card" },
      h("div", {}, marks, " ", badge(word(QUESTION_STATUS_TEXT, item.status), item.status === "open" ? "warn" : null)),
      h("p", {}, text(item.text)),
      kv([
        ["表", tableLink(item.table)],
        ["概念", concepts],
        ["编号", item.id],
        ["涉及", item.about.length ? item.about.join("、") : null],
        ["列", item.columns.length ? joined(item.columns.map((c) =>
          [code(c.column), c.bound ? "" : "（目录未绑定）"])) : null],
      ]));
  }
  const dates = item.dates.first === item.dates.last ? item.dates.first : `${item.dates.first} 至 ${item.dates.last}`;
  return h("div", { class: "card" },
    h("div", {}, marks, " ", badge(`${item.hits} 次`)),
    h("p", {}, h("strong", {}, item.missing)),
    kv([
      ["问到它的问题", list(item.questions, (q) => q)],
      ["业务词", item.terms.join("、")],
      ["涉及", item.columns.length || item.tables.length
        ? joined([...item.columns.map((c) => code(c)), ...item.tables.filter((t) =>
          !item.columns.some((c) => c.startsWith(t + "."))).map(tableLink)]) : null],
      ["概念", concepts],
      ["提议的定义", item.proposed.length ? list(item.proposed, (p) => p) : null],
      ["记录日期", `${dates}（第 ${item.lines.join("、")} 行）`],
      ["表语义已记录的问题", item.recorded_questions && item.recorded_questions.length
        ? list(item.recorded_questions, (q) => [tableLink(q.table), ` ${q.id}（${word(QUESTION_STATUS_TEXT, q.status)}）`, text(q.text)])
        : null],
      ["目录现在有同名对象", item.catalog_objects.length
        ? list(item.catalog_objects, (o) => objectLink(o)) : null],
    ]));
}

function objectLink(found) {
  if (found.kind === "concept") return link("concept", found.id, found.name);
  if (found.kind === "metric") return link("metric", found.id, found.name);
  if (found.kind === "table") return tableLink(found.id);
  return [found.name, " ", code(found.id)];
}

// ------------------------------------------------------------------ search

const HIT_TEXT = {
  concept: "概念", metric: "指标", attribute: "属性", identifier: "标识", code_set: "码值集", table: "表",
};

export async function search(_, params) {
  const words = (params.get("text") || "").trim();
  if (!words) return [crumbs("搜索"), h("p", { class: "muted" }, "在上方输入一个词、一个列名或一句问题。")];
  const { status, body } = await api("/api/search", { text: words, limit: 30 });
  if (status !== 200 && status !== 404) throw new Error(body && body.error ? body.error.message : `HTTP ${status}`);
  const hits = body.hits || [];
  return [
    crumbs("搜索"),
    h("h1", {}, `搜索：${words}`),
    hits.length ? grid(["类别", "名称", "说明", "所在"], hits.map((hit) => [
      HIT_TEXT[hit.kind] || hit.kind, hitLink(hit), text(hit.summary), text(hit.where),
    ])) : h("p", { class: "muted" }, "没有相近的目录对象。"),
  ];
}

function hitLink(hit) {
  if (hit.kind === "concept") return link("concept", hit.id, hit.name);
  if (hit.kind === "metric") return link("metric", hit.id, hit.name);
  if (hit.kind === "table") return tableLink(hit.id);
  if (hit.kind === "attribute" || hit.kind === "identifier") {
    const button = h("button", { type: "button" }, "所属概念");
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const found = await answer("/api/query", { kind: hit.kind, term: hit.id }, { notFoundOk: true });
        const match = found.matches[0];
        const owner = match && (match.concept || match.identifies);
        if (owner) go("concept", owner.id);
        else button.textContent = "没有所属概念";
      } catch (error) {
        button.textContent = error.message;
      }
    });
    return [hit.name, " ", code(hit.id), " ", button];
  }
  return [hit.name, " ", code(hit.id)];
}
