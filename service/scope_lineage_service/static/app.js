// The browse page: hash routes (#/concept/<id>, #/table/<db.table>, ...) so every view can
// be linked, a navigation bar, and the search box. Read-only: it only ever GETs.

import { h, href, pageTitle } from "./dom.js";
import * as views from "./views.js";

// view name -> function(id, URLSearchParams) returning the nodes of <main>
const ROUTES = {
  "": views.home,
  domain: views.domain,
  concept: views.concept,
  metric: views.metric,
  table: views.table,
  tables: views.tables,
  metrics: views.metrics,
  questions: views.questions,
  search: views.search,
};

// The navigation, in order. A later view (an ask panel answering data questions from the
// catalog) is added here and in ROUTES; nothing else in the page needs to change.
const NAV = [
  ["", "目录"],
  ["tables", "表"],
  ["metrics", "指标"],
  ["questions", "待确认问题"],
];

const TITLES = {
  "": "本体目录", domain: "业务域", concept: "概念", metric: "指标", table: "表",
  tables: "表", metrics: "指标", questions: "待确认问题", search: "搜索",
};

let current = 0;

function parse(hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query] = splitOnce(raw, "?");
  const [view, rest] = splitOnce(path, "/");
  let id = null;
  if (rest) {
    try {
      id = decodeURIComponent(rest);
    } catch (error) {
      id = rest;
    }
  }
  return { view, id, params: new URLSearchParams(query || "") };
}

function splitOnce(value, separator) {
  const at = value.indexOf(separator);
  return at < 0 ? [value, ""] : [value.slice(0, at), value.slice(at + 1)];
}

function drawNav(view) {
  const nav = document.getElementById("nav");
  const active = ["concept", "domain"].includes(view) ? "" : view === "metric" ? "metrics"
    : view === "table" ? "tables" : view;
  nav.replaceChildren(...NAV.map(([name, label]) =>
    h("a", { href: href(name), "aria-current": name === active ? "page" : null }, label)));
}

async function render() {
  const token = ++current;
  const main = document.getElementById("main");
  const { view, id, params } = parse(window.location.hash);
  const route = Object.prototype.hasOwnProperty.call(ROUTES, view) ? ROUTES[view] : null;
  drawNav(view);
  // the box shows a search's words on the search view only; elsewhere it starts empty
  document.getElementById("search-text").value = view === "search" ? params.get("text") || "" : "";
  document.title = pageTitle(null, TITLES[view] || null, true);
  main.replaceChildren(h("p", { class: "muted" }, "正在加载……"));
  let nodes;
  try {
    nodes = route ? await route(id, params) : [h("p", { class: "error" }, "没有这个页面。"), h("a", { href: "#/" }, "回到目录")];
  } catch (error) {
    nodes = [h("p", { class: "error" }, `出错了：${error.message}`)];
  }
  if (token !== current) return; // a later click has already replaced this view
  const content = h("div", {}, nodes);
  main.replaceChildren(content);
  // the title is the heading the new view shows, set once it is shown
  const heading = content.querySelector("h1");
  document.title = pageTitle(heading ? heading.firstChild && heading.firstChild.textContent : null,
    TITLES[view] || null, false);
  window.scrollTo(0, 0);
}

function start() {
  document.getElementById("search").addEventListener("submit", (event) => {
    event.preventDefault();
    const words = document.getElementById("search-text").value.trim();
    if (words) window.location.hash = href("search", null, { text: words }).slice(1);
  });
  window.addEventListener("hashchange", render);
  render();
}

start();
