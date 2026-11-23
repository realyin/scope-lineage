// The relations graph of one concept's neighbourhood, drawn as SVG by hand: the concept in
// the middle, its neighbours on a ring, every relation between two drawn concepts as a
// curve (spread apart when two concepts share several, a loop for a concept related to
// itself). ``layoutGraph`` is a pure function (no DOM) so its geometry can be checked;
// ``drawGraph`` turns its result into SVG. Labels are text nodes; nothing is markup.

import { KIND_TEXT, RELATION_KIND_TEXT, href, word } from "./dom.js";

const SVG = "http://www.w3.org/2000/svg";
const NODE_H = 40;
const NODE_FONT = 14;
const SUB_FONT = 11;
const LABEL_FONT = 12;
const LABEL_H = 17;
const LABEL_CHARS = 12;
const EDGE_LABEL_CHARS = 10;
const EDGE_LABELS_UP_TO = 16; // with more nodes, edge labels crowd: the table below has them
const PARALLEL_GAP = 44; // how far apart the curves between the same two concepts run
const PAD = 16;

function clip(value, limit) {
  const textValue = String(value || "");
  return textValue.length <= limit ? textValue : textValue.slice(0, limit - 1) + "…";
}

/** A rough width of a label: wide characters count about twice a narrow one. */
export function textWidth(value, size) {
  let units = 0;
  for (const ch of String(value)) units += ch.charCodeAt(0) > 0x2e80 ? 1 : 0.6;
  return units * size;
}

function box(x, y, w, h) {
  return { x: x - w / 2, y: y - h / 2, w, h };
}

export function overlaps(a, b, margin = 2) {
  return a.x < b.x + b.w + margin && b.x < a.x + a.w + margin &&
    a.y < b.y + b.h + margin && b.y < a.y + a.h + margin;
}

function contains(b, point) {
  return point.x >= b.x && point.x <= b.x + b.w && point.y >= b.y && point.y <= b.y + b.h;
}

/** Where a line from ``from`` towards a box's centre meets the box's border. */
function boxEdge(from, node) {
  const dx = node.x - from.x;
  const dy = node.y - from.y;
  const scale = Math.min(
    Math.abs(dx) > 0.01 ? (node.w / 2) / Math.abs(dx) : Infinity,
    Math.abs(dy) > 0.01 ? (node.h / 2) / Math.abs(dy) : Infinity,
  );
  if (!isFinite(scale) || scale >= 1) return { x: node.x, y: node.y };
  return { x: node.x - dx * scale, y: node.y - dy * scale };
}

function placeNodes(graph) {
  const others = graph.nodes.filter((node) => !node.centre);
  const n = others.length;
  let ry = Math.max(95, Math.min(300, n * 24));
  let rx = Math.max(n > 1 ? 210 : 0, Math.min(430, ry * 1.6));
  const start = -Math.PI / 2 + (n > 0 ? Math.PI / n : 0); // two neighbours: left and right
  const placed = new Map();
  for (const node of graph.nodes) {
    const label = clip(node.name, LABEL_CHARS);
    const sub = `${word(KIND_TEXT, node.kind)} · ${node.tables} 张表`;
    const w = Math.max(textWidth(label, NODE_FONT), textWidth(sub, SUB_FONT)) + 24;
    placed.set(node.id, { id: node.id, name: node.name, centre: !!node.centre, x: 0, y: 0, w, h: NODE_H, label, sub });
  }
  const ring = [...placed.values()].filter((node) => !node.centre);
  // widen the ring until no two boxes touch (a crowded neighbourhood draws larger, and
  // the box scrolls it)
  for (let attempt = 0; attempt < 40; attempt += 1) {
    ring.forEach((node, index) => {
      const angle = start + (2 * Math.PI * index) / Math.max(1, n);
      node.x = Math.cos(angle) * rx;
      node.y = Math.sin(angle) * (n === 1 ? 130 : ry);
    });
    const boxes = [...placed.values()].map((node) => box(node.x, node.y, node.w, node.h));
    const crowded = boxes.some((a, i) => boxes.slice(i + 1).some((b) => overlaps(a, b, 6)));
    if (!crowded) break;
    rx *= 1.12;
    ry *= 1.12;
  }
  return placed;
}

/**
 * The geometry of a neighbourhood answer: {width, height, viewBox, nodes, edges}. Each edge
 * has ``path`` and, when labels are shown, ``label`` {x, y, w, h, text} placed beside its
 * curve, clear of every node and every other label where the tried positions allow.
 */
export function layoutGraph(graph) {
  const placed = placeNodes(graph);
  const nodeBoxes = [...placed.values()].map((node) => box(node.x, node.y, node.w, node.h));
  const showLabels = graph.nodes.length <= EDGE_LABELS_UP_TO;
  const pairKey = (edge) => [edge.from, edge.to].sort().join("\u0000");
  const pairTotal = new Map();
  for (const edge of graph.edges) pairTotal.set(pairKey(edge), (pairTotal.get(pairKey(edge)) || 0) + 1);
  const pairSeen = new Map();
  const labels = [];
  const extents = [];
  const edges = [];
  graph.edges.forEach((edge, index) => {
    const a = placed.get(edge.from);
    const b = placed.get(edge.to);
    if (!a || !b) return;
    const key = pairKey(edge);
    const i = pairSeen.get(key) || 0;
    pairSeen.set(key, i + 1);
    const total = pairTotal.get(key);
    let path;
    let mid;
    let normal;
    let side;
    if (edge.from === edge.to) {
      const lift = 40 + i * 22;
      const top = a.y - a.h / 2;
      path = `M ${a.x - 16} ${top} C ${a.x - 46} ${top - lift}, ${a.x + 46} ${top - lift}, ${a.x + 16} ${top}`;
      mid = { x: a.x, y: top - lift * 0.75 };
      normal = { x: 0, y: -1 };
      side = 1;
      extents.push(box(a.x, top - lift * 0.75, 70, 2));
    } else {
      // the edges of one pair spread symmetrically about the straight line, and an edge's
      // direction does not change which side it takes
      const [p, q] = edge.from < edge.to ? [a, b] : [b, a];
      const dx = q.x - p.x;
      const dy = q.y - p.y;
      const length = Math.hypot(dx, dy) || 1;
      normal = { x: -dy / length, y: dx / length };
      const bend = (i - (total - 1) / 2) * PARALLEL_GAP;
      const cx = (a.x + b.x) / 2 + normal.x * bend * 2;
      const cy = (a.y + b.y) / 2 + normal.y * bend * 2;
      const end = boxEdge({ x: cx, y: cy }, b);
      path = `M ${a.x} ${a.y} Q ${cx} ${cy} ${end.x} ${end.y}`;
      mid = { x: 0.25 * a.x + 0.5 * cx + 0.25 * b.x, y: 0.25 * a.y + 0.5 * cy + 0.25 * b.y };
      side = bend < 0 ? -1 : 1;
    }
    const result = {
      index, id: edge.id || null, kind: edge.kind, from: edge.from, to: edge.to, path, mid,
      joined: Boolean((edge.joins && edge.joins.count) || (edge.keys && edge.keys.length)),
      label: null,
    };
    if (showLabels && (edge.name || edge.kind === "role")) {
      const text = clip(edge.kind === "role" ? "角色" : edge.name, EDGE_LABEL_CHARS);
      result.label = placeLabel(text, mid, normal, side, nodeBoxes, labels);
      labels.push(result.label);
    }
    edges.push(result);
  });
  const all = [...nodeBoxes, ...labels, ...extents];
  const minX = Math.min(...all.map((b) => b.x)) - PAD;
  const minY = Math.min(...all.map((b) => b.y)) - PAD;
  const maxX = Math.max(...all.map((b) => b.x + b.w)) + PAD;
  const maxY = Math.max(...all.map((b) => b.y + b.h)) + PAD;
  const width = Math.ceil(maxX - minX);
  const height = Math.ceil(maxY - minY);
  return {
    width, height, viewBox: `${Math.floor(minX)} ${Math.floor(minY)} ${width} ${height}`,
    nodes: [...placed.values()], edges,
  };
}

/** The first position beside the curve's middle (its own side first, then the other, then
 * further out, then slid along it) whose box meets no node and no label already placed. */
function placeLabel(text, mid, normal, side, nodeBoxes, labels) {
  const w = textWidth(text, LABEL_FONT) + 8;
  const h = LABEL_H;
  // how far the box reaches along the normal: past that it cannot cover its own line
  const reach = Math.abs(normal.x) * (w / 2) + Math.abs(normal.y) * (h / 2) + 4;
  const tangent = { x: normal.y, y: -normal.x };
  const tries = [];
  for (const out of [0, 16, 32, 48]) {
    for (const slide of [0, 24, -24, 48, -48]) {
      for (const s of [side, -side]) tries.push({ distance: s * (reach + out), slide });
    }
  }
  let first = null;
  for (const { distance, slide } of tries) {
    const x = mid.x + normal.x * distance + tangent.x * slide;
    const y = mid.y + normal.y * distance + tangent.y * slide;
    const candidate = { ...box(x, y, w, h), text, cx: x, cy: y };
    if (!first) first = candidate;
    if (contains(candidate, mid)) continue;
    if (nodeBoxes.some((b) => overlaps(candidate, b)) || labels.some((b) => overlaps(candidate, b))) continue;
    return candidate;
  }
  return first;
}

function el(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, String(value));
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function edgeTitle(edge, names) {
  const kind = word(RELATION_KIND_TEXT, edge.kind);
  const from = names.get(edge.from) || edge.from;
  const to = names.get(edge.to) || edge.to;
  return `${from} ${edge.name || ""} ${to}（${kind}）`;
}

/**
 * The SVG for a neighbourhood answer ({nodes, edges}); a node links to its concept view.
 * It is drawn at its natural size (text at the page's size), never stretched; a box
 * narrower than the drawing scrolls it sideways.
 */
export function drawGraph(graph) {
  const layout = layoutGraph(graph);
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]));
  const svg = el("svg", {
    viewBox: layout.viewBox, width: layout.width, height: layout.height, role: "img",
    "aria-label": `关系图：${graph.nodes.length} 个概念，${graph.edges.length} 条关系`,
  });
  svg.append(el("defs", {},
    el("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7,
      markerHeight: 7, orient: "auto-start-reverse" },
    el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "arrow" }))));
  const lines = el("g", {});
  const labels = el("g", {});
  layout.edges.forEach((placed) => {
    const edge = graph.edges[placed.index];
    const cls = "edge" + (placed.kind === "role" ? " role" : "") + (placed.joined ? " joined" : "");
    const line = el("path", { d: placed.path, class: cls });
    if (placed.kind !== "role") line.setAttribute("marker-end", "url(#arrow)");
    lines.append(el("g", {}, el("title", {}, edgeTitle(edge, names)), line));
    if (placed.label) {
      const label = placed.label;
      labels.append(el("g", { class: "edge-label" },
        el("title", {}, edgeTitle(edge, names)),
        el("rect", { x: label.x, y: label.y, width: label.w, height: label.h, rx: 3 }),
        el("text", { x: label.cx, y: label.cy + 4, "text-anchor": "middle" }, label.text)));
    }
  });
  svg.append(lines);
  const nodes = el("g", {});
  for (const node of layout.nodes) {
    const anchor = el("a", { href: href("concept", node.id) },
      el("title", {}, `${node.name}（${node.id}）`),
      el("rect", { x: node.x - node.w / 2, y: node.y - node.h / 2, width: node.w, height: node.h, rx: 6 }),
      el("text", { x: node.x, y: node.y - 3, "text-anchor": "middle" }, node.label),
      el("text", { x: node.x, y: node.y + 13, "text-anchor": "middle", class: "sub" }, node.sub));
    nodes.append(el("g", { class: node.centre ? "node centre" : "node" }, anchor));
  }
  svg.append(nodes);
  svg.append(labels); // last: a label is never under a line or a node
  return svg;
}
