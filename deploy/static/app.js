"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let STATE = null;
const selected = new Set();   // model filenames ticked for download
const opened = new Set();     // expanded group ids
let cfgDirty = false;         // don't clobber the settings form while typing

const gb = b => (b / 1e9).toFixed(b < 1e9 ? 2 : 1) + " GB";
const rate = b => b > 1e6 ? (b / 1e6).toFixed(1) + " MB/s" : Math.round(b / 1e3) + " KB/s";

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

/* ------------------------------------------------------------------- tabs */

$$("#tabs button").forEach(btn => btn.onclick = () => {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b === btn));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + btn.dataset.tab));
});

/* ----------------------------------------------------------------- render */

function renderChecks(doctor) {
  const marks = { ok: "●", warn: "▲", fail: "✕" };
  $("#checks").innerHTML = doctor.checks.map(c => `
    <div class="check-row ${c.status}">
      <div class="mark">${marks[c.status]}</div>
      <div>
        <b>${esc(c.name)}</b>
        <div class="detail">${esc(c.detail)}</div>
        ${c.hint && c.status !== "ok" ? `<div class="fix">${esc(c.hint)}</div>` : ""}
      </div>
    </div>`).join("");

  const blocked = doctor.checks.filter(c => c.status === "fail");
  const box = $("#blocker");
  if (blocked.length) {
    box.classList.remove("hidden");
    box.innerHTML = `<b>${blocked.length} check${blocked.length > 1 ? "s" : ""} failing</b>
      Work through the Setup tab in order; each fix re-runs this page automatically.`;
  } else {
    box.classList.add("hidden");
  }

  const gpu = doctor.gpus && doctor.gpus[0];
  $("#gpu-badge").textContent = gpu
    ? `${gpu.name} · ${Math.round(gpu.vram_mb / 1024)} GB`
    : "no GPU detected";
}

function renderGroups(manifest, dl) {
  const jobs = {};
  (dl.jobs || []).forEach(j => jobs[j.file] = j);

  $("#groups").innerHTML = manifest.groups.map(g => {
    const complete = g.have === g.total;
    const isOpen = opened.has(g.id);
    const groupTicked = g.models.every(m => m.state === "ok" || selected.has(m.file));

    const files = g.models.map(m => {
      const job = jobs[m.file];
      const busy = job && (job.status === "running" || job.status === "queued");
      let tag = `<span class="tag missing">missing</span>`;
      if (m.state === "ok") tag = `<span class="tag ok">installed</span>`;
      else if (m.state === "partial") tag = `<span class="tag partial">partial ${Math.round(100 * m.local_size / m.size)}%</span>`;
      else if (m.state === "size-mismatch") tag = `<span class="tag bad">wrong size</span>`;
      if (job) {
        if (job.status === "running") tag = `<span class="tag partial">${job.percent}% · ${rate(job.speed)}</span>`;
        else if (job.status === "queued") tag = `<span class="tag missing">queued</span>`;
        else if (job.status === "error") tag = `<span class="tag bad">failed</span>`;
        else if (job.status === "cancelled") tag = `<span class="tag missing">cancelled</span>`;
      }
      return `
        <div class="file">
          <input type="checkbox" data-file="${esc(m.file)}"
                 ${selected.has(m.file) ? "checked" : ""}
                 ${m.state === "ok" || busy ? "disabled" : ""}>
          <div>
            <div class="nm">${esc(m.folder)}/${esc(m.file)}</div>
            <div class="note">${esc(m.note)}</div>
            ${job && job.status === "running"
              ? `<div class="bar"><i style="width:${job.percent}%"></i></div>` : ""}
            ${job && job.error ? `<div class="note" style="color:var(--fail)">${esc(job.error)}</div>` : ""}
          </div>
          <div class="sz">${gb(m.size)}</div>
          ${tag}
        </div>`;
    }).join("");

    return `
      <div class="group ${isOpen ? "open" : ""}" data-group="${g.id}">
        <div class="group-head">
          <input type="checkbox" data-groupsel="${g.id}" ${groupTicked && !complete ? "checked" : ""}
                 ${complete ? "disabled" : ""}>
          <span class="chev">▶</span>
          <div class="title">
            <b>${esc(g.name)}</b>
            <span class="sum">${esc(g.summary)}</span>
          </div>
          <div class="meta">
            <span class="${complete ? "done" : ""}">${g.have}/${g.total} files</span><br>
            ${complete ? "complete" : gb(g.missing_bytes) + " to fetch"}
          </div>
        </div>
        <div class="files">${files}</div>
      </div>`;
  }).join("");

  // expand / collapse
  $$(".group-head").forEach(head => head.onclick = ev => {
    if (ev.target.matches("input")) return;
    const id = head.parentElement.dataset.group;
    opened.has(id) ? opened.delete(id) : opened.add(id);
    head.parentElement.classList.toggle("open");
  });

  $$("[data-file]").forEach(box => box.onchange = () => {
    box.checked ? selected.add(box.dataset.file) : selected.delete(box.dataset.file);
    render();
  });

  $$("[data-groupsel]").forEach(box => box.onchange = () => {
    const group = manifest.groups.find(g => g.id === box.dataset.groupsel);
    group.models.forEach(m => {
      if (m.state === "ok") return;
      box.checked ? selected.add(m.file) : selected.delete(m.file);
    });
    render();
  });

  const active = (dl.jobs || []).filter(j => j.status === "running" || j.status === "queued");
  const box = $("#dl-active");
  if (active.length) {
    const pct = dl.total_bytes ? Math.round(100 * dl.done_bytes / dl.total_bytes) : 0;
    box.classList.remove("hidden");
    box.innerHTML = `<b>Downloading ${active.length} file${active.length > 1 ? "s" : ""}
      — ${pct}% of ${gb(dl.total_bytes)} at ${rate(dl.speed)}</b>
      <div class="bar"><i style="width:${pct}%"></i></div>`;
  } else {
    box.classList.add("hidden");
  }

  const n = selected.size;
  $("#dl-selected").disabled = n === 0;
  $("#dl-selected").textContent = n ? `Download ${n} file${n > 1 ? "s" : ""}` : "Download selected";
}

function renderTask(task) {
  $("#task-name").textContent = task.name || "no task running";
  const pill = $("#task-status");
  pill.textContent = task.status;
  pill.className = "pill " + task.status;
  const log = $("#task-log");
  const pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.textContent = task.lines.length ? task.lines.join("\n") : "Output appears here.";
  if (pinned) log.scrollTop = log.scrollHeight;
  $$("[data-step]").forEach(b => b.disabled = task.status === "running");
}

function renderComfy(comfy) {
  const pill = $("#comfy-state");
  pill.textContent = comfy.running ? "running" : "stopped";
  pill.className = "pill " + (comfy.running ? "running" : "");
  $("#comfy-start").disabled = comfy.running;
  $("#comfy-stop").disabled = !comfy.running;

  const link = $("#comfy-link");
  link.classList.toggle("hidden", !comfy.running);
  if (comfy.running) link.href = comfy.url;

  const log = $("#comfy-log");
  const pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.textContent = comfy.lines.length ? comfy.lines.join("\n") : "Not running.";
  if (pinned) log.scrollTop = log.scrollHeight;
}

function renderConfig(cfg) {
  if (cfgDirty) return;
  const form = $("#cfg-form");
  for (const [key, value] of Object.entries(cfg)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = !!value;
    else field.value = value;
  }
  $("#chan").textContent = cfg.torch_channel;
}

function render() {
  if (!STATE) return;
  renderChecks(STATE.doctor);
  renderGroups(STATE.manifest, STATE.downloads);
  renderTask(STATE.task);
  renderComfy(STATE.comfy);
  renderConfig(STATE.config);
}

const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ poll */

async function poll() {
  try {
    STATE = await api("/api/state");
    $("#pulse").classList.remove("stale");
    render();
  } catch {
    $("#pulse").classList.add("stale");
  }
}

/* --------------------------------------------------------------- actions */

$("#dl-selected").onclick = async () => {
  await api("/api/download", { files: [...selected] });
  selected.clear();
  poll();
};
$("#dl-cancel").onclick = async () => { await api("/api/download/cancel", { all: true }); poll(); };

$("#sel-recommended").onclick = () => {
  selected.clear();
  STATE.manifest.groups.filter(g => g.recommended).forEach(g =>
    g.models.forEach(m => { if (m.state !== "ok") selected.add(m.file); }));
  render();
};
$("#sel-missing").onclick = () => {
  selected.clear();
  STATE.manifest.groups.forEach(g =>
    g.models.forEach(m => { if (m.state !== "ok") selected.add(m.file); }));
  render();
};
$("#sel-none").onclick = () => { selected.clear(); render(); };

$$("[data-step]").forEach(btn => btn.onclick = async () => {
  const res = await api("/api/setup", { step: btn.dataset.step });
  if (!res.ok && res.error) alert(res.error);
  $$("#tabs button").find(b => b.dataset.tab === "setup").click();
  poll();
});

$("#wf-install").onclick = async () => {
  const res = await api("/api/workflows/install", {});
  const box = $("#wf-result");
  box.classList.remove("hidden");
  box.classList.add("good");
  box.innerHTML = `<b>Installed ${res.copied.length} workflows</b>
    Copied to <code>${esc(res.dest)}</code>. Reload the ComfyUI tab to see them in the sidebar.`;
  $("#wf-list").innerHTML = res.copied.map(f => `<li>${esc(f)}</li>`).join("");
};

$("#comfy-start").onclick = async () => {
  const res = await api("/api/comfy/start", {});
  if (!res.ok && res.error) alert(res.error);
  poll();
};
$("#comfy-stop").onclick = async () => { await api("/api/comfy/stop", {}); poll(); };

const form = $("#cfg-form");
form.oninput = () => { cfgDirty = true; };
form.onsubmit = async ev => {
  ev.preventDefault();
  const patch = {};
  for (const field of form.elements) {
    if (!field.name) continue;
    if (field.type === "checkbox") patch[field.name] = field.checked;
    else if (field.type === "number") patch[field.name] = Number(field.value);
    else patch[field.name] = field.value;
  }
  await api("/api/config", patch);
  cfgDirty = false;
  const saved = $("#cfg-saved");
  saved.classList.remove("hidden");
  setTimeout(() => saved.classList.add("hidden"), 1600);
  poll();
};

poll();
setInterval(poll, 1000);
