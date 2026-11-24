// The browse views. Each takes the route's id and parameters, fetches the answers it
// shows and returns the nodes to put in <main>. Every catalog string goes in as text.

import {
  BINDING_TEXT, CATEGORY_TEXT, CONSTRAINT_KIND_TEXT, GRAIN_SOURCE_TEXT, KIND_TEXT,
  QUESTION_STATUS_TEXT, RELATION_KIND_TEXT, REP_KIND_TEXT, STATUS_TEXT, STRENGTH_TEXT,
  TABLE_STATUS_TEXT, TIME_TEXT,
  answer, api, append, badge, breakableName, code, conceptLink, fold, grid, h, href, joined, kv, link, pager,
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
  out.push(...section("表语义", doc ? semanticsDocument(doc, pageMarks(semantics))
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
// width classes (app.css): name and binding never wrap, the target keeps a minimum width,
// the lineage expression keeps its own so a narrow screen scrolls instead of squeezing
export const GRID_CLASSES = ["short", "short", "col-prose", "col-expr", "short"];

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
      h("td", { class: GRID_CLASSES[0] }, code(column.column)),
      h("td", { class: GRID_CLASSES[1] }, word(BINDING_TEXT, column.to)),
      h("td", { class: GRID_CLASSES[2] }, column.ref_name || column.concept || column.via || (unit && unit.text) ? target : "—"),
      h("td", { class: GRID_CLASSES[3] }, column.evidence && column.evidence.expression ? code(column.evidence.expression, true) : "—"),
      h("td", { class: GRID_CLASSES[4] }, more));
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
  const head = h("tr", {}, GRID_COLUMNS.map((n, i) => h("th", { scope: "col", class: GRID_CLASSES[i] }, n)));
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
      [`${q.id} `, badge(q.status === "set_aside" ? "已搁置" : word(QUESTION_STATUS_TEXT, q.status)),
        q.written === false ? badge("未写回", "warn") : null, " ", text(q.text),
        q.answer ? h("div", { class: "muted" }, `回答：${q.answer}`) : null]) : null],
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

/** The page's marks on a table's questions, from the keys the server puts beside the
 * document when it takes the page's answers (``unwritten``, ``page``); null otherwise. */
export function pageMarks(answer) {
  if (!answer || (!("unwritten" in answer) && !("page" in answer))) return null;
  return { unwritten: new Set(answer.unwritten || []), page: answer.page || {} };
}

function semanticsDocument(doc, marks) {
  const summary = doc.summary || {};
  const parts = [];
  parts.push(fold("一页纸", true, ...SUMMARY_LABELS.filter(([key]) => key in summary)
    .map(([key, label]) => fold(`${label}${countOf(summary[key])}`, key === "what" || key === "row" ||
      key === "questions", summaryValue(key, summary[key], marks))),
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

function summaryValue(key, item, marks) {
  if (key === "questions" && Array.isArray(item)) {
    return list(item, (q) => {
      const note = marks ? marks.page[q.id] : null;
      const aside = note && (note.kind === "invalid" || note.kind === "not_applicable") && q.status !== "answered";
      const status = aside ? "已搁置" : word(QUESTION_STATUS_TEXT, q.status);
      return [`${q.id || ""} `, badge(status, q.status === "open" && !aside ? "warn" : null),
        marks && marks.unwritten.has(q.id) ? badge("未写回", "warn") : null,
        " ", text(q.text), q.about && q.about.length ? h("span", { class: "muted" }, `（${q.about.join("、")}）`) : null,
        q.status === "answered" && q.answer ? h("div", { class: "muted" },
          `回答：${q.answer}（${[q.answered_by, q.answered_on].filter(Boolean).join("，") || "未署名"}）`) : null,
        note && q.status !== "answered" ? h("div", { class: "muted" },
          `页面备注：${recordText(note)}（${[note.by, note.date].filter(Boolean).join("，")}）`) : null];
    });
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

// width classes of the table list's columns (app.css): the name wraps at "." and "_" up to
// a cap, short columns never wrap, the description keeps a minimum width
export const TABLE_LIST_CLASSES = ["col-name", "short", "short", "short", "short", "col-prose"];

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
    h("a", { href: href("table", rep.table), class: "name" }, breakableName(rep.table)),
    conceptLink(rep.concept), word(REP_KIND_TEXT, rep.kind),
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
    grid(["表", "概念", "种类", "时间形态", "绑定列", "说明", ...columns.map((column) => column.label)], rows,
      TABLE_LIST_CLASSES.concat(columns.map(() => "short"))),
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

// The page's answers (a server started with --answers). The pure functions below build what
// a card shows and what it sends; the views after them draw and post.

/** The kinds of record a person may leave on a question, in the order the menu offers. */
export const RECORD_KINDS = [
  ["answer", "回答"], ["partial", "部分回答"], ["deferred", "暂时确认不了"],
  ["redirect", "该问某某"], ["invalid", "问题有误"], ["not_applicable", "不适用"],
];
export const NOTE_TEXT = {
  partial: "部分回答", deferred: "暂时确认不了", redirect: "该问", invalid: "问题有误",
  not_applicable: "不适用",
};
export const CHOICE_TEXT = { yes: "是", no: "否" };
const CHOICE_KINDS = ["answer", "partial"];
export const MAX_TEXT = 1000;
export const MAX_NAME = 60;
export const NAME_KEY = "scope-lineage-service.answers.by";
export const EXPORT_FILE = "semantic-confirmations.json";
const ANSWER_KEYS = ["answer", "answered_by", "answered_on"];

/** The status filter's choices: 已搁置 only when the server takes the page's answers. */
export function statusChoices(answersOn) {
  const choices = [["open", "待确认"], ["answered", "已回答"]];
  if (answersOn) choices.push(["set_aside", "已搁置"]);
  choices.push(["all", "全部"]);
  return choices;
}

/** What the card of a table-semantics item shows, from the board's item:
 * ``open`` (no answer), ``answered`` (the document's answer), ``unwritten`` (the page's
 * answer, not written back), ``note`` (a page note on an open question), ``set_aside``
 * (a note that sets it aside); ``unmatched`` is true when the item's page record did not
 * match the document (the card shows the document as it is). ``canNote``: a note may be
 * left (the document has not answered it). */
export function cardState(item) {
  const unmatched = item.record_state === "unmatched";
  let mode = "open";
  if (item.written === false) mode = "unwritten";
  else if (item.status === "set_aside") mode = "set_aside";
  else if (item.page) mode = "note";
  else if (item.status === "answered") mode = "answered";
  const disk = diskOf(item);
  return { mode, unmatched, canNote: disk === null, record: item.record || null, disk };
}

/** The document's answer to the item as the board shows it: the record's ``disk`` when the
 * item carries a page record, otherwise the item's own answer (it is not overlaid). */
export function diskOf(item) {
  if (item.record) return item.disk || null;
  if (item.status !== "answered") return null;
  const out = {};
  for (const key of ANSWER_KEYS) out[key] = item[key] === undefined ? null : item[key];
  return out;
}

/** ``seen``: what the page showed of the question, sent back so the server can refuse
 * (409) an answer to something that changed since. */
export function seenOf(item) {
  return { disk: diskOf(item), record: item.record || null };
}

/** The text and fields of a record as one line: ``否：…``, or ``该问 某某：…``. */
export function recordText(record) {
  if (!record) return "";
  const text = record.kind === "answer" ? record.answer : record.reason;
  const choice = CHOICE_TEXT[record.choice] ? `${CHOICE_TEXT[record.choice]}：` : "";
  if (record.kind === "answer") return `${choice}${text}`;
  const label = NOTE_TEXT[record.kind] || record.kind;
  const to = record.kind === "redirect" && record.to ? ` ${record.to}` : "";
  return `${label}${to}：${choice}${text}`;
}

function normalised(value) {
  return String(value === null || value === undefined ? "" : value).normalize("NFKC").trim();
}

/** The sentence why a form cannot be sent yet, or null. Mirrors the server's guards. */
export function formProblem(form) {
  const by = normalised(form.by);
  const text = normalised(form.text);
  if (!by) return "先填回答人。";
  if ([...by].length > MAX_NAME) return `回答人最多 ${MAX_NAME} 个字。`;
  if (!text) return form.kind === "answer" ? "回答不能是空的。" : "理由不能是空的。";
  if ([...text].length > MAX_TEXT) return `最多 ${MAX_TEXT} 个字。`;
  if (/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(text + by + normalised(form.to))) {
    return "写在一行里：不能有换行或控制字符。";
  }
  if (form.kind === "redirect" && !normalised(form.to)) return "写上该问谁。";
  if (form.kind === "redirect" && [...normalised(form.to)].length > MAX_NAME) {
    return `该问谁最多 ${MAX_NAME} 个字。`;
  }
  return null;
}

/** ``POST /api/answers``'s body for the item's card: ``form`` is
 * ``{kind, text, choice, to, by}`` as typed; ``asked`` is the question as shown. */
export function answerBody(item, form) {
  return recordBody(item.table, item.id, item.text, seenOf(item), form);
}

/** The body to answer again a record that did not match, to the question as it is now
 * (``entry`` from the board's ``answers.unmatched``). */
export function againBody(entry, form) {
  const now = entry.now || {};
  const disk = now.status === "answered"
    ? { answer: now.answer, answered_by: now.answered_by, answered_on: now.answered_on } : null;
  return recordBody(entry.table, entry.question, now.text, { disk, record: entry.record }, form);
}

function recordBody(table, question, asked, seen, form) {
  const kind = form.kind || "answer";
  const body = { table, question, kind, asked, seen, by: normalised(form.by) };
  body[kind === "answer" ? "answer" : "reason"] = form.text;
  if (form.choice && CHOICE_KINDS.includes(kind)) body.choice = form.choice;
  if (kind === "redirect") body.to = form.to;
  return body;
}

/** ``POST /api/answers/withdraw``'s body: the record as the page showed it. */
export function withdrawBody(table, question, record) {
  return { table, question, seen: record };
}

/** The sentence under the export button: how the file is written back. */
export function writeBackCommand() {
  return "scope-lineage semantic confirm <文档目录> --confirmations <下载的 " + EXPORT_FILE +
    "> --reviews <reviews 目录>";
}

/** The muted sentence a board shows when the page cannot answer, or null when it can. */
export function readOnlyReason(answers) {
  if (!answers) return "页面上不能回答：服务启动时没有给回答文件（--answers FILE）；加上它即可在这里回答问题。";
  if (answers.refused) return "页面上不能回答：别的机器也能连上这个服务，它不收回答；要收，启动时加 --answers-allow-remote。";
  if (answers.status !== "ok") return `页面上暂时不能回答：回答文件读不了（${answers.reason || "原因不明"}），修好或移走它后刷新。`;
  return null;
}

function rememberedName() {
  try {
    return window.localStorage.getItem(NAME_KEY) || "";
  } catch (error) {
    return "";
  }
}

function rememberName(name) {
  try {
    window.localStorage.setItem(NAME_KEY, name);
  } catch (error) {
    // private window or blocked storage: the name is asked for again next time
  }
}

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

function errorText(status, body) {
  if (status === 409) return "这条问题在你看到之后变了（问题被改写，或别人刚回答过），已重新载入，请再看一遍。";
  if (status === 403) return "这个服务不收页面上的回答（别的机器也能连上它）。";
  return body && body.error ? body.error.message : `请求失败（HTTP ${status}）`;
}

export async function questions(_, params) {
  const filters = {
    status: params.get("status") || "open", source: params.get("source"), table: params.get("table"),
    concept: params.get("concept"), text: params.get("text"),
  };
  const offset = offsetOf(params);
  const board = await answer("/api/questions", { ...filters, offset, limit: PAGE });
  const answers = board.answers || null;
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
  const writable = Boolean(answers && answers.writable);
  const name = h("input", { type: "text", value: rememberedName(), maxlength: String(MAX_NAME),
    placeholder: "回答前先填名字", "aria-label": "回答人" });
  name.addEventListener("change", () => rememberName(normalised(name.value)));
  const context = {
    answers, writable, name, bottom: h("div", {}), cards: new Map(),
    filters: { ...filters, offset, limit: PAGE },
  };
  const readOnly = board.checked.semantics ? readOnlyReason(answers) : null;
  const out = [
    crumbs("待确认问题"),
    h("h1", {}, "待确认问题"),
    notes.map((note) => h("p", { class: "muted" }, note)),
    filterForm([
      select("status", "状态", statusChoices(Boolean(answers)), filters.status),
      select("source", "来源", [["", "全部"], ["semantics", "表语义"], ["pending", "待确认的定义"]], filters.source),
      select("concept", "概念", conceptOptions, filters.concept),
      input("table", "表", filters.table, "db.table"),
      input("text", "包含", filters.text),
    ], (values) => go("questions", null, values)),
    h("p", { class: "muted" },
      `表语义 ${counts.semantics} 条 · 待确认的定义 ${counts.pending} 项 · 目录里没有的 ${counts.not_in_catalog} 项`),
    readOnly ? h("p", { class: "muted" }, readOnly) : null,
    writable ? h("p", { class: "answer-who" }, h("label", {}, "回答人 ", name),
      h("span", { class: "muted" }, " 记在这个浏览器里；日期由服务器取当天。回答先存在服务的回答文件里，「导出确认文件」后才写回文档。")) : null,
    board.items.length ? h("div", {}, board.items.map((item) => questionCard(item, context)))
      : h("p", { class: "muted" }, "没有符合条件的问题。"),
    pager(board, (next) => go("questions", null, { ...filters, offset: next })),
    board.problems.length ? section("待确认文件里读不了的行",
      list(board.problems, (p) => `第 ${p.line} 行：${p.message}`)) : null,
  ];
  if (answers) {
    drawAnswersBlock(context.bottom, answers, context);
    out.push(context.bottom);
  }
  return out;
}

function questionCard(item, context) {
  const card = h("div", { class: "card" });
  if (item.source === "semantics") context.cards.set(cardKey(item.table, item.id), card);
  drawCard(card, item, context, null);
  return card;
}

function cardMarks(item) {
  const marks = [badge(SOURCE_TEXT[item.source] || item.source)];
  if (!item.in_catalog) marks.push(badge("目录里没有", "warn"));
  return marks;
}

function drawCard(card, item, context, notice) {
  const concepts = item.concepts.length ? joined(item.concepts.map(conceptLink)) : null;
  if (item.source !== "semantics") {
    card.replaceChildren(...pendingCard(item, concepts));
    return;
  }
  const status = item.status === "set_aside" ? "已搁置" : word(QUESTION_STATUS_TEXT, item.status);
  const parts = [
    h("div", {}, cardMarks(item), " ", badge(status, item.status === "open" ? "warn" : null),
      item.written === false ? badge("未写回", "warn") : null),
    h("p", {}, text(item.text)),
    kv([
      ["表", tableLink(item.table)],
      ["概念", concepts],
      ["编号", item.id],
      ["涉及", item.about.length ? item.about.join("、") : null],
      ["列", item.columns.length ? joined(item.columns.map((c) =>
        [code(c.column), c.bound ? "" : "（目录未绑定）"])) : null],
      ["回答", item.answer ? [item.answer, h("span", { class: "muted" },
        `（${[item.answered_by, item.answered_on].filter(Boolean).join("，") || "未署名"}）`)] : null],
      ["页面备注", item.page ? [recordText(item.page), h("span", { class: "muted" },
        `（${[item.page.by, item.page.date].filter(Boolean).join("，")}）`)] : null],
    ]),
  ];
  if (context.answers) parts.push(answerPart(card, item, context));
  if (notice) parts.push(h("p", { class: "error", role: "status" }, notice));
  card.replaceChildren(...parts);
}

function pendingCard(item, concepts) {
  const dates = item.dates.first === item.dates.last ? item.dates.first : `${item.dates.first} 至 ${item.dates.last}`;
  return [
    h("div", {}, cardMarks(item), " ", badge(`${item.hits} 次`)),
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
    ]),
  ];
}

/** The answer box of a semantics card, or its actions (修改 / 撤回), by its state. */
function answerPart(card, item, context) {
  const state = cardState(item);
  const box = h("div", { class: "answer-box" });
  if (state.unmatched) {
    box.append(h("p", { class: "muted" }, "页面上留的「", recordText(state.record),
      "」没对上现在的文档，没有生效；见页面底部「没对上的回答」。"));
  }
  if (!context.writable) return box;
  const reload = (notice) => reloadCard(card, item, context, notice);
  const open = (preset) => {
    box.replaceChildren(answerForm({
      kinds: state.canNote ? RECORD_KINDS : RECORD_KINDS.slice(0, 1),
      preset,
      context,
      submit: (form) => answerBody(item, form),
      done: reload,
      cancel: () => reload(null),
    }));
  };
  const buttons = h("div", { class: "answer-actions" });
  const live = state.record && !state.unmatched;
  if (state.mode === "open" && !live) {
    box.append(answerForm({ kinds: RECORD_KINDS, preset: null, context,
      submit: (form) => answerBody(item, form), done: reload, cancel: null }));
    return box;
  }
  if (live) {
    buttons.append(h("button", { type: "button", onclick: () => open(state.record) }, "修改"),
      h("button", { type: "button", onclick: async (event) => {
        event.target.disabled = true;
        const { status, body } = await postJson("/api/answers/withdraw",
          withdrawBody(item.table, item.id, state.record));
        reload(status === 200 ? null : errorText(status, body));
      } }, "撤回"));
  } else {
    buttons.append(h("button", { type: "button", onclick: () => open(null) },
      state.mode === "answered" ? "修改回答" : "回答"));
  }
  box.append(buttons);
  return box;
}

/** The form: the text, an optional 是/否, the kind menu and (for 该问某某) who to ask. */
function answerForm({ kinds, preset, context, submit, done, cancel }) {
  const kind = h("select", { "aria-label": "种类" }, kinds.map(([value, label]) =>
    h("option", { value, selected: preset && preset.kind === value ? "" : null }, label)));
  const textBox = h("textarea", { rows: "2", maxlength: String(MAX_TEXT), placeholder: "写在一行里" });
  textBox.value = preset ? (preset.kind === "answer" ? preset.answer : preset.reason) || "" : "";
  const choice = h("select", { "aria-label": "是或否" },
    h("option", { value: "" }, "不标是否"), h("option", { value: "yes" }, "是"), h("option", { value: "no" }, "否"));
  choice.value = preset && preset.choice ? preset.choice : "";
  const to = h("input", { type: "text", maxlength: String(MAX_NAME), placeholder: "该问谁（名字）",
    "aria-label": "该问谁" });
  to.value = preset && preset.to ? preset.to : "";
  const message = h("span", { class: "muted", role: "status" });
  const send = h("button", { type: "submit" }, "提交");
  const sync = () => {
    to.hidden = kind.value !== "redirect";
    choice.hidden = !CHOICE_KINDS.includes(kind.value);
    textBox.placeholder = kind.value === "answer" ? "回答，写在一行里" : kind.value === "partial"
      ? "已经答了的那部分" : "理由，写在一行里";
  };
  kind.addEventListener("change", sync);
  sync();
  const form = h("form", { class: "answer-form" }, textBox,
    h("div", { class: "answer-actions" }, kind, choice, to, send,
      cancel ? h("button", { type: "button", onclick: cancel }, "取消") : null, message));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const typed = { kind: kind.value, text: textBox.value, choice: choice.value || null,
      to: to.value, by: context.name.value };
    const problem = formProblem(typed);
    if (problem) {
      message.textContent = problem;
      if (problem.startsWith("先填回答人")) context.name.focus();
      return;
    }
    rememberName(normalised(context.name.value));
    send.disabled = true;
    message.textContent = "正在提交……";
    const { status, body } = await postJson("/api/answers", submit(typed));
    if (status === 201) {
      done(null);
    } else if (status === 409) {
      done(errorText(status, body));
    } else {
      send.disabled = false;
      message.textContent = errorText(status, body);
    }
  });
  return form;
}

function cardKey(table, id) {
  return `${String(table).toLowerCase()}\n${id}`;
}

/** Load the card's item again (after an answer, or when the server says it changed): the
 * card itself, then every other card on the page and the board's bottom block, so the
 * page shows one state. A card keeps its place even when the filter would now leave it
 * out (an open question just answered stays where it was until the page is reloaded). */
async function reloadCard(card, item, context, notice) {
  try {
    const board = await answer("/api/questions", {
      table: item.table, status: "all", source: "semantics", limit: 200,
    });
    const fresh = board.items.find((found) => found.id === item.id);
    if (fresh) drawCard(card, fresh, context, notice);
    else card.replaceChildren(h("p", { class: "muted" }, "这条问题已经不在文档里了。"));
  } catch (error) {
    card.append(h("p", { class: "error" }, error.message));
  }
  await refreshPage(context, card);
}

/** Draw again every card of the page (but ``skip``) and the bottom block, from the
 * board as the page's own filter fetches it. */
async function refreshPage(context, skip) {
  let board;
  try {
    board = await answer("/api/questions", context.filters);
  } catch (error) {
    context.bottom.prepend(h("p", { class: "error" }, error.message));
    return;
  }
  for (const item of board.items) {
    const card = context.cards.get(cardKey(item.table, item.id));
    if (card && card !== skip && item.source === "semantics") drawCard(card, item, context, null);
  }
  if (board.answers) {
    context.answers = board.answers;
    context.writable = Boolean(board.answers.writable);
    drawAnswersBlock(context.bottom, board.answers, context);
  }
}

/** The bottom of the board: the answers that did not match, and the export. */
function drawAnswersBlock(block, answers, context) {
  const parts = [];
  const unmatched = answers.unmatched || [];
  parts.push(...section(`没对上的回答（${unmatched.length}）`, unmatched.length
    ? h("div", {}, unmatched.map((entry) => unmatchedCard(entry, context)))
    : h("p", { class: "muted" }, "没有：页面上留的回答和备注都对得上现在的文档。")));
  if (answers.problem) parts.push(h("p", { class: "error" }, answers.problem));
  const digests = Object.entries(answers.digests || {});
  parts.push(...section("写回文档",
    h("p", {}, answers.exported
      ? h("a", { class: "button", href: "/api/answers/export", download: EXPORT_FILE },
        `导出确认文件（${answers.exported} 条回答）`)
      : h("span", { class: "muted" }, "还没有可以导出的回答（备注不写回文档）。")),
    digests.length ? h("div", {}, h("p", { class: "muted" }, "导出时这些文档的摘要（写回前可核对文档没被换过）："),
      list(digests, ([table, digest]) => [tableLink(table), " ", code(digest)])) : null,
    h("p", { class: "muted" }, "下载后照手册 S12 写回：", code(writeBackCommand(), true),
      "；写回之后，这些回答的记录在服务下一次读到文档时自动删去。")));
  block.replaceChildren();
  append(block, parts); // skips the parts a section leaves out (null)
}

function unmatchedCard(entry, context) {
  const card = h("div", { class: "card" });
  const now = entry.now;
  const held = now === null || now === undefined ? "（表或问题不存在）"
    : [`问题：${text(now.text)}`, now.status === "answered"
      ? `；回答：${text(now.answer)}（${[now.answered_by, now.answered_on].filter(Boolean).join("，") || "未署名"}）`
      : "；待确认"];
  const record = entry.record;
  const draw = (notice) => {
    const actions = h("div", { class: "answer-actions" });
    const parts = [
      h("div", {}, badge(entry.message || entry.reason, "warn")),
      kv([
        ["表", tableLink(entry.table)],
        ["编号", entry.question],
        ["当时的问题", record.asked],
        ["页面上留的", [recordText(record), h("span", { class: "muted" }, `（${record.by}，${record.date}）`)]],
        ["文档现在", held],
      ]),
    ];
    if (context.writable) {
      actions.append(h("button", { type: "button", onclick: async (event) => {
        event.target.disabled = true;
        const { status, body } = await postJson("/api/answers/withdraw",
          withdrawBody(entry.table, entry.question, record));
        if (status === 200) await refreshPage(context);
        else draw(errorText(status, body));
      } }, "删除"));
      if (now) {
        actions.append(h("button", { type: "button", onclick: () => {
          const canNote = now.status !== "answered";
          actions.replaceWith(answerForm({
            kinds: canNote ? RECORD_KINDS : RECORD_KINDS.slice(0, 1), preset: record, context,
            submit: (form) => againBody(entry, form),
            done: async (message) => {
              await refreshPage(context);
              if (message) context.bottom.prepend(h("p", { class: "error", role: "status" }, message));
            },
            cancel: () => draw(null),
          }));
        } }, "按现在的问题重新回答"));
      }
      parts.push(actions);
    }
    if (notice) parts.push(h("p", { class: "error", role: "status" }, notice));
    card.replaceChildren(...parts);
  };
  draw(null);
  return card;
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
