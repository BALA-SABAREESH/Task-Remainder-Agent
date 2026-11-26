/* ===== STATE ===== */
let tasks = [];
let chartData = [0, 0, 0, 0, 0, 0, 0];
let agentActive = false;

const PRIORITIES = ["high", "med", "low"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const AI_SUGGESTIONS = [
  "add Review project roadmap",
  "add Prepare weekly standup notes",
  "add Fix critical bug in auth module",
  "add Write unit tests for new API",
  "add Update documentation",
  "add Deploy to staging environment",
];
let sugIdx = 0;

/* ===== 3D CANVAS ===== */
(function init3D() {
  try {
    const canvas = document.getElementById("hero-canvas");
    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      75,
      window.innerWidth / window.innerHeight,
      0.1,
      1000,
    );
    camera.position.z = 5;

    // Floating particle system
    const geometry = new THREE.BufferGeometry();
    const count = 120;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 14;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 10;
      const t = Math.random();
      colors[i * 3] = t < 0.5 ? 0.49 : 0;
      colors[i * 3 + 1] = t < 0.5 ? 0.36 : 0.9;
      colors[i * 3 + 2] = t < 0.5 ? 0.99 : 0.75;
    }
    geometry.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.PointsMaterial({
      size: 0.07,
      vertexColors: true,
      transparent: true,
      opacity: 0.7,
    });
    const particles = new THREE.Points(geometry, mat);
    scene.add(particles);

    // Wireframe torus
    const torusGeo = new THREE.TorusGeometry(2, 0.6, 10, 50);
    const torusMat = new THREE.MeshBasicMaterial({
      color: 0x7c5cfc,
      wireframe: true,
      opacity: 0.08,
      transparent: true,
    });
    const torus = new THREE.Mesh(torusGeo, torusMat);
    torus.position.set(3, -1, -3);
    scene.add(torus);

    // Second torus
    const torus2 = new THREE.Mesh(
      new THREE.TorusGeometry(1.2, 0.3, 8, 30),
      new THREE.MeshBasicMaterial({
        color: 0x00e5c0,
        wireframe: true,
        opacity: 0.06,
        transparent: true,
      }),
    );
    torus2.position.set(-4, 2, -4);
    scene.add(torus2);

    let mouse = { x: 0, y: 0 };
    document.addEventListener("mousemove", (e) => {
      mouse.x = (e.clientX / window.innerWidth - 0.5) * 0.3;
      mouse.y = (e.clientY / window.innerHeight - 0.5) * 0.3;
    });

    window.addEventListener("resize", () => {
      renderer.setSize(window.innerWidth, window.innerHeight);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    });

    let t = 0;
    (function animate() {
      requestAnimationFrame(animate);
      t += 0.005;
      particles.rotation.y = t * 0.05 + mouse.x;
      particles.rotation.x = t * 0.02 + mouse.y;
      torus.rotation.x = t * 0.3;
      torus.rotation.y = t * 0.2;
      torus2.rotation.x = -t * 0.2;
      torus2.rotation.z = t * 0.3;
      renderer.render(scene, camera);
    })();
  } catch (e) {
    /* silently fail if WebGL unavailable */
  }
})();

/* ===== SCROLL REVEAL ===== */
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add("visible");
        observer.unobserve(e.target);
      }
    });
  },
  { threshold: 0.1 },
);
document
  .querySelectorAll(".reveal")
  .forEach((el) => observer.observe(el));

/* ===== THEME ===== */
function toggleTheme() {
  const isLight =
    document.documentElement.getAttribute("data-theme") === "light";
  document.documentElement.setAttribute(
    "data-theme",
    isLight ? "dark" : "light",
  );
  document.getElementById("theme-btn").textContent = isLight
    ? "🌙"
    : "☀️";
}

/* ===== SMOOTH SCROLL ===== */
function smoothScroll(sel) {
  document
    .querySelector(sel)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });

  // Update active class on nav links if the event object is not available but we can match by onclick attribute
  document.querySelectorAll(".nav-link").forEach((link) => {
    if (link.getAttribute("onclick")?.includes(sel)) {
      document
        .querySelectorAll(".nav-link")
        .forEach((l) => l.classList.remove("active"));
      link.classList.add("active");
    }
  });
}

/* ===== CHART ===== */
function updateChart() {
  const svg = document.getElementById("chart-svg");
  const W = 300,
    H = 90,
    PAD = 8;
  const max = Math.max(...chartData, 1);
  const pts = chartData.map((v, i) => [
    PAD + (i * (W - PAD * 2)) / 6,
    H - PAD - (v / max) * (H - PAD * 2),
  ]);
  const lineD = pts
    .map(
      (p, i) =>
        (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1),
    )
    .join(" ");
  const areaD =
    lineD + ` L${pts[pts.length - 1][0]},${H} L${pts[0][0]},${H} Z`;
  document.getElementById("chart-line").setAttribute("d", lineD);
  document.getElementById("chart-area").setAttribute("d", areaD);
  const dotsG = document.getElementById("chart-dots");
  dotsG.innerHTML = pts
    .map(
      (p, i) =>
        `<circle class="chart-dot" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${chartData[i] > 0 ? 3 : 1.5}" opacity="${chartData[i] > 0 ? 1 : 0.3}"/>`,
    )
    .join("");
  const labelsEl = document.getElementById("chart-labels");
  labelsEl.innerHTML = DAYS.map(
    (d) => `<span class="chart-label">${d}</span>`,
  ).join("");
}
updateChart();

/* ===== AI INSIGHTS ===== */
function updateInsights() {
  const done = tasks.filter((t) => t.done).length;
  const total = tasks.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const insights = [];
  if (total === 0) {
    insights.push({
      icon: "✨",
      bg: "var(--violet-subtle)",
      text: "<strong>Start adding tasks</strong> to unlock AI-powered recommendations and patterns.",
      time: "now",
    });
  } else {
    if (pct >= 80)
      insights.push({
        icon: "🏆",
        bg: "var(--cyan-subtle)",
        text: `<strong>Exceptional velocity!</strong> ${pct}% completion rate. You're in the top 5% of productive users today.`,
        time: "just now",
      });
    else if (pct >= 50)
      insights.push({
        icon: "📈",
        bg: "var(--violet-subtle)",
        text: `<strong>Solid momentum.</strong> You've completed ${done} of ${total} tasks. Push for ${Math.ceil(total * 0.8)} to hit peak performance.`,
        time: "just now",
      });
    else
      insights.push({
        icon: "💡",
        bg: "var(--amber-subtle)",
        text: `<strong>Tip:</strong> Breaking large tasks into smaller chunks increases completion rate by 40%. Try splitting your pending items.`,
        time: "just now",
      });
    if (tasks.filter((t) => !t.done).length > 3)
      insights.push({
        icon: "⚠️",
        bg: "rgba(255,77,109,0.08)",
        text: `<strong>${tasks.filter((t) => !t.done).length} tasks pending.</strong> Consider prioritizing the top 3 for maximum impact.`,
        time: "AI analysis",
      });
    insights.push({
      icon: "🤖",
      bg: "var(--emerald-subtle)",
      text: `<strong>Agent suggests:</strong> "${AI_SUGGESTIONS[sugIdx % AI_SUGGESTIONS.length].replace("add ", "")}" might be a high-value next task.`,
      time: "NeuralTask AI",
    });
  }
  const list = document.getElementById("insights-list");
  list.innerHTML = insights
    .map(
      (i) => `
  <div class="insight-item">
    <div class="insight-icon" style="background:${i.bg}">${i.icon}</div>
    <div>
      <div class="insight-text">${i.text}</div>
      <div class="insight-time">${i.time}</div>
    </div>
  </div>`,
    )
    .join("");
}

/* ===== AI SCORE ===== */
function aiScore() {
  const total = tasks.length;
  if (!total) return "—";
  const done = tasks.filter((t) => t.done).length;
  const pct = done / total;
  if (pct >= 0.9) return "A+";
  if (pct >= 0.7) return "A";
  if (pct >= 0.5) return "B+";
  if (pct >= 0.3) return "B";
  return "C";
}

/* ===== UPDATE UI ===== */
function updateStats() {
  const done = tasks.filter((t) => t.done).length;
  const total = tasks.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-done").textContent = done;
  document.getElementById("stat-done-pct").textContent = pct + "% rate";
  document.getElementById("stat-pending").textContent = total - done;
  document.getElementById("stat-ai").textContent = aiScore();
  document.getElementById("head-count").textContent =
    total + " item" + (total !== 1 ? "s" : "");
  // ring
  const circumference = 251.2;
  document.getElementById("ring-fill").style.strokeDashoffset =
    circumference - (pct / 100) * circumference;
  document.getElementById("ring-pct").textContent = pct + "%";
  document.getElementById("ms-total").textContent = total;
  document.getElementById("ms-done").textContent = done;
  document.getElementById("ms-pend").textContent = total - done;
  updateInsights();
}

/* ===== RENDER TASKS ===== */
function renderTasks() {
  const list = document.getElementById("task-list");
  if (!tasks.length) {
    list.innerHTML =
      '<div class="empty-state"><span class="empty-icon">📭</span>No tasks yet — add one below</div>';
  } else {
    list.innerHTML = tasks
      .map(
        (t, i) => `
    <div class="task-item${t.isNew ? " entering" : ""}">
      <span class="task-num">${String(i + 1).padStart(2, "0")}</span>
      <div class="check-circle${t.done ? " done" : ""}" onclick="completeTask(${i})" title="Mark done"></div>
      <div class="task-body">
        <div class="task-text${t.done ? " done" : ""}">${escHtml(t.task)}</div>
        <div class="task-meta">${t.added}</div>
      </div>
      <span class="priority-tag pt-${t.priority}">${t.priority}</span>
      <span class="task-badge ${t.done ? "done" : "pending"}">${t.done ? "done" : "pending"}</span>
      <button class="del-btn" onclick="deleteTask(${i})" title="Delete">✕</button>
    </div>`,
      )
      .join("");
    tasks.forEach((t) => {
      t.isNew = false;
    });
  }
  updateStats();
}

/* ===== HELPERS ===== */
function escHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
function now() {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}
function randomPriority() {
  return PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)];
}

/* ===== LOG ===== */
function log(text, cls) {
  const term = document.getElementById("terminal");
  const d = document.createElement("div");
  d.className = cls || "";
  d.innerHTML = text;
  term.appendChild(d);
  term.scrollTop = term.scrollHeight;
}

/* ===== TOAST ===== */
let toastTimer;
function showToast(msg, icon = "✓") {
  clearTimeout(toastTimer);
  document.getElementById("toast-msg").textContent = msg;
  document.getElementById("toast-icon").textContent = icon;
  const t = document.getElementById("toast");
  t.classList.add("show");
  toastTimer = setTimeout(() => t.classList.remove("show"), 2500);
}

/* ===== AGENT PULSE ===== */
function setAgentActive(on) {
  agentActive = on;
  const p = document.getElementById("agent-pulse");
  if (on) p.classList.remove("idle");
  else p.classList.add("idle");
}

/* ===== PROCESS COMMAND ===== */
async function processCommand(cmd) {
  cmd = cmd.trim();
  if (!cmd) return;
  log("$ " + escHtml(cmd), "t-prompt");
  setAgentActive(true);

  // Simulate agent thinking
  const thinkEl = document.createElement("div");
  thinkEl.className = "t-ai";
  thinkEl.innerHTML =
    '<span class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></span>';
  document.getElementById("terminal").appendChild(thinkEl);
  document.getElementById("terminal").scrollTop = 9999;

  await new Promise((r) => setTimeout(r, 300 + Math.random() * 200));
  thinkEl.remove();
  setAgentActive(false);

  if (cmd.startsWith("add ")) {
    const task = cmd.slice(4).trim();
    if (!task) {
      log("→ Error: please provide a task name.", "t-err");
      return;
    }
    const priority = randomPriority();
    tasks.push({
      task,
      done: false,
      isNew: true,
      added: now(),
      priority,
    });
    // update chart
    const dayIdx = new Date().getDay();
    chartData[(dayIdx + 6) % 7]++;
    updateChart();
    log(
      `→ Task added: <span style="color:var(--text)">"${escHtml(task)}"</span>  <span style="color:var(--text-dim)">[priority: ${priority}]</span>`,
      "t-res",
    );
    showToast("Task added", "➕");
    renderTasks();
    sugIdx++;
    document.getElementById("ai-suggest-text").textContent =
      AI_SUGGESTIONS[sugIdx % AI_SUGGESTIONS.length].replace(
        "add ",
        "Try: ",
      );
  } else if (cmd === "show") {
    if (!tasks.length) {
      log("→ No tasks in memory.", "t-res");
      return;
    }
    tasks.forEach((t, i) => {
      log(
        `  ${String(i + 1).padStart(2, "0")}. ${escHtml(t.task)} <span style="color:var(--text-dim)">[${t.done ? "✔ done" : "✘ pending"} · ${t.priority}]</span>`,
        "t-res",
      );
    });
  } else if (cmd.startsWith("done ")) {
    const num = parseInt(cmd.slice(5)) - 1;
    if (isNaN(num) || num < 0 || num >= tasks.length) {
      log("→ Error: invalid task number.", "t-err");
    } else if (tasks[num].done) {
      log("→ Task already completed.", "t-err");
    } else {
      tasks[num].done = true;
      log(
        `→ Task ${num + 1} marked as <span style="color:var(--cyan)">completed</span> ✓`,
        "t-res",
      );
      showToast("Task completed", "✅");
      renderTasks();
    }
  } else if (cmd === "ai") {
    log(
      '→ 🤖 <span style="color:var(--amber)">NeuralTask AI Analysis</span>',
      "t-ai",
    );
    const done = tasks.filter((t) => t.done).length;
    const total = tasks.length;
    const pct = total ? Math.round((done / total) * 100) : 0;
    log(`  ├─ Total tasks: ${total}`, "t-ai");
    log(`  ├─ Completion: ${pct}% (${done}/${total})`, "t-ai");
    log(`  ├─ AI Score: ${aiScore()}`, "t-ai");
    log(
      `  └─ Recommendation: ${pct >= 70 ? "Great velocity! Keep it up." : "Focus on high-priority tasks first."}`,
      "t-ai",
    );
  } else if (cmd === "exit") {
    log("→ Goodbye! Agent shutting down gracefully.", "t-info");
    showToast("Agent exited", "⏻");
    setAgentActive(false);
    document.getElementById("agent-pulse").classList.add("idle");
  } else {
    log(
      '→ Unknown command. Try: <span style="color:var(--violet-light)">add / show / done &lt;n&gt; / ai / exit</span>',
      "t-err",
    );
  }
}

/* ===== TASK ACTIONS ===== */
function completeTask(i) {
  if (tasks[i].done) return;
  tasks[i].done = true;
  log("$ done " + (i + 1), "t-prompt");
  log(
    `→ Task ${i + 1} marked as <span style="color:var(--cyan)">completed</span> ✓`,
    "t-res",
  );
  showToast("Task completed", "✅");
  renderTasks();
}

function deleteTask(i) {
  const name = tasks[i].task;
  tasks.splice(i, 1);
  renderTasks();
  log(`$ [deleted task: "${escHtml(name)}"]`, "t-info");
  showToast("Removed: " + name.slice(0, 24), "✕");
}

/* ===== TERMINAL ===== */
function clearTerminal() {
  document.getElementById("terminal").innerHTML =
    '<div class="t-info">── Terminal cleared ──</div>';
}

/* ===== QUICK CMD ===== */
function runCmd() {
  const input = document.getElementById("cmd-input");
  processCommand(input.value);
  input.value = "";
}

function quickCmd(cmd) {
  const input = document.getElementById("cmd-input");
  input.value = cmd;
  input.focus();
  if (!cmd.endsWith(" ")) {
    processCommand(cmd);
    input.value = "";
  }
}

function insertSuggestion() {
  const sug = AI_SUGGESTIONS[sugIdx % AI_SUGGESTIONS.length];
  document.getElementById("cmd-input").value = sug;
  document.getElementById("cmd-input").focus();
}

/* ===== ENTER KEY ===== */
document.getElementById("cmd-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runCmd();
});

/* ===== INIT ===== */
updateStats();
updateChart();

// Parallax on hero text
window.addEventListener("scroll", () => {
  const y = window.scrollY;
  const hero = document.querySelector(".hero-title");
  if (hero && y < window.innerHeight) {
    hero.style.transform = `translateY(${y * 0.3}px)`;
    hero.style.opacity = 1 - y / 600;
  }
});