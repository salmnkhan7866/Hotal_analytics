// Draws every chart from ONE JSON call: /api/analytics?start=..&end=..
const COLORS = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d'];
const charts = {};

function drawChart(id, type, data, label) {
  const el = document.getElementById(id);
  if (!el) return;                       // this page does not have that chart
  if (charts[id]) charts[id].destroy();  // redraw when the filter changes
  charts[id] = new Chart(el, {
    type: type,
    data: {
      labels: data.labels,
      datasets: [{
        label: label,
        data: data.values,
        backgroundColor: type === 'line' ? 'rgba(37,99,235,0.15)' : COLORS,
        borderColor: '#2563eb',
        fill: type === 'line',
        tension: 0.3
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: type === 'doughnut' } } }
  });
}

function setKpi(name, text) {
  const el = document.getElementById('kpi-' + name);
  if (el) el.textContent = text;
}

function renderAll(d) {
  const k = d.kpis;
  setKpi('total_bookings', k.total_bookings.toLocaleString());
  setKpi('cancel_rate', k.cancel_rate + '%');
  setKpi('revenue', '$' + k.revenue.toLocaleString());
  setKpi('adr', '$' + k.adr);
  setKpi('occupancy', k.occupancy + '%');
  setKpi('avg_lead_time', k.avg_lead_time + ' days');

  drawChart('chart-occupancy', 'line', d.occupancy, 'Occupancy %');
  drawChart('chart-cancel-trend', 'line', d.cancel_trend, 'Cancellation %');
  drawChart('chart-revenue', 'bar', d.revenue_room, 'Revenue');
  drawChart('chart-origin', 'doughnut', d.origin, 'Bookings');
  drawChart('chart-cancel-lead', 'bar', d.cancel_lead, 'Cancellation %');
  drawChart('chart-cancel-type', 'bar', d.cancel_type, 'Cancellation %');
}

async function loadAnalytics(start, end) {
  const params = new URLSearchParams();
  if (start) params.append('start', start);
  if (end) params.append('end', end);
  const response = await fetch('/api/analytics?' + params.toString());
  renderAll(await response.json());
}
