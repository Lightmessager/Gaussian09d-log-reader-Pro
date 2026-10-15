/* S0 protocol: values originate in Python; JavaScript only renders. */
"use strict";
let bridge;
let latestRevision = -1;
let listenerBound = false;
const plot = document.getElementById("plot");

async function renderPayload(raw) {
  try {
    const data = JSON.parse(raw);
    if (data.protocol_version !== 1) throw new Error("Unsupported protocol");
    if (data.revision < latestRevision) return;
    latestRevision = data.revision;
    const points = data.points;
    const trace = {
      type: "scatter", mode: "lines+markers+text",
      x: points.map(p => p.x), y: points.map(p => p.value),
      text: points.map(p => p.label), textposition: "top center",
      customdata: points.map(p => p.node_id),
      marker: { size: 13, color: ["#0d9488", "#e79b27", "#5367b8", "#0d9488"], line: {color:"white", width:2} },
      line: { color:"#5367b8", width:3 },
      hovertemplate: "%{text}<br>%{y:.4f} kcal/mol<extra>Synthetic S0 sample</extra>"
    };
    const layout = {
      title: { text:"<b>Energy profile · 能量剖面</b><br><sup>Synthetic S0 data · reference R</sup>", x:0.06 },
      paper_bgcolor:"#f7f9fc", plot_bgcolor:"#ffffff",
      font:{family:"Arial, Microsoft YaHei, sans-serif", color:"#27334a", size:13},
      margin:{l:85,r:35,t:100,b:65},
      xaxis:{title:{text:"Reaction step / 反应步骤"},tickvals:points.map(p => p.x),ticktext:points.map(p => p.label),range:[-0.35,3.35],zeroline:false},
      yaxis:{title:{text:"Relative energy (kcal/mol)"},range:[-23,23],gridcolor:"#e4e9f2",zerolinecolor:"#a7b4c8"},
      showlegend:false, uirevision:data.project_id,
      shapes:[{type:"line",x0:-0.3,x1:3.3,y0:0,y1:0,line:{color:"#9daec6",width:1,dash:"dot"}}]
    };
    await Plotly.react(plot, [trace], layout, {responsive:true, displaylogo:false, scrollZoom:true});
    if (!listenerBound) {
      plot.on("plotly_click", event => {
        const p = event.points[0];
        bridge.pointSelected(String(p.customdata), latestRevision);
      });
      listenerBound = true;
    }
    bridge.rendered(data.revision, JSON.stringify({
      point_count:points.length,
      values:plot.data[0].y,
      ids:plot.data[0].customdata,
      plotly_version:Plotly.version,
      svg_count:plot.querySelectorAll("svg.main-svg").length
    }));
  } catch (error) {
    bridge.pageError(String(error));
  }
}

window.s0PointPosition = function(index) {
  const rect = plot.getBoundingClientRect();
  const layout = plot._fullLayout;
  return { x:rect.left + layout.xaxis._offset + layout.xaxis.l2p(plot.data[0].x[index]),
           y:rect.top + layout.yaxis._offset + layout.yaxis.l2p(plot.data[0].y[index]) };
};

new QWebChannel(qt.webChannelTransport, channel => {
  bridge = channel.objects.bridge;
  bridge.dataChanged.connect(renderPayload);
  bridge.pageReady(1, Plotly.version);
});
