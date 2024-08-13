import * as d3 from "d3";
import fs from "fs";
import { JSDOM } from "jsdom";

// Function to calculate the intersection point on the edge of the box
function findBoxEdgeIntersection(sourceBox, targetBox, offset = 5) {
  const x_c = sourceBox.x + sourceBox.width / 2;
  const y_c = sourceBox.y + sourceBox.height / 2;
  const w = sourceBox.width;
  const h = sourceBox.height;
  const dx = targetBox.x + targetBox.width / 2 - x_c;
  const dy = targetBox.y + targetBox.height / 2 - y_c;

  let t_left = -w / 2 / dx;
  let t_right = w / 2 / dx;
  let t_top = -h / 2 / dy;
  let t_bottom = h / 2 / dy;

  let y_left = y_c + t_left * dy;
  let y_right = y_c + t_right * dy;
  let x_top = x_c + t_top * dx;
  let x_bottom = x_c + t_bottom * dx;

  let intersections = [];

  if (y_left >= y_c - h / 2 && y_left <= y_c + h / 2) {
    intersections.push({ x: x_c - w / 2, y: y_left, t: t_left });
  }
  if (y_right >= y_c - h / 2 && y_right <= y_c + h / 2) {
    intersections.push({ x: x_c + w / 2, y: y_right, t: t_right });
  }
  if (x_top >= x_c - w / 2 && x_top <= x_c + w / 2) {
    intersections.push({ x: x_top, y: y_c - h / 2, t: t_top });
  }
  if (x_bottom >= x_c - w / 2 && x_bottom <= x_c + w / 2) {
    intersections.push({ x: x_bottom, y: y_c + h / 2, t: t_bottom });
  }

  let closestIntersection = { x: Infinity, y: Infinity, t: Infinity };

  intersections.forEach((intersection) => {
    if (intersection.t >= 0 && intersection.t < closestIntersection.t) {
      closestIntersection = intersection;
    }
  });

  if (closestIntersection.t === Infinity) {
    intersections.forEach((intersection) => {
      if (intersection.t >= 0 && intersection.t < closestIntersection.t) {
        closestIntersection = intersection;
      }
    });
  }

  let dxi = closestIntersection.x - x_c;
  let dyi = closestIntersection.y - y_c;
  let l = Math.sqrt(dxi ** 2 + dyi ** 2);

  let uxi = dxi / l;
  let uyi = dyi / l;

  let ex = offset * uxi;
  let ey = offset * uyi;

  return { x: closestIntersection.x + ex, y: closestIntersection.y + ey };
}

function calculateAngle(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const angleRadians = Math.atan2(dy, dx);
  return angleRadians;
}

function calculateAngleInDegrees(sourceBox, targetBox) {
  let x1 = sourceBox.x + sourceBox.width / 2;
  let y1 = sourceBox.y + sourceBox.height / 2;
  let x2 = targetBox.x + targetBox.width / 2;
  let y2 = targetBox.y + targetBox.height / 2;

  const angleRadians = calculateAngle(x1, y1, x2, y2);
  const angleDegrees = angleRadians * (180 / Math.PI);
  return angleDegrees;
}

function isWithin45DegreesFromHorizontal(sourceBox, targetBox) {
  const angleDegrees = calculateAngleInDegrees(sourceBox, targetBox);
  return (
    (angleDegrees >= -45 && angleDegrees <= 45) ||
    (angleDegrees >= 135 && angleDegrees <= 225)
  );
}

function createUmlDiagram(svg, boxesData, linksData) {
  svg.selectAll("*").remove();

  const zoom = d3.zoom().scaleExtent([0.5, 10]).on("zoom", zoomed);

  const zoomGroup = svg.append("g").attr("class", "zoom-group");

  svg.call(zoom);

  function zoomed(event) {
    zoomGroup.attr("transform", event.transform);
  }

  const boxMap = {};
  boxesData.forEach((d) => (boxMap[d.id] = d));

  const missingBoxes = new Set();
  linksData.forEach((d) => {
    if (!boxMap[d.source]) {
      missingBoxes.add(d.source);
    }
    if (!boxMap[d.target]) {
      missingBoxes.add(d.target);
    }
  });

  if (missingBoxes.size > 0) {
    console.error(
      "The following box IDs are missing in boxesData:",
      Array.from(missingBoxes)
    );
  }

  zoomGroup
    .append("defs")
    .append("marker")
    .attr("id", "arrowhead")
    .attr("viewBox", "-0 -5 10 10")
    .attr("refX", 5)
    .attr("refY", 0)
    .attr("orient", "auto")
    .attr("markerWidth", 10)
    .attr("markerHeight", 10)
    .attr("xoverflow", "visible")
    .append("svg:path")
    .attr("d", "M 0,-5 L 10 ,0 L 0,5")
    .attr("fill", "black")
    .style("stroke", "none");

  const links = zoomGroup
    .selectAll(".link")
    .data(linksData)
    .enter()
    .append("line")
    .attr("class", "link")
    .attr("x1", (d) => boxMap[d.source].x + boxMap[d.source].width / 2)
    .attr("y1", (d) => boxMap[d.source].y + boxMap[d.source].height / 2)
    .attr("x2", (d) => boxMap[d.target].x + boxMap[d.target].width / 2)
    .attr("y2", (d) => boxMap[d.target].y + boxMap[d.target].height / 2)
    .attr("stroke", (d) => d.color || "black")
    .attr("stroke-width", 3)
    .attr("marker-end", (d) =>
      d.type === "generalization" ? "url(#arrowhead)" : null
    );

  const arrows = zoomGroup
    .selectAll(".arrow")
    .data(linksData.filter((d) => d.type === "generalization"))
    .enter()
    .append("line")
    .attr("class", "arrow")
    .attr("x2", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source],
        10
      );
      return intersection.x;
    })
    .attr("y2", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source],
        10
      );
      return intersection.y;
    })
    .attr("x1", (d) => boxMap[d.source].x + boxMap[d.source].width / 2)
    .attr("y1", (d) => boxMap[d.source].y + boxMap[d.source].height / 2)
    .attr("stroke", (d) => d.color || "black")
    .attr("stroke-width", 2)
    .attr("marker-end", "url(#arrowhead)");

  const groups = zoomGroup
    .selectAll("g")
    .data(boxesData)
    .enter()
    .append("g")
    .attr("class", "draggable")
    .attr("transform", (d) => `translate(${d.x}, ${d.y})`)
    .call(
      d3
        .drag()
        .on("start", function (event, d) {
          d3.select(this).raise().attr("stroke", "black");
        })
        .on("drag", function (event, d) {
          d.x += event.dx;
          d.y += event.dy;
          d3.select(this).attr("transform", `translate(${d.x}, ${d.y})`);
          updateLinks();
        })
        .on("end", function (event, d) {
          d3.select(this).attr("stroke", null);
        })
    );

  groups
    .append("rect")
    .attr("class", "box")
    .attr("width", (d) => d.width)
    .attr("height", (d) => d.height)
    .style("fill", (d) => d.color)
    .style("stroke", "steelblue")
    .style("stroke-width", "2px")
    .style("cursor", "move");

  groups.each(function (d) {
    const group = d3.select(this);
    const buffer = 10;
    const numLines = d.textLines.length;
    const fontSize = 10;
    const lineHeight = fontSize * 1.2;
    const textHeight = lineHeight * numLines + buffer;
    let currentY = (d.height - textHeight) / 2 + lineHeight / 2;

    d.textLines.forEach((line, index) => {
      const textElement = group
        .append("text")
        .attr("class", "text")
        .attr("x", d.width / 2)
        .attr("y", currentY)
        .attr("dy", ".35em")
        .attr("text-anchor", "middle")
        .style("font-family", "Arial, sans-serif")
        .style("fill", "black")
        .style("font-size", `${fontSize}px`)
        .style("pointer-events", "none")
        .text(line.text);

      currentY += lineHeight;

      if (line.type === "title") {
        const hasTextAfterTitle = d.textLines.length > index + 1;

        if (hasTextAfterTitle) {
          currentY += buffer;
          group
            .append("line")
            .attr("x1", 0)
            .attr("x2", d.width)
            .attr("y1", currentY - buffer / 2)
            .attr("y2", currentY - buffer / 2)
            .attr("stroke", "black")
            .attr("stroke-width", 1);

          currentY += buffer;
        }
      }
    });
  });

  const linkTextOffset = 10;

  const linkTextStart = zoomGroup
    .selectAll(".link-text-start")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-start")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target],
        linkTextOffset
      );
      return intersection.x;
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target],
        linkTextOffset
      );
      return intersection.y;
    })
    .attr("transform", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target],
        linkTextOffset
      );
      const isHorizontal = isWithin45DegreesFromHorizontal(
        boxMap[d.target],
        boxMap[d.source]
      );
      const angle = isHorizontal ? 90 : 0;
      return `rotate(${angle}, ${intersection.x}, ${intersection.y})`;
    })
    .attr("text-anchor", "middle")
    .text((d) => d.textStart || "")
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "12px")
    .style("fill", "black");

  const linkTextEnd = zoomGroup
    .selectAll(".link-text-end")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-end")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source],
        linkTextOffset
      );
      return intersection.x;
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source],
        linkTextOffset
      );
      return intersection.y;
    })
    .attr("transform", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source],
        linkTextOffset
      );
      const isHorizontal = isWithin45DegreesFromHorizontal(
        boxMap[d.target],
        boxMap[d.source]
      );
      const angle = isHorizontal ? 90 : 0;
      return `rotate(${angle}, ${intersection.x}, ${intersection.y})`;
    })
    .attr("text-anchor", "middle")
    .text((d) => d.textEnd || "")
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "12px")
    .style("fill", "black");

  function updateLinks() {
    links
      .attr("x1", (d) => boxMap[d.source].x + boxMap[d.source].width / 2)
      .attr("y1", (d) => boxMap[d.source].y + boxMap[d.source].height / 2)
      .attr("x2", (d) => boxMap[d.target].x + boxMap[d.target].width / 2)
      .attr("y2", (d) => boxMap[d.target].y + boxMap[d.target].height / 2);

    arrows
      .attr("x2", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.target],
          boxMap[d.source],
          10
        );
        return intersection.x;
      })
      .attr("y2", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.target],
          boxMap[d.source],
          10
        );
        return intersection.y;
      })
      .attr("x1", (d) => boxMap[d.source].x + boxMap[d.source].width / 2)
      .attr("y1", (d) => boxMap[d.source].y + boxMap[d.source].height / 2);

    linkTextStart
      .attr("x", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.source],
          boxMap[d.target],
          linkTextOffset
        );
        return intersection.x;
      })
      .attr("y", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.source],
          boxMap[d.target],
          linkTextOffset
        );
        return intersection.y;
      })
      .attr("transform", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.source],
          boxMap[d.target],
          linkTextOffset
        );
        const isHorizontal = isWithin45DegreesFromHorizontal(
          boxMap[d.target],
          boxMap[d.source]
        );
        const angle = isHorizontal ? 90 : 0;
        return `rotate(${angle}, ${intersection.x}, ${intersection.y})`;
      });

    linkTextEnd
      .attr("x", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.target],
          boxMap[d.source],
          linkTextOffset
        );
        return intersection.x;
      })
      .attr("y", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.target],
          boxMap[d.source],
          linkTextOffset
        );
        return intersection.y;
      })
      .attr("transform", (d) => {
        const intersection = findBoxEdgeIntersection(
          boxMap[d.target],
          boxMap[d.source],
          linkTextOffset
        );
        const isHorizontal = isWithin45DegreesFromHorizontal(
          boxMap[d.target],
          boxMap[d.source]
        );
        const angle = isHorizontal ? 90 : 0;
        return `rotate(${angle}, ${intersection.x}, ${intersection.y})`;
      });
  }

  return svg.node();
}

function createStandaloneUmlSvg(data) {
  const { window } = new JSDOM(`<!DOCTYPE html><body></body>`);

  Object.defineProperty(window, "navigator", {
    value: {
      maxTouchPoints: 1,
      userAgent: "node.js",
    },
    writable: true,
  });

  const { document } = window;
  global.document = document;
  global.window = window;
  global.navigator = window.navigator;

  const svg = d3
    .select(document.body)
    .append("svg")
    .attr("width", data.cx)
    .attr("height", data.cy)
    .attr("xmlns", "http://www.w3.org/2000/svg");

  const svgElement = createUmlDiagram(svg, data.nodes, data.links);

  const serializer = new window.XMLSerializer();
  const svgString = serializer.serializeToString(svgElement);

  const fullSvgString = `<?xml version="1.0" encoding="UTF-8"?>\n${svgString}`;

  if ("outputPath" in data) {
    fs.writeFileSync(data.outputPath, fullSvgString, "utf-8");
  } else {
    console.log(fullSvgString);
  }
}

const args = process.argv.slice(2);
const jsonString = args[0];

const jsObject = JSON.parse(jsonString);

createStandaloneUmlSvg(jsObject);
