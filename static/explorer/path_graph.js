(function () {
  function select(parent, selector) {
    if (window.d3) {
      return window.d3.select(parent).select(selector);
    }
    return parent.querySelector(selector);
  }

  function append(parent, name, className) {
    if (window.d3 && parent.append) {
      const node = parent.append(name);
      if (className) {
        node.attr("class", className);
      }
      return node;
    }
    const namespace = name === "svg" || parent.namespaceURI
      ? "http://www.w3.org/2000/svg"
      : "http://www.w3.org/1999/xhtml";
    const node = document.createElementNS(namespace, name);
    if (className) {
      node.setAttribute("class", className);
    }
    parent.appendChild(node);
    return node;
  }

  function attr(node, name, value) {
    if (window.d3 && node.attr) {
      node.attr(name, value);
      return node;
    }
    node.setAttribute(name, value);
    return node;
  }

  function text(node, value) {
    if (window.d3 && node.text) {
      node.text(value);
      return node;
    }
    node.textContent = value;
    return node;
  }

  function draw() {
    const dataElement = document.getElementById("path-graph-data");
    const mount = document.querySelector("[data-path-graph]");
    if (!dataElement || !mount) {
      return;
    }

    const data = JSON.parse(dataElement.textContent);
    const stage = select(mount, ".path-graphic-stage");
    const root = window.d3 ? stage : stage;
    if (window.d3) {
      stage.selectAll("*").remove();
    } else {
      stage.textContent = "";
    }

    const svg = append(root, "svg", "path-graphic-svg");
    attr(svg, "viewBox", `0 0 ${data.width} ${data.height}`);
    attr(svg, "role", "img");
    attr(svg, "aria-labelledby", "path-graphic-title");

    const defs = append(svg, "defs");
    const title = append(svg, "title");
    attr(title, "id", "path-graphic-title");
    text(title, "Podcast network path");

    const glow = append(defs, "filter");
    attr(glow, "id", "path-node-glow");
    attr(glow, "x", "-45%");
    attr(glow, "y", "-45%");
    attr(glow, "width", "190%");
    attr(glow, "height", "190%");
    attr(append(glow, "feDropShadow"), "dx", "0");
    attr(glow.lastChild || glow.node().lastChild, "dy", "12");
    attr(glow.lastChild || glow.node().lastChild, "stdDeviation", "10");
    attr(glow.lastChild || glow.node().lastChild, "flood-color", "#22d3ee");
    attr(glow.lastChild || glow.node().lastChild, "flood-opacity", "0.28");

    const arrow = append(defs, "marker");
    attr(arrow, "id", "path-edge-arrow");
    attr(arrow, "viewBox", "0 0 12 12");
    attr(arrow, "refX", "10");
    attr(arrow, "refY", "6");
    attr(arrow, "markerWidth", "8");
    attr(arrow, "markerHeight", "8");
    attr(arrow, "orient", "auto-start-reverse");
    attr(append(arrow, "path"), "d", "M 1 1 L 11 6 L 1 11 z");

    attr(append(svg, "rect", "path-graphic-bg"), "width", data.width);
    attr(svg.select ? svg.select(".path-graphic-bg") : svg.querySelector(".path-graphic-bg"), "height", data.height);

    const edgeLayer = append(svg, "g", "path-graphic-edge-layer");
    const nodeLayer = append(svg, "g", "path-graphic-node-layer");

    data.edges.forEach((edge, index) => {
      const group = append(edgeLayer, "g", "path-graphic-edge-group");
      attr(group, "style", `--edge-index: ${index}`);
      attr(append(group, "path", "path-graphic-edge-halo"), "d", edge.path_d);
      const line = append(group, "path", "path-graphic-edge");
      attr(line, "d", edge.path_d);
      attr(line, "marker-end", "url(#path-edge-arrow)");

      const label = append(group, "text", "path-graphic-edge-label");
      attr(label, "x", edge.label_x);
      attr(label, "y", edge.label_y);
      text(append(label, "tspan"), edge.label);
      if (edge.date_label) {
        const date = append(label, "tspan", "path-graphic-edge-date");
        attr(date, "x", edge.label_x);
        attr(date, "dy", "15");
        text(date, edge.date_label);
      }
    });

    data.nodes.forEach((node, index) => {
      const group = append(nodeLayer, "g", `path-graphic-node path-graphic-node-${node.kind}`);
      attr(group, "transform", `translate(${node.x} ${node.y})`);
      attr(group, "style", `--node-index: ${index}`);

      if (node.kind === "person") {
        attr(append(group, "circle", "path-graphic-node-aura"), "r", "48");
        attr(append(group, "circle", "path-graphic-node-shape"), "r", "38");
      } else {
        attr(append(group, "rect", "path-graphic-node-aura"), "x", "-70");
        attr(group.select ? group.select(".path-graphic-node-aura") : group.querySelector(".path-graphic-node-aura"), "y", "-39");
        attr(group.select ? group.select(".path-graphic-node-aura") : group.querySelector(".path-graphic-node-aura"), "width", "140");
        attr(group.select ? group.select(".path-graphic-node-aura") : group.querySelector(".path-graphic-node-aura"), "height", "78");
        attr(group.select ? group.select(".path-graphic-node-aura") : group.querySelector(".path-graphic-node-aura"), "rx", "14");
        attr(append(group, "rect", "path-graphic-node-shape"), "x", "-62");
        attr(group.select ? group.select(".path-graphic-node-shape") : group.querySelector(".path-graphic-node-shape"), "y", "-32");
        attr(group.select ? group.select(".path-graphic-node-shape") : group.querySelector(".path-graphic-node-shape"), "width", "124");
        attr(group.select ? group.select(".path-graphic-node-shape") : group.querySelector(".path-graphic-node-shape"), "height", "64");
        attr(group.select ? group.select(".path-graphic-node-shape") : group.querySelector(".path-graphic-node-shape"), "rx", "10");
      }

      if (index === 0 || index === data.nodes.length - 1) {
        const badge = append(group, "text", "path-graphic-node-badge");
        attr(badge, "x", "0");
        attr(badge, "y", node.kind === "person" ? "56" : "52");
        text(badge, index === 0 ? "START" : "END");
      }

      const label = append(group, "text", "path-graphic-node-label");
      node.label_lines.forEach((line, lineIndex) => {
        const tspan = append(label, "tspan");
        attr(tspan, "x", "0");
        attr(tspan, "dy", lineIndex === 0 ? "-4" : "16");
        text(tspan, line);
      });
    });

    mount.classList.add("path-graphic-ready");
    animateEdges(mount);
  }

  function animateEdges(mount) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    mount.querySelectorAll(".path-graphic-edge").forEach((edge) => {
      const length = edge.getTotalLength();
      edge.style.strokeDasharray = length;
      edge.style.strokeDashoffset = length;
      edge.getBoundingClientRect();
      edge.style.strokeDashoffset = "0";
    });
  }

  document.addEventListener("DOMContentLoaded", draw);
})();
