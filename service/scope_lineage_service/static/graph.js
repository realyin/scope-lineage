// The relations graph of one concept's neighbourhood, drawn as SVG by hand: the concept in
// the middle, its neighbours on a ring, and one line for each pair of drawn concepts that
// are related (a loop for a concept related to itself). The relations between one pair
// share that line and one label, a line per relation, so a concept with many relations
// to the same neighbour does not stack curves and labels on top of each other.
//
// ``layoutGraph`` is a pure function (no DOM) so its geometry can be checked; ``drawGraph``
// turns its result into SVG. Labels are text nodes; nothing is markup.
//
// Labels: a relation is labelled with its name. A participation (an event's participant,
// derived by ``catalog build`` from the event's ``participants``) has as its name the
// participant's ``role_name``, an identifier the catalog author wrote, not a reading: its
// label is the word the command line prints for it, 「参与者」, with how many roles when the
// event has several participants of the same concept; each role name stays in the line's
// tooltip and in the table under the graph. A role is labelled 「角色」.
//
// Limits: every neighbour is placed on the ring however many there are (the ring widens
// until no two boxes touch; a wide drawing scrolls inside its box). Labels are drawn while
// the graph has at most EDGE_LABELS_UP_TO concepts; each is placed by searching outward
// from the middle of its line for a spot that meets no concept and no other label, so two
// labels never overlap. Past that many concepts the lines carry no labels and the page
// says so: the table under the graph lists every relation.

import { KIND_TEXT, RELATION_KIND_TEXT, href, word } from "./dom.js";

const SVG = "http://www.w3.org/2000/svg";
const NODE_H = 40;
const NODE_FONT = 14;
const SUB_FONT = 11;
const LABEL_FONT = 12;
const LABEL_LINE = 16;
const LABEL_CHARS = 12; // a concept's name in its box; the box's tooltip has it whole
const EDGE_LINE_CHARS = 18; // one line of an edge label; the label's tooltip has it whole
const EDGE_LINES = 4; // lines of one edge label; past that the last says how many more
export const EDGE_LABELS_UP_TO = 24; // concepts; with more, the table carries the names
const PAD = 16;
const LEADER_FROM = 26; // a label further than this from its line gets a leader line

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

function inside(b, point, margin = 0) {
  return point.x >= b.x - margin && point.x <= b.x + b.w + margin &&
    point.y >= b.y - margin && point.y <= b.y + b.h + margin;
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
  let ry = Math.max(110, Math.min(320, n * 26));
  let rx = Math.max(n > 1 ? 230 : 0, Math.min(460, ry * 1.6));
  const start = -Math.PI / 2 + (n > 0 ? Math.PI / n : 0); // two neighbours: left and right
  const placed = new Map();
  for (const node of graph.nodes) {
    const label = clip(node.name, LABEL_CHARS);
    const sub = `${word(KIND_TEXT, node.kind)} · ${node.tables} 张表`;
    const w = Math.max(textWidth(label, NODE_FONT), textWidth(sub, SUB_FONT)) + 24;
    placed.set(node.id, { id: node.id, name: node.name, centre: !!node.centre, x: 0, y: 0, w, h: NODE_H, label, sub });
  }
  const ring = [...placed.values()].filter((node) => !node.centre);
  // widen the ring until no two boxes come close (a crowded neighbourhood draws larger,
  // and the box scrolls it); room between them is room for the labels
  for (let attempt = 0; attempt < 60; attempt += 1) {
    ring.forEach((node, index) => {
      const angle = start + (2 * Math.PI * index) / Math.max(1, n);
      node.x = Math.cos(angle) * rx;
      node.y = Math.sin(angle) * (n === 1 ? 130 : ry);
    });
    const boxes = [...placed.values()].map((node) => box(node.x, node.y, node.w, node.h));
    const crowded = boxes.some((a, i) => boxes.slice(i + 1).some((b) => overlaps(a, b, 24)));
    if (!crowded) break;
    rx *= 1.1;
    ry *= 1.1;
  }
  return placed;
}

/** The text of one relation on its line's label. */
export function relationLabel(edge) {
  if (edge.kind === "role") return "角色";
  if (edge.kind === "participation") return "参与者";
  return String(edge.name || word(RELATION_KIND_TEXT, edge.kind));
}

/** The lines of one label for the relations of one pair: participations to the same
 * concept as one line with how many roles, the others one line each, in document order. */
export function bundleLines(edges) {
  const lines = [];
  const participants = new Map();
  for (const edge of edges) {
    if (edge.kind === "participation") {
      const key = `${edge.from}\u0000${edge.to}`;
      if (!participants.has(key)) {
        participants.set(key, { count: 0 });
        lines.push(participants.get(key));
      }
      participants.get(key).count += 1;
    } else {
      lines.push(relationLabel(edge));
    }
  }
  const texts = lines.map((line) => (typeof line === "string" ? line
    : line.count > 1 ? `参与者（${line.count} 个角色）` : "参与者"));
  const shown = texts.length > EDGE_LINES
    ? [...texts.slice(0, EDGE_LINES - 1), `等 ${texts.length} 条关系`] : texts;
  return { lines: shown.map((line) => clip(line, EDGE_LINE_CHARS)), full: texts };
}

/** Points along a path given as {from, control, to} (a quadratic curve), for the checks. */
function samples(curve, count = 14) {
  const out = [];
  for (let k = 1; k < count; k += 1) {
    const t = k / count;
    const u = 1 - t;
    out.push({
      x: u * u * curve.from.x + 2 * u * t * curve.control.x + t * t * curve.to.x,
      y: u * u * curve.from.y + 2 * u * t * curve.control.y + t * t * curve.to.y,
    });
  }
  return out;
}

/**
 * The geometry of a neighbourhood answer: {width, height, viewBox, nodes, edges, labelled}.
 * ``edges`` has one entry per pair of related concepts: ``indexes`` (the relations it
 * draws, into ``graph.edges``), ``path``, ``mid``, ``forward`` / ``backward`` (whether a
 * relation runs from the first end to the second, or back), and, when labels are shown,
 * ``label`` {x, y, w, h, cx, cy, lines, full, leader}.
 */
export function layoutGraph(graph) {
  const placed = placeNodes(graph);
  const nodeBoxes = [...placed.values()].map((node) => box(node.x, node.y, node.w, node.h));
  const labelled = graph.nodes.length <= EDGE_LABELS_UP_TO;
  const bundles = new Map();
  graph.edges.forEach((edge, index) => {
    if (!placed.has(edge.from) || !placed.has(edge.to)) return;
    const [p, q] = edge.from <= edge.to ? [edge.from, edge.to] : [edge.to, edge.from];
    const key = `${p}\u0000${q}`;
    if (!bundles.has(key)) bundles.set(key, { p, q, indexes: [] });
    bundles.get(key).indexes.push(index);
  });
  const edges = [];
  const curves = [];
  const extents = [];
  for (const bundle of bundles.values()) {
    const a = placed.get(bundle.p);
    const b = placed.get(bundle.q);
    const members = bundle.indexes.map((i) => graph.edges[i]);
    let path;
    let mid;
    let curve = null;
    if (a === b) {
      const top = a.y - a.h / 2;
      path = `M ${a.x - 16} ${top} C ${a.x - 46} ${top - 44}, ${a.x + 46} ${top - 44}, ${a.x + 16} ${top}`;
      mid = { x: a.x, y: top - 33 };
      extents.push(box(a.x, top - 33, 70, 2));
    } else {
      // a line between two neighbours bends away from the centre, so it does not cross
      // the concept in the middle; a line from the centre runs straight
      let control = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      if (!a.centre && !b.centre) {
        const length = Math.hypot(control.x, control.y);
        const reach = Math.max(80, Math.hypot(b.x - a.x, b.y - a.y) * 0.3);
        const out = length > 1 ? { x: control.x / length, y: control.y / length }
          : { x: -(b.y - a.y), y: b.x - a.x };
        const norm = Math.hypot(out.x, out.y) || 1;
        control = { x: control.x + (out.x / norm) * reach, y: control.y + (out.y / norm) * reach };
      }
      const from = boxEdge(control, a);
      const to = boxEdge(control, b);
      curve = { from, control, to };
      path = `M ${from.x} ${from.y} Q ${control.x} ${control.y} ${to.x} ${to.y}`;
      mid = { x: 0.25 * from.x + 0.5 * control.x + 0.25 * to.x, y: 0.25 * from.y + 0.5 * control.y + 0.25 * to.y };
      curves.push({ bundle: edges.length, points: samples(curve) });
    }
    edges.push({
      indexes: bundle.indexes, from: bundle.p, to: bundle.q, path, mid,
      forward: members.some((e) => e.kind !== "role" && e.from === bundle.p && e.to === bundle.q),
      backward: members.some((e) => e.kind !== "role" && e.from === bundle.q && e.to === bundle.p),
      role: members.every((e) => e.kind === "role"),
      joined: members.some((e) => Boolean((e.joins && e.joins.count) || (e.keys && e.keys.length))),
      label: null,
    });
  }
  const labels = [];
  if (labelled) {
    edges.forEach((edge, index) => {
      const { lines, full } = bundleLines(edge.indexes.map((i) => graph.edges[i]));
      const others = curves.filter((curve) => curve.bundle !== index).flatMap((curve) => curve.points);
      edge.label = placeLabel(lines, full, edge.mid, nodeBoxes, labels, others);
      labels.push(edge.label);
    });
  }
  const leaders = labels.filter((label) => label.leader)
    .map((label) => box(label.leader.x, label.leader.y, 1, 1));
  const all = [...nodeBoxes, ...labels, ...extents, ...leaders];
  const minX = Math.min(...all.map((b) => b.x)) - PAD;
  const minY = Math.min(...all.map((b) => b.y)) - PAD;
  const maxX = Math.max(...all.map((b) => b.x + b.w)) + PAD;
  const maxY = Math.max(...all.map((b) => b.y + b.h)) + PAD;
  const width = Math.ceil(maxX - minX);
  const height = Math.ceil(maxY - minY);
  return {
    width, height, viewBox: `${Math.floor(minX)} ${Math.floor(minY)} ${width} ${height}`,
    nodes: [...placed.values()], edges, labelled,
  };
}

/**
 * A label's box: on its own line's middle when that spot is free, else the nearest free
 * spot found walking outward in rings. A spot is free when the box meets no concept and
 * no label already placed; within the first rings it must also keep off the other lines.
 * The walk goes on until it finds one: past every box drawn, every spot is free, so a
 * label is always placed and never on another.
 */
function placeLabel(lines, full, mid, nodeBoxes, labels, otherPoints) {
  const w = Math.max(...lines.map((line) => textWidth(line, LABEL_FONT))) + 10;
  const h = lines.length * LABEL_LINE + 4;
  const free = (candidate, strict) => {
    if (nodeBoxes.some((b) => overlaps(candidate, b, 4))) return false;
    if (labels.some((b) => overlaps(candidate, b, 3))) return false;
    return !strict || !otherPoints.some((point) => inside(candidate, point, 2));
  };
  const at = (radius, step, steps) => {
    const angle = (2 * Math.PI * step) / steps;
    const x = mid.x + Math.cos(angle) * radius;
    const y = mid.y + Math.sin(angle) * radius;
    return { ...box(x, y, w, h), cx: x, cy: y };
  };
  let found = null;
  for (const strict of [true, false]) {
    for (let ring = 0; !found && ring < (strict ? 12 : 4000); ring += 1) {
      const radius = ring * 10;
      const steps = ring === 0 ? 1 : Math.max(8, Math.round((2 * Math.PI * radius) / 18));
      for (let step = 0; step < steps; step += 1) {
        const candidate = at(radius, step, steps);
        if (free(candidate, strict)) {
          found = candidate;
          break;
        }
      }
    }
    if (found) break;
  }
  const label = { ...found, lines, full, leader: null };
  if (Math.hypot(label.cx - mid.x, label.cy - mid.y) > LEADER_FROM) {
    label.leader = { x: mid.x, y: mid.y };
  }
  return label;
}

function el(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, String(value));
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** One relation in words, for a tooltip: participations name their role. */
export function relationTitle(edge, names) {
  const from = names.get(edge.from) || edge.from;
  const to = names.get(edge.to) || edge.to;
  if (edge.kind === "role") return `${from} 是 ${to} 承担的角色${edge.name ? `（${edge.name}）` : ""}`;
  if (edge.kind === "participation") return `${from} 的参与者：${to}（角色名 ${edge.name || "—"}）`;
  const kind = word(RELATION_KIND_TEXT, edge.kind);
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
  for (const placed of layout.edges) {
    const title = placed.indexes.map((i) => relationTitle(graph.edges[i], names)).join("\n");
    const cls = "edge" + (placed.role ? " role" : "") + (placed.joined ? " joined" : "");
    const line = el("path", { d: placed.path, class: cls });
    if (placed.forward) line.setAttribute("marker-end", "url(#arrow)");
    if (placed.backward) line.setAttribute("marker-start", "url(#arrow)");
    lines.append(el("g", {}, el("title", {}, title), line));
    const label = placed.label;
    if (!label) continue;
    const group = el("g", { class: "edge-label" }, el("title", {}, title));
    if (label.leader) {
      group.append(el("line", { x1: label.leader.x, y1: label.leader.y, x2: label.cx, y2: label.cy, class: "leader" }));
    }
    group.append(el("rect", { x: label.x, y: label.y, width: label.w, height: label.h, rx: 3 }));
    label.lines.forEach((text, i) => {
      group.append(el("text", { x: label.cx, y: label.y + 2 + LABEL_LINE * (i + 1) - 4, "text-anchor": "middle" }, text));
    });
    labels.append(group);
  }
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
