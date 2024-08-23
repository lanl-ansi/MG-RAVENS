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
    intersections.push({ x: x_c - w / 2, y: y_left, t: t_left, edge: 4 });
  }
  if (y_right >= y_c - h / 2 && y_right <= y_c + h / 2) {
    intersections.push({ x: x_c + w / 2, y: y_right, t: t_right, edge: 2 });
  }
  if (x_top >= x_c - w / 2 && x_top <= x_c + w / 2) {
    intersections.push({ x: x_top, y: y_c - h / 2, t: t_top, edge: 1 });
  }
  if (x_bottom >= x_c - w / 2 && x_bottom <= x_c + w / 2) {
    intersections.push({ x: x_bottom, y: y_c + h / 2, t: t_bottom, edge: 3 });
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

  return {
    x: closestIntersection.x + ex,
    y: closestIntersection.y + ey,
    edge: closestIntersection.edge,
  };
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
    .attr("transform", (d) => `translate(${d.x}, ${d.y})`);

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

    const textBox = group
      .append("text")
      .attr("x", 0)
      .attr("y", 0)
      .attr("text-anchor", "start")
      .attr("font-size", `${fontSize}px`);

    d.textLines.forEach((line, index) => {
      if (Object.keys(line).length === 0) {
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
      } else {
        const textElement = textBox
          .append("tspan")
          .attr("x", (d) => {
            if (line.align == "right") {
              return d.width - 5;
            } else if (line.align == "center") {
              return d.width / 2;
            } else {
              return 5;
            }
          })
          .attr("y", currentY)
          .attr("dy", ".35em")
          .attr("text-anchor", (d) => {
            if (line.align == "right") {
              return "end";
            } else if (line.align == "center") {
              return "middle";
            } else {
              return "start";
            }
          })
          .style("font-family", "Arial, sans-serif")
          .style("font-weight", (d) => {
            if (line.style == "bold") {
              return 700;
            } else {
              return 400;
            }
          })
          .style("font-style", (d) => {
            if (line.style == "italic") {
              return line.style;
            } else {
              return "normal";
            }
          })
          .style("fill", "black")
          .style("font-size", (d) => {
            if (line.style == "bold") {
              return `${fontSize + 2}px`;
            } else {
              return `${fontSize}px`;
            }
          })
          .style("pointer-events", "none")
          .text(line.text);

        currentY += lineHeight;
      }
    });
  });

  const linkTextOffset = 10;

  const linkTextStartTop = zoomGroup
    .selectAll(".link-text-start-top")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-start-top")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 2) {
        return intersection.x + 5;
      } else {
        return intersection.x - 5;
      }
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      return intersection.y;
    })
    .attr("text-anchor", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 2) {
        return "start";
      } else {
        return "end";
      }
    })
    .attr("dy", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 1) {
        return "-1em";
      } else if (intersection.edge == 3) {
        return "1em";
      } else {
        return "-1em";
      }
    })
    .text((d) => {
      if (d.textStartTopHidden == 0) {
        return d.textStartTop;
      } else {
        return "";
      }
    })
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "10px")
    .style("fill", "black");

  const linkTextStartBtm = zoomGroup
    .selectAll(".link-text-start-btm")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-start-btm")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 4) {
        return intersection.x - 5;
      } else {
        return intersection.x + 5;
      }
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      return intersection.y;
    })
    .attr("dy", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 1) {
        return "-1em";
      } else if (intersection.edge == 3) {
        return "1em";
      } else {
        return "1em";
      }
    })
    .attr("text-anchor", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.source],
        boxMap[d.target]
      );
      if (intersection.edge == 4) {
        return "end";
      } else {
        return "start";
      }
    })
    .text((d) => {
      if (d.textStartBtmHidden == 0) {
        return d.textStartBtm;
      } else {
        return "";
      }
    })
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "10px")
    .style("fill", "black");

  const linkTextEndTop = zoomGroup
    .selectAll(".link-text-end-top")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-end-top")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 2) {
        return intersection.x + 5;
      } else {
        return intersection.x - 5;
      }
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      return intersection.y;
    })
    .attr("dy", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 1) {
        return "-1em";
      } else if (intersection.edge == 3) {
        return "1em";
      } else {
        return "-1em";
      }
    })
    .attr("text-anchor", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 2) {
        return "start";
      } else {
        return "end";
      }
    })
    .text((d) => {
      if (d.textEndTopHidden == 0) {
        return d.textEndTop;
      } else {
        return "";
      }
    })
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "10px")
    .style("fill", "black");

  const linkTextEndBtm = zoomGroup
    .selectAll(".link-text-end-btm")
    .data(linksData)
    .enter()
    .append("text")
    .attr("class", "link-text-end-btm")
    .attr("x", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 4) {
        return intersection.x - 5;
      } else {
        return intersection.x + 5;
      }
    })
    .attr("y", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 3) {
        return intersection.y;
      } else {
        return intersection.y;
      }
    })
    .attr("dy", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 1) {
        return "-1em";
      } else if (intersection.edge == 3) {
        return "1em";
      } else {
        return "1em";
      }
    })
    .attr("text-anchor", (d) => {
      const intersection = findBoxEdgeIntersection(
        boxMap[d.target],
        boxMap[d.source]
      );
      if (intersection.edge == 4) {
        return "end";
      } else {
        return "start";
      }
    })
    .text((d) => {
      if (d.textEndBtmHidden == 0) {
        return d.textEndBtm;
      } else {
        return "";
      }
    })
    .style("font-family", "Arial, sans-serif")
    .style("font-size", "10px")
    .style("fill", "black");

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
    .attr("width", data.cx + 5)
    .attr("height", data.cy + 5)
    .attr("xmlns", "http://www.w3.org/2000/svg");

  const svgElement = createUmlDiagram(svg, data.nodes, data.links);

  const serializer = new window.XMLSerializer();
  let svgString = serializer.serializeToString(svgElement);

  // Inline script to load D3.js from CDN and ensure custom script runs after it's loaded
  const d3Script = `
  <script type="text/javascript">
    <![CDATA[
      var script = document.createElementNS("http://www.w3.org/2000/svg", "script");
      script.setAttribute("href", "https://d3js.org/d3.v7.min.js");
      script.addEventListener("load", function() {
        // D3.js is loaded, now execute the custom script
        function embedUmlScript() {
          const svg = d3.select("svg");
          const zoom = d3.zoom().scaleExtent([0.5, 10]).on("zoom", function (event) {
            d3.select("g.zoom-group").attr("transform", event.transform);
          });
          svg.call(zoom);

        }
        embedUmlScript();
      });
      document.documentElement.appendChild(script);
    ]]>
  </script>`;

  // Inject the script right before the closing </svg> tag
  svgString = svgString.replace("</svg>", `${d3Script}</svg>`);

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
