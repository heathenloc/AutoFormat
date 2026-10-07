(() => {
  "use strict";
  const graph = document.querySelector(".workflow-graph");
  if (!graph) return;
  const svg = graph.querySelector(".workflow-connections");
  const paths = graph.querySelector(".workflow-paths");
  const nodes = new Map([...graph.querySelectorAll("[data-wf-node]")].map(node => [node.dataset.wfNode, node]));
  const edges = [
    ["U", "A", "main"], ["A", "B", "main"], ["B", "Q", "main"],
    ["Q", "C", "confirm"], ["C", "D", "confirm"], ["D", "Q", "confirm"],
    ["Q", "E", "main"], ["E", "F", "main"], ["F", "G", "main"],
    ["G", "H", "main"], ["G", "I", "main"], ["I", "J", "refine"], ["J", "E", "refine"],
  ];
  const edgePaths = edges.map(([from, to, kind], index) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", `wf-edge wf-edge-${kind}`);
    path.setAttribute("data-edge", `${from}-${to}`);
    path.setAttribute("marker-end", `url(#wf-arrow-${kind})`);
    path.setAttribute("pathLength", "1");
    path.style.setProperty("--edge-delay", `${index * 55}ms`);
    paths.append(path);
    return path;
  });
  nodes.forEach((node, key) => node.style.setProperty("--node-delay", `${["U", "A", "B", "Q", "C", "D", "E", "F", "G", "H", "I", "J"].indexOf(key) * 65}ms`));
  let queued = false;

  function roundedPath(points) {
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 1; i < points.length - 1; i++) {
      const a = points[i - 1], b = points[i], c = points[i + 1];
      const incoming = Math.hypot(b.x - a.x, b.y - a.y);
      const outgoing = Math.hypot(c.x - b.x, c.y - b.y);
      const r = Math.min(9, incoming / 2, outgoing / 2);
      if (!r) { d += ` L ${b.x} ${b.y}`; continue; }
      const before = { x: b.x - (b.x - a.x) * r / incoming, y: b.y - (b.y - a.y) * r / incoming };
      const after = { x: b.x + (c.x - b.x) * r / outgoing, y: b.y + (c.y - b.y) * r / outgoing };
      d += ` L ${before.x} ${before.y} Q ${b.x} ${b.y} ${after.x} ${after.y}`;
    }
    const last = points.at(-1);
    return `${d} L ${last.x} ${last.y}`;
  }

  function draw() {
    queued = false;
    const origin = graph.getBoundingClientRect();
    const rect = element => {
      const r = element.getBoundingClientRect();
      return { left: r.left - origin.left, right: r.right - origin.left, top: r.top - origin.top, bottom: r.bottom - origin.top, x: r.left - origin.left + r.width / 2, y: r.top - origin.top + r.height / 2 };
    };
    const n = Object.fromEntries([...nodes].map(([key, node]) => [key, rect(node)]));
    const parsing = rect(graph.querySelector(".wf-parsing"));
    const editing = rect(graph.querySelector(".wf-editing"));
    const preview = rect(graph.querySelector(".wf-preview"));
    const vertical = matchMedia("(max-width: 1040px)").matches;
    const point = (x, y) => ({ x, y });
    const top = node => point(node.x, node.top);
    const bottom = node => point(node.x, node.bottom);
    const left = node => point(node.left, node.y);
    const right = node => point(node.right, node.y);
    const route = {};
    route["U-A"] = [bottom(n.U), point(n.U.x, parsing.top - 14), point(parsing.left + 9, parsing.top - 14), point(parsing.left + 9, n.A.y), left(n.A)];
    route["A-B"] = [bottom(n.A), top(n.B)];
    route["B-Q"] = [bottom(n.B), top(n.Q)];
    route["C-D"] = [bottom(n.C), top(n.D)];
    route["E-F"] = [bottom(n.E), top(n.F)];
    route["I-J"] = [bottom(n.I), top(n.J)];
    const labels = {};
    if (vertical) {
      route["Q-C"] = [bottom(n.Q), top(n.C)];
      route["D-Q"] = [bottom(n.D), point(n.D.x, n.D.bottom + 17), point(parsing.right - 9, n.D.bottom + 17), point(parsing.right - 9, n.Q.y), right(n.Q)];
      route["Q-E"] = [left(n.Q), point(parsing.left + 9, n.Q.y), point(parsing.left + 9, editing.top - 16), point(n.E.x, editing.top - 16), top(n.E)];
      route["F-G"] = [bottom(n.F), point(n.F.x, preview.top - 16), point(preview.left + 9, preview.top - 16), point(preview.left + 9, n.G.y), left(n.G)];
      route["G-H"] = [bottom(n.G), top(n.H)];
      route["G-I"] = [right(n.G), point(preview.right - 9, n.G.y), point(preview.right - 9, n.I.y), right(n.I)];
      route["J-E"] = [bottom(n.J), point(n.J.x, preview.bottom + 20), point(origin.width - 3, preview.bottom + 20), point(origin.width - 3, n.E.y), right(n.E)];
      labels["Q-C"] = point(n.Q.x, (n.Q.bottom + n.C.top) / 2);
      labels["Q-E"] = point((parsing.left + 9 + n.E.x) / 2, editing.top - 16);
      labels["D-Q"] = point((n.D.x + parsing.right - 9) / 2, n.D.bottom + 17);
      labels["J-E"] = point((n.J.x + origin.width - 3) / 2, preview.bottom + 20);
    } else {
      const firstGap = (parsing.right + editing.left) / 2;
      const secondGap = (editing.right + preview.left) / 2;
      const noQuestionsY = (Math.max(n.Q.bottom, n.C.bottom) + n.D.top) / 2;
      route["Q-C"] = [right(n.Q), left(n.C)];
      route["D-Q"] = [bottom(n.D), point(n.D.x, n.D.bottom + 17), point(parsing.left + 9, n.D.bottom + 17), point(parsing.left + 9, n.Q.y), left(n.Q)];
      route["Q-E"] = [bottom(n.Q), point(n.Q.x, noQuestionsY), point(firstGap, noQuestionsY), point(firstGap, n.E.y), left(n.E)];
      route["F-G"] = [right(n.F), point(secondGap - 4, n.F.y), point(secondGap - 4, n.G.y), left(n.G)];
      const fork = (n.G.bottom + Math.min(n.H.top, n.I.top)) / 2;
      route["G-H"] = [bottom(n.G), point(n.G.x, fork), point(n.H.x, fork), top(n.H)];
      route["G-I"] = [bottom(n.G), point(n.G.x, fork), point(n.I.x, fork), top(n.I)];
      route["J-E"] = [bottom(n.J), point(n.J.x, preview.bottom + 24), point(secondGap + 4, preview.bottom + 24), point(secondGap + 4, n.E.y), right(n.E)];
      labels["Q-C"] = point((n.Q.right + n.C.left) / 2, n.Q.y);
      labels["Q-E"] = point((n.Q.x + firstGap) / 2, noQuestionsY);
      labels["D-Q"] = point((n.D.x + parsing.left + 9) / 2, n.D.bottom + 17);
      labels["J-E"] = point((n.J.x + secondGap + 4) / 2, preview.bottom + 24);
    }
    svg.setAttribute("viewBox", `0 0 ${origin.width} ${origin.height}`);
    edges.forEach(([from, to], index) => edgePaths[index].setAttribute("d", roundedPath(route[`${from}-${to}`])));
    for (const [key, position] of Object.entries(labels)) {
      const label = graph.querySelector(`[data-wf-label="${key}"]`);
      label.style.left = `${position.x}px`;
      label.style.top = `${position.y}px`;
    }
  }
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(draw);
  }
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(schedule);
    observer.observe(graph);
    nodes.forEach(node => observer.observe(node));
  }
  window.addEventListener("resize", schedule, { passive: true });
  document.addEventListener("easyformat:languagechange", schedule);
  if (document.fonts) document.fonts.ready.then(schedule);
  schedule();
})();
