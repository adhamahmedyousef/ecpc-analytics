/* =============================================
   ECPC Analytics — main.js
   Shared utilities + sidebar + chart helpers
   ============================================= */

const API = '';  


async function apiFetch(path) {
  try {
    const res = await fetch(API + path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn(`[apiFetch] ${path} failed:`, e);
    setStatusError();
    return null;
  }
}

function setStatusError() {
  const dot = document.getElementById('status-dot');
  if (dot) {
    dot.classList.remove('bg-green-400');
    dot.classList.add('bg-red-500');
    dot.title = 'API Error';
  }
}

function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function animateNumber(elId, target, suffix = '') {
  const el = document.getElementById(elId);
  if (!el || !target) { if (el) el.textContent = target + suffix; return; }
  let start = 0;
  const dur = 800;
  const startTime = performance.now();
  function tick(now) {
    const elapsed = Math.min(now - startTime, dur);
    const val = Math.round(easeOut(elapsed / dur) * target);
    el.textContent = val.toLocaleString() + suffix;
    if (elapsed < dur) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function renderRate(rate) {
  if (rate === undefined || rate === null) return '<span class="text-gray-600">—</span>';
  const pct = Math.max(0, Math.min(100, Math.round(rate)));
  const color = pct >= 60 ? '#22c55e' : pct >= 30 ? '#f59e0b' : '#ef4444';
  return `
    <div class="rate-bar-wrap">
      <div class="rate-bar-bg">
        <div class="rate-bar-fill" style="width:${pct}%;background:${color}"></div>
      </div>
      <span class="rate-text">${pct}%</span>
    </div>`;
}

Chart.defaults.color = '#6b6b7e';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size = 11;

const DIFF_COLORS = {
  'Easy':      { bg: 'rgba(34,197,94,0.75)',   border: '#22c55e' },
  'Medium':    { bg: 'rgba(245,158,11,0.75)',  border: '#f59e0b' },
  'Hard':      { bg: 'rgba(239,68,68,0.75)',   border: '#ef4444' },
  'Very Hard': { bg: 'rgba(168,85,247,0.75)',  border: '#a855f7' },
};

const TOPIC_PALETTE = [
  '#e84545','#ff6b6b','#f59e0b','#22c55e','#3b82f6',
  '#a855f7','#ec4899','#14b8a6','#f97316','#06b6d4',
  '#84cc16','#6366f1','#e11d48','#64748b','#0ea5e9',
];

function renderPie(canvasId, labels, values) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const bgColors  = labels.map(l => DIFF_COLORS[l]?.bg   || 'rgba(100,100,130,0.6)');
  const bdrColors = labels.map(l => DIFF_COLORS[l]?.border || '#6b6b7e');

  const existing = Chart.getChart(canvasId);
  if (existing) existing.destroy();

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: bgColors, borderColor: bdrColors, borderWidth: 1.5, hoverOffset: 6 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 12, boxWidth: 10, font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${ctx.parsed} problems`
          }
        }
      }
    }
  });
}

function renderBar(canvasId, labels, values) {
  const maxVal = Math.max(...values);

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const existing = Chart.getChart(canvasId);
  if (existing) existing.destroy();

  const bgColors = labels.map((_, i) => TOPIC_PALETTE[i % TOPIC_PALETTE.length] + 'bb');
  const bdrColors = labels.map((_, i) => TOPIC_PALETTE[i % TOPIC_PALETTE.length]);

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: bgColors,
        borderColor: bdrColors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: ctx => ` ${ctx.parsed.x} problems` }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(30,30,46,0.8)' },
          ticks: { color: '#6b6b7e' }
        },
        y: {
          grid: { display: false },
          ticks: {
            autoSkip: false,
            maxRotation: 0,
            minRotation: 0
          }
        }
      }
    }
  });
}

async function loadSidebarContests() {
  const el = document.getElementById('sidebar-contests');
  if (!el) return;

  const contests = await apiFetch('/api/contests');
  if (!contests) { el.innerHTML = '<div class="px-2 py-1 text-red-500 text-xs">Failed to load</div>'; return; }

  const currentPath = window.location.pathname;
  el.innerHTML = contests.map(c => {
    const href = `/contest/${encodeURIComponent(c.contest_id)}`;
    const isActive = currentPath.startsWith(`/contest/${encodeURIComponent(c.contest_id)}`);
    const typeIcon = c.is_qualification ? '🎯' : '🏆';
    return `
      <a href="${href}" class="sidebar-contest-link ${isActive ? 'active-contest' : ''}" title="${escHtml(c.title)}">
        ${typeIcon} ${escHtml(c.title)}
      </a>`;
  }).join('');
}

document.addEventListener('DOMContentLoaded', () => {
  loadSidebarContests();

  // --- Mobile sidebar toggle ---
  const sidebar  = document.getElementById('sidebar');
  const toggle   = document.getElementById('sidebar-toggle');
  const overlay  = document.getElementById('sidebar-overlay');

  function openSidebar() {
    sidebar.classList.add('open');
    overlay.classList.add('active');
    // Need a frame to transition opacity from 0
    requestAnimationFrame(() => overlay.style.display = 'block');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
    setTimeout(() => {
      if (!overlay.classList.contains('active')) overlay.style.display = '';
    }, 250);
  }

  if (toggle) {
    toggle.addEventListener('click', () => {
      sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
    });
  }
  if (overlay) {
    overlay.addEventListener('click', closeSidebar);
  }

  // Close sidebar when a nav link inside it is clicked (mobile)
  sidebar?.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 768) closeSidebar();
    });
  });

  // Auto-close sidebar when resizing past breakpoint
  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) closeSidebar();
  });
});
