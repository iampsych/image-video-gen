"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let STATE = null;
const selected = new Set();   // model filenames ticked for download
const opened = new Set();     // expanded group ids
let cfgDirty = false;         // don't clobber the settings form while typing

const gb = b => b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB";
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

function jobMap(dl) {
  const jobs = {};
  (dl.jobs || []).forEach(j => jobs[j.key] = j);
  return jobs;
}

function renderGroups(manifest, dl) {
  const jobs = jobMap(dl);

  $("#groups").innerHTML = manifest.groups.map(g => {
    const complete = g.have === g.total;
    const isOpen = opened.has(g.id);
    const groupTicked = g.models.every(m => m.state === "ok" || selected.has(m.file));

    const files = g.models.map(m => {
      const job = jobs[`${m.folder}/${m.file}`];
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
  renderSaved(STATE.civitai, STATE.downloads);
  renderTask(STATE.task);
  renderComfy(STATE.comfy);
  renderConfig(STATE.config);
}

const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* --------------------------------------------------------------- civitai */

let CV = null;          // last resolved model
let cvVersion = null;   // chosen version id
let cvFile = null;      // chosen file id
let cvFolder = null;    // chosen target folder

function cvError(message) {
  const box = $("#cv-error");
  box.classList.toggle("hidden", !message);
  box.textContent = message || "";
}

function renderResolved() {
  const box = $("#cv-result");
  if (!CV) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");

  const version = CV.versions.find(v => v.version_id === cvVersion) || CV.versions[0];
  cvVersion = version.version_id;
  if (!version.files.some(f => f.file_id === cvFile)) {
    cvFile = version.files.length ? version.files[0].file_id : null;
  }

  box.innerHTML = `
    <div class="top">
      <div style="flex:1">
        <h4>${esc(CV.name)}</h4>
        <div class="by">
          ${CV.creator ? "by " + esc(CV.creator) + " · " : ""}
          <a href="${esc(CV.page)}" target="_blank" rel="noopener">open on Civitai ↗</a>
        </div>
      </div>
      <span class="kind">${esc(CV.type || "model")}</span>
      ${CV.nsfw ? `<span class="kind nsfw">nsfw</span>` : ""}
    </div>

    <div class="picker">
      <label>Version
        <select id="cv-version">
          ${CV.versions.map(v => `
            <option value="${v.version_id}" ${v.version_id === cvVersion ? "selected" : ""}>
              ${esc(v.version_name || v.version_id)}${v.base_model ? " — " + esc(v.base_model) : ""}
            </option>`).join("")}
        </select>
      </label>
      <label>Install into
        <select id="cv-folder">
          ${(STATE.civitai.folders || []).map(f => `
            <option value="${f}" ${f === (cvFolder || CV.suggested_folder) ? "selected" : ""}>
              models/${f}${f === CV.suggested_folder ? "  (suggested)" : ""}
            </option>`).join("")}
        </select>
      </label>
    </div>

    <div class="cvfiles">
      ${version.files.length ? version.files.map(f => `
        <label class="cvfile">
          <input type="radio" name="cvfile" value="${f.file_id}"
                 ${f.file_id === cvFile ? "checked" : ""}>
          <div>
            <div class="nm">${esc(f.name)}</div>
            <div class="sub2">${esc(f.kind)}${f.primary ? " · primary" : ""}
              · scan: ${esc(f.scan)}</div>
          </div>
          <div class="sz">${gb(f.size)}</div>
        </label>`).join("")
        : `<div class="empty">This version has no downloadable files.</div>`}
    </div>

    <button id="cv-add" class="primary" ${cvFile ? "" : "disabled"}>Add to list</button>`;

  $("#cv-version").onchange = ev => { cvVersion = Number(ev.target.value); cvFile = null; renderResolved(); };
  $("#cv-folder").onchange = ev => { cvFolder = ev.target.value; };
  $$("input[name=cvfile]").forEach(r => r.onchange = () => { cvFile = Number(r.value); });
  const add = $("#cv-add");
  if (add) add.onclick = addResolved;
}

function renderSaved(cv, dl) {
  if (!cv) return;
  const jobs = jobMap(dl);
  const missing = cv.total - cv.have;

  $("#cv-summary").textContent = cv.total
    ? `${cv.have}/${cv.total} present${missing ? " · " + gb(cv.missing_bytes) + " to fetch" : ""}`
    : "0 saved";
  $("#cv-dl-all").disabled = missing === 0;

  $("#cv-saved").innerHTML = cv.models.length ? cv.models.map(m => {
    const job = jobs[`${m.folder}/${m.file}`];
    let tag = `<span class="tag missing">missing</span>`;
    if (m.state === "ok") tag = `<span class="tag ok">installed</span>`;
    else if (m.state === "partial") tag = `<span class="tag partial">partial</span>`;
    else if (m.state === "size-mismatch") tag = `<span class="tag bad">wrong size</span>`;
    if (job) {
      if (job.status === "running") tag = `<span class="tag partial">${job.percent}% · ${rate(job.speed)}</span>`;
      else if (job.status === "queued") tag = `<span class="tag missing">queued</span>`;
      else if (job.status === "error") tag = `<span class="tag bad">failed</span>`;
    }
    const busy = job && (job.status === "running" || job.status === "queued");
    return `
      <div class="cvrow">
        <div>
          <div class="nm">${esc(m.name)}
            ${m.version_name ? `<span style="color:var(--muted);font-weight:400"> · ${esc(m.version_name)}</span>` : ""}
          </div>
          <div class="meta2">models/${esc(m.folder)}/${esc(m.file)}
            ${m.base_model ? " · " + esc(m.base_model) : ""}
            · <a href="${esc(m.page)}" target="_blank" rel="noopener">Civitai ↗</a></div>
          ${job && job.error ? `<div class="meta2" style="color:var(--fail)">${esc(job.error)}</div>` : ""}
          ${job && job.status === "running" ? `<div class="bar"><i style="width:${job.percent}%"></i></div>` : ""}
        </div>
        <div class="sz">${gb(m.size)}</div>
        ${tag}
        <div style="display:flex;gap:6px">
          ${m.state === "ok" || busy ? "" :
            `<button data-cvget="${esc(m.key)}">Download</button>`}
          <button class="ghost" data-cvdel="${esc(m.key)}">Remove</button>
        </div>
      </div>`;
  }).join("") : `<div class="empty">Nothing saved yet — paste a Civitai URL above.</div>`;

  $$("[data-cvget]").forEach(b => b.onclick = async () => {
    await api("/api/civitai/download", { keys: [b.dataset.cvget] });
    poll();
  });
  $$("[data-cvdel]").forEach(b => b.onclick = async () => {
    await api("/api/civitai/remove", { key: b.dataset.cvdel });
    poll();
  });
}

async function lookup() {
  const ref = $("#cv-ref").value.trim();
  if (!ref) return;
  cvError("");
  $("#cv-lookup").disabled = true;
  $("#cv-lookup").textContent = "Looking up…";
  try {
    const res = await api("/api/civitai/resolve", { ref });
    if (!res.ok) { CV = null; cvError(res.error); }
    else {
      CV = res.model;
      cvVersion = CV.selected_version;
      cvFile = null;
      cvFolder = CV.suggested_folder;
    }
    renderResolved();
  } catch (e) {
    cvError("Lookup failed: " + e);
  } finally {
    $("#cv-lookup").disabled = false;
    $("#cv-lookup").textContent = "Look up";
  }
}

async function addResolved() {
  const res = await api("/api/civitai/add", {
    ref: String(CV.model_id),
    version_id: cvVersion,
    file_id: cvFile,
    folder: cvFolder || CV.suggested_folder,
  });
  if (!res.ok) { cvError(res.error); return; }
  CV = null;
  $("#cv-ref").value = "";
  cvError("");
  renderResolved();
  poll();
}

$("#cv-lookup").onclick = lookup;
$("#cv-ref").onkeydown = ev => { if (ev.key === "Enter") lookup(); };
$("#cv-dl-all").onclick = async () => { await api("/api/civitai/download", { all: true }); poll(); };

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
