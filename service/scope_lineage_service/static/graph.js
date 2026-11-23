// The relations graph of one concept's neighbourhood, drawn as SVG by hand: the concept in
// the middle, its neighbours on a ring, every relation between two drawn concepts as a
// line (a curve when two concepts share several, a loop for a concept related to itself).
// Labels are text nodes; nothing is parsed as markup.

import { KIND_TEXT, RELATION_KIND_TEXT, href, word } from "./dom.js";

const SVG = "http://www.w3.org/2000/svg";
const WIDTH = 760;
const NODE_H = 38;
const LABEL_CHARS = 12;
const EDGE_LABEL_CHARS = 10;
const EDGE_LABELS_UP_TO = 16; // with more nodes, edge labels crowd: the table below has them

function el(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, String(value));
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clip(value, limit) {
  const textValue = String(value || "");
  return textValue.length <= limit ? textValue : textValue.slice(0, limit - 1) + "…";
}

/** A rough width of a label: wide characters count about twice a narrow one. */
function textWidth(value, size) {
  let units = 0;
  for (const ch of value) units += ch.charCodeAt(0) > 0x2e80 ? 1 : 0.58;
  return units * size;
}

function layout(nodes) {
  const others = nodes.filter((node) => !node.centre);
  const radius = Math.max(150, Math.min(340, others.length * 22));
  const height = Math.max(260, 2 * radius + 2 * NODE_H + 40);
  const cx = WIDTH / 2;
  const cy = height / 2;
  const place = new Map();
  for (const node of nodes) {
    if (node.centre) place.set(node.id, { x: cx, y: cy });
  }
  others.forEach((node, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(1, others.length);
    // an ellipse: the box is wider than it is tall
    place.set(node.id, {
      x: cx + Math.cos(angle) * Math.min(radius * 1.45, WIDTH / 2 - 70),
      y: cy + Math.sin(angle) * radius,
    });
  });
  return { place, height };
}

function edgeTitle(edge, names) {
  const kind = word(RELATION_KIND_TEXT, edge.kind);
  const from = names.get(edge.from) || edge.from;
  const to = names.get(edge.to) || edge.to;
  return `${from} ${edge.name || ""} ${to}（${kind}）`;
}

/**
 * The SVG for a neighbourhood answer ({nodes, edges}); a node links to its concept view.
 */
export function drawGraph(graph) {
  const { place, height } = layout(graph.nodes);
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]));
  const svg = el("svg", {
    viewBox: `0 0 ${WIDTH} ${height}`, role: "img",
    "aria-label": `关系图：${graph.nodes.length} 个概念，${graph.edges.length} 条关系`,
  });
  svg.append(el("defs", {},
    el("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7,
      markerHeight: 7, orient: "auto-start-reverse" },
    el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "arrow" }))));

  const showLabels = graph.nodes.length <= EDGE_LABELS_UP_TO;
  const pairs = new Map();
  const edges = el("g", {});
  for (const edge of graph.edges) {
    const a = place.get(edge.from);
    const b = place.get(edge.to);
    if (!a || !b) continue;
    const key = [edge.from, edge.to].sort().join("\u0000");
    const seen = pairs.get(key) || 0;
    pairs.set(key, seen + 1);
    const joinedClass = (edge.joins && edge.joins.count) || (edge.keys && edge.keys.length)
      ? " joined" : "";
    const cls = "edge" + (edge.kind === "role" ? " role" : "") + joinedClass;
    let path;
    let label;
    if (edge.from === edge.to) {
      const lift = 34 + seen * 14;
      path = `M ${a.x - 14} ${a.y - NODE_H / 2} C ${a.x - 40} ${a.y - NODE_H / 2 - lift}, ` +
        `${a.x + 40} ${a.y - NODE_H / 2 - lift}, ${a.x + 14} ${a.y - NODE_H / 2}`;
      label = { x: a.x, y: a.y - NODE_H / 2 - lift * 0.75 };
    } else {
      // a curve bending further for each further relation between the same two concepts
      const bend = seen === 0 ? 0 : (seen % 2 ? 1 : -1) * Math.ceil(seen / 2) * 28;
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const length = Math.hypot(dx, dy) || 1;
      const qx = mx - (dy / length) * bend;
      const qy = my + (dx / length) * bend;
      // stop at the target box's edge so the arrow head shows
      const end = boxEdge(qx, qy, b, names.get(edge.to));
      path = `M ${a.x} ${a.y} Q ${qx} ${qy} ${end.x} ${end.y}`;
      label = { x: (mx + qx) / 2, y: (my + qy) / 2 - 4 };
    }
    const line = el("path", { d: path, class: cls });
    if (edge.kind !== "role") line.setAttribute("marker-end", "url(#arrow)");
    const group = el("g", {}, el("title", {}, edgeTitle(edge, names)), line);
    if (showLabels && edge.name) {
      group.append(el("text", { x: label.x, y: label.y, class: "edge-label", "text-anchor": "middle" },
        clip(edge.kind === "role" ? "角色" : edge.name, EDGE_LABEL_CHARS)));
    }
    edges.append(group);
  }
  svg.append(edges);

  const nodes = el("g", {});
  for (const node of graph.nodes) {
    const at = place.get(node.id);
    const label = clip(node.name, LABEL_CHARS);
    const sub = `${word(KIND_TEXT, node.kind)} · ${node.tables} 张表`;
    const width = Math.max(textWidth(label, 13), textWidth(sub, 10)) + 22;
    const anchor = el("a", { href: href("concept", node.id) },
      el("title", {}, `${node.name}（${node.id}）`),
      el("rect", { x: at.x - width / 2, y: at.y - NODE_H / 2, width, height: NODE_H, rx: 6 }),
      el("text", { x: at.x, y: at.y - 3, "text-anchor": "middle" }, label),
      el("text", { x: at.x, y: at.y + 12, "text-anchor": "middle", class: "sub" }, sub));
    nodes.append(el("g", { class: node.centre ? "node centre" : "node" }, anchor));
  }
  svg.append(nodes);
  return svg;
}

/** Where a line from (fx, fy) towards a node's centre meets the node's box. */
function boxEdge(fx, fy, at, name) {
  const half = (Math.max(textWidth(clip(name, LABEL_CHARS), 13), 60) + 22) / 2;
  const dx = at.x - fx;
  const dy = at.y - fy;
  const scale = Math.min(
    Math.abs(dx) > 0.01 ? half / Math.abs(dx) : Infinity,
    Math.abs(dy) > 0.01 ? (NODE_H / 2) / Math.abs(dy) : Infinity,
  );
  if (!isFinite(scale) || scale >= 1) return at;
  return { x: at.x - dx * scale, y: at.y - dy * scale };
}
