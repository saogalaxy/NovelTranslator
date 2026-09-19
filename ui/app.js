const $ = (id) => document.getElementById(id);
let filter = "all";
let selected = "";
let busy = false;
let series = { series_chapters: 0, downloaded: 0, translated: 0, missing: 0, title: "" };
let recommendations = { items: [], message: "" };
let recsLoaded = false;

function setStatus(text, value, working) {
  if (text) {
    $("progressText").textContent = text;
    $("status").textContent = text;
  }
  if (value != null) $("bar").style.width = `${Math.round(value * 100)}%`;
  if (working != null) $("statusBar").classList.toggle("busy", Boolean(working));
}

function form() {
  return {
    url: $("url").value,
    mode: document.querySelector("input[name=mode]:checked").value,
    start: $("start").value,
    end: $("end").value,
    target_language: $("lang").value,
    provider: $("provider").value,
    model: $("model").value,
    api_key: $("apiKey").value,
    api_base: $("apiBase").value,
    output_dir: $("output").value,
    glossary: $("glossary").value,
    ncode: selected,
    headset_host: $("headsetHost") ? $("headsetHost").value : "",
    headset_port: $("headsetPort") ? $("headsetPort").value : "8765",
    headset_token: $("headsetToken") ? $("headsetToken").value : "",
  };
}

function setLogOpen(open) {
  $("logCard").classList.toggle("open", open);
  $("logCard").classList.toggle("collapsed", !open);
}

function applyConfig(cfg) {
  $("url").value = cfg.url || "";
  $("start").value = cfg.start || "1";
  $("end").value = cfg.end || "3";
  $("lang").value = cfg.target_language || "English";
  $("provider").value = cfg.provider || "ollama";
  $("apiKey").value = cfg.api_key || "";
  $("apiBase").value = cfg.api_base || "";
  $("output").value = cfg.output_dir || "";
  $("glossary").value = cfg.glossary || "";
  if ($("headsetHost")) $("headsetHost").value = cfg.headset_host || "";
  if ($("headsetPort")) $("headsetPort").value = cfg.headset_port || 8765;
  if ($("headsetToken")) $("headsetToken").value = cfg.headset_token || "";
  document.querySelector(`input[name=mode][value="${cfg.mode || "chapters"}"]`).checked = true;
  $("cloud").classList.toggle("hidden", cfg.provider !== "openai");
}

function applyModels(models, current) {
  $("model").innerHTML = (models || []).map((m) => `<option ${m === current ? "selected" : ""}>${m}</option>`).join("");
  if (current && ![...(models || [])].includes(current)) {
    $("model").innerHTML += `<option selected>${current}</option>`;
  }
}

function showLibraryMode() {
  const recommended = filter === "recommended";
  $("libraryPanel").classList.toggle("hidden", recommended);
  $("recsPanel").classList.toggle("hidden", !recommended);
}

function renderLibrary(lib) {
  showLibraryMode();
  if (filter === "recommended") return;
  const books = (lib.books || []).filter((b) => filter !== "completed" || b.status === "translated");
  $("books").innerHTML = books
    .map((b) => {
      const label = filter === "author" ? b.display_author || b.author || b.display_title : b.display_title;
      const active = b.ncode === selected ? "active" : "";
      return `<button class="${active}" data-ncode="${b.ncode}">${label}</button>`;
    })
    .join("");
  $("chapters").innerHTML = (lib.chapters || [])
    .map((c) => {
      if (typeof c === "string") return `<div class="chapter-row"><p>${c}</p></div>`;
      const jp = c.japanese || "—";
      const en = c.english || "English title pending";
      return `<div class="chapter-row">
        <span class="chapter-num">${c.number}</span>
        <div>
          <p class="chapter-jp">${jp}</p>
          <p class="chapter-en">${en}</p>
          <p class="chapter-mark">[${c.status || ""}]</p>
        </div>
      </div>`;
    })
    .join("");
  if (lib.url) {
    $("url").value = lib.url;
  }
  if (lib.resume_start && document.activeElement !== $("start")) {
    $("start").value = lib.resume_start;
  }
  if (lib.selected && !busy) {
    setStatus(`Selected: ${lib.selected}`);
  }
  $("books").querySelectorAll("button").forEach((btn) => {
    btn.onclick = async () => {
      selected = btn.dataset.ncode;
      setStatus("Opening book… filling titles and cleaning names", 0.15, true);
      const next = await window.pywebview.api.select_book(selected);
      renderLibrary(next);
      refreshSeries();
      setStatus($("progressText").textContent || "Ready", null, false);
    };
    btn.ondblclick = () => window.pywebview.api.open_selected(btn.dataset.ncode);
  });
}

function renderRecommendations(payload) {
  recommendations = payload || recommendations;
  const items = recommendations.items || [];
  $("recsStatus").textContent = recommendations.message || (items.length ? `${items.length} upcoming titles` : "No recommendations yet.");
  if (!items.length) {
    $("recs").innerHTML = `<p class="note">No cached recommendations. Hit Refresh list to load LiveChart upcoming anime.</p>`;
    return;
  }
  $("recs").innerHTML = items
    .map((item) => {
      const title = escapeHtml(item.title_en || item.official_title || "Untitled");
      const jp = escapeHtml(item.title_jp || "");
      const cover = escapeHtml(item.cover_url || "");
      const url = escapeHtml(item.webnovel_url || "");
      const ncode = escapeHtml(item.ncode || "");
      const live = escapeHtml(item.livechart_url || "");
      const badge = item.has_webnovel ? `<span class="badge">Syosetu</span>` : "";
      const chips = []
        .concat(item.available || [])
        .concat((item.publishers || []).slice(0, 2))
        .map((c) => `<span class="chip">${escapeHtml(c)}</span>`)
        .join("");
      const useBtn = item.webnovel_url
        ? `<button type="button" class="use" data-url="${url}" data-ncode="${ncode}">Use this URL</button>`
        : `<button type="button" disabled title="No Syosetu match">No web novel URL</button>`;
      const liveLink = live ? `<a href="${live}" target="_blank" rel="noreferrer">LiveChart</a>` : "";
      return `<article class="rec-card">
        <img src="${cover}" alt="" loading="lazy" onerror="this.style.opacity=.2" />
        <div>
          <h4>${title}${badge}</h4>
          ${jp ? `<p class="jp">${jp}</p>` : ""}
          <div class="chips">${chips}</div>
          <div class="actions">${useBtn}${liveLink}</div>
        </div>
      </article>`;
    })
    .join("");
  $("recs").querySelectorAll("button.use").forEach((btn) => {
    btn.onclick = async () => {
      selected = btn.dataset.ncode || "";
      $("url").value = btn.dataset.url || "";
      try {
        const res = await window.pywebview.api.remember_url({
          url: btn.dataset.url,
          ncode: btn.dataset.ncode,
        });
        if (res && res.url_history) renderHistory(res.url_history);
      } catch (_) {}
      filter = "all";
      document.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("current", b.dataset.filter === "all"));
      showLibraryMode();
      setStatus(`Loaded recommendation URL`, 0.2, true);
      refreshSeries(false);
      const state = await window.pywebview.api.state();
      renderLibrary(state.library);
    };
  });
}

async function loadRecommendations(force) {
  if (!window.pywebview) return;
  showLibraryMode();
  $("recsStatus").textContent = force ? "Refreshing upcoming anime…" : "Loading recommendations…";
  if (force) {
    setStatus("Loading upcoming anime…", 0.15, true);
    await window.pywebview.api.refresh_recommendations();
    return;
  }
  const payload = await window.pywebview.api.recommendations();
  recsLoaded = true;
  renderRecommendations(payload);
  if (!(payload.items || []).length) {
    setStatus("Loading upcoming anime…", 0.15, true);
    await window.pywebview.api.refresh_recommendations();
  }
}

window.onNative = (name, payload) => {
  if (name === "busy") {
    busy = Boolean(payload);
    setStatus(null, null, busy);
    if (busy) setLogOpen(true);
  }
  if (name === "log") {
    $("log").textContent += payload + "\n";
    $("log").scrollTop = $("log").scrollHeight;
  }
  if (name === "progress") {
    setStatus(payload.text || "", payload.value, busy);
  }
  if (name === "library") renderLibrary(payload);
  if (name === "official") renderOfficial(payload);
  if (name === "series") renderSeries(payload);
  if (name === "history") renderHistory(payload);
  if (name === "recommendations") {
    recsLoaded = true;
    renderRecommendations(payload);
    if (filter === "recommended") showLibraryMode();
  }
};

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderHistory(rows) {
  const box = $("urlHistory");
  if (!box) return;
  const list = rows || [];
  if (!list.length) {
    box.innerHTML = `<p class="note">Paste or look up a URL to save it here (last 10).</p>`;
    return;
  }
  box.innerHTML = list
    .map((row) => {
      const en = escapeHtml(row.english_title || row.title || row.ncode || "Untitled");
      const chapters = row.series_chapters ? `${row.series_chapters} ch` : "";
      const meta = escapeHtml([row.ncode, chapters].filter(Boolean).join(" · "));
      const url = escapeHtml(row.url || "");
      const ncode = escapeHtml(row.ncode || "");
      return `<button type="button" data-url="${url}" data-ncode="${ncode}">
        <span class="en">${en}</span>
        <span class="meta">${meta}</span>
      </button>`;
    })
    .join("");
  box.querySelectorAll("button").forEach((btn) => {
    btn.onclick = () => {
      selected = btn.dataset.ncode || "";
      $("url").value = btn.dataset.url || "";
      setStatus(`Loaded recent URL: ${btn.querySelector(".en")?.textContent || ""}`, 0.2, true);
      refreshSeries(false);
    };
  });
}

function renderSeries(info) {
  series = info || series;
  const box = $("seriesCounts");
  if (!box) return;
  if (!info || !info.ncode) {
    box.innerHTML = "Enter a Syosetu URL to see series length and what you already have.";
    return;
  }
  const total = info.series_chapters || 0;
  const down = info.downloaded || 0;
  const done = info.translated || 0;
  const missing = info.missing || Math.max(0, total - down);
  if (total > 0) {
    const endVal = parseInt($("end").value || "0", 10);
    if (!endVal || endVal > total) $("end").value = String(total);
  }
  const jp = info.title ? `<strong>${info.title}</strong>` : "";
  const en = info.english_title ? `<span class="en-title">${info.english_title}</span>` : "English title pending — hit Lookup titles";
  const range = total ? `1–${total}` : "unknown";
  box.innerHTML = `${jp}${jp && en ? "<br/>" : ""}${en}<br/>Series has <strong>${total || "?"}</strong> chapter${total === 1 ? "" : "s"} (range ${range}).<br/>Downloaded <strong>${down}</strong> · translated <strong>${done}</strong> · still missing <strong>${missing}</strong>.`;
}

function renderOfficial(info) {
  const box = $("officialSummary");
  const list = $("officialList");
  if (!info || !info.found) {
    box.textContent = (info && info.found === false)
      ? "No official book, manga, or anime listing found."
      : "Download a book to check Wikipedia, fansites, and Ollama web lookup.";
    list.innerHTML = "";
    return;
  }
  const bits = [];
  if (info.official_title) bits.push(info.official_title);
  if (info.available && info.available.length) bits.push("Available as " + info.available.join(", "));
  if (info.publishers && info.publishers.length) bits.push("Publishers: " + info.publishers.join(", "));
  box.textContent = bits.join(" · ") || "Official listing found.";
  list.innerHTML = (info.links || [])
    .map((link) => `<li><a href="${link.url}" target="_blank" rel="noreferrer">${link.label}</a></li>`)
    .join("");
}

async function boot() {
  const state = await window.pywebview.api.state();
  applyConfig(state.config);
  applyModels(state.models, state.config.model);
  renderLibrary(state.library);
  if (state.recommendations) renderRecommendations(state.recommendations);
  if (state.wallpaper) {
    document.body.style.setProperty("--desktop", `url("${state.wallpaper}")`);
  }
  $("log").textContent = "Ready.\n";
  setLogOpen(false);
  renderOfficial(state.official);
  renderSeries(state.series);
  renderHistory(state.url_history);
  refreshSeries();
  autoFindHeadset(Boolean(state.config && state.config.headset_host));
}

async function applyHeadsetDiscovery(res) {
  if (!res) return;
  if ($("headsetStatus")) {
    $("headsetStatus").textContent = res.message || (res.ok ? "Headset ready" : "Headset not found");
  }
  if (res.ok) {
    if (res.host && $("headsetHost")) $("headsetHost").value = res.host;
    if (res.port && $("headsetPort")) $("headsetPort").value = res.port;
    if (res.token && $("headsetToken")) $("headsetToken").value = res.token;
  }
}

async function autoFindHeadset(hasSavedHost) {
  if (!window.pywebview) return;
  if ($("headsetStatus")) {
    $("headsetStatus").textContent = hasSavedHost ? "Checking saved headset…" : "Looking for SpatialLauncher on Wi‑Fi…";
  }
  try {
    const res = hasSavedHost
      ? await window.pywebview.api.probe_headset(form())
      : await window.pywebview.api.discover_headset(form());
    await applyHeadsetDiscovery(res);
    if (!res.ok && hasSavedHost) {
      const again = await window.pywebview.api.discover_headset(form());
      await applyHeadsetDiscovery(again);
    }
  } catch (_) {
    if ($("headsetStatus")) $("headsetStatus").textContent = "Headset search failed.";
  }
}

let seriesTimer = 0;
async function refreshSeries(lookup) {
  if (!window.pywebview) return;
  const payload = { url: $("url").value, ncode: "", lookup: Boolean(lookup) };
  if (lookup) setStatus("Looking up official English title and series length…", 0.25, true);
  try {
    await window.pywebview.api.remember_url({ url: payload.url });
  } catch (_) {}
  const info = await window.pywebview.api.series_status(payload);
  renderSeries(info);
  renderHistory(info.url_history || []);
  if (lookup) setStatus(info.english_title ? `Official title: ${info.english_title}` : "Series lookup finished", 1, false);
  else if (!busy) setStatus(info.english_title || info.title || "Series info updated", null, false);
}

function scheduleSeriesRefresh() {
  clearTimeout(seriesTimer);
  seriesTimer = setTimeout(() => refreshSeries(false), 350);
}

window.addEventListener("pywebviewready", boot);
setInterval(async () => {
  if (!window.pywebview) return;
  const events = await window.pywebview.api.pull_events();
  (events || []).forEach((e) => window.onNative(e.name, e.payload));
}, 250);

$("provider").onchange = () => $("cloud").classList.toggle("hidden", $("provider").value !== "openai");
function askUser(message) {
  return new Promise((resolve) => {
    $("askText").textContent = message;
    $("ask").classList.remove("hidden");
    const finish = (value) => {
      $("ask").classList.add("hidden");
      resolve(value);
    };
    $("askKeep").onclick = () => finish("keep");
    $("askUpdate").onclick = () => finish("update");
    $("askCancel").onclick = () => finish("cancel");
  });
}

async function runJob(name) {
  const labels = { download: "Starting download…", translate: "Starting translation…" };
  setStatus(labels[name] || "Working…", 0.05, true);
  const payload = form();
  let res = await window.pywebview.api[name](payload);
  if (res && res.ok === false && res.message) {
    setStatus(res.message, 0, false);
    $("log").textContent += res.message + "\n";
    return;
  }
  if (res && res.needs_confirm) {
    const choice = await askUser(res.message);
    if (choice === "cancel") {
      $("log").textContent += "Cancelled.\n";
      setStatus("Cancelled", 0, false);
      return;
    }
    payload.confirmed = true;
    payload.overwrite = choice === "update";
    await window.pywebview.api[name](payload);
  }
}

$("download").onclick = () => runJob("download");
$("downloadAll").onclick = () => {
  $("start").value = "1";
  if (series.series_chapters) $("end").value = String(series.series_chapters);
  else $("end").value = "";
  setStatus(
    series.series_chapters
      ? `Download all: chapters 1–${series.series_chapters}`
      : "Download all chapters in the series",
    0.05,
    true
  );
  runJob("download");
};
$("url").addEventListener("change", () => refreshSeries(false));
$("url").addEventListener("paste", () => {
  setTimeout(async () => {
    try {
      const res = await window.pywebview.api.remember_url({ url: $("url").value });
      if (res && res.url_history) renderHistory(res.url_history);
    } catch (_) {}
    refreshSeries(false);
  }, 0);
});
$("url").addEventListener("input", scheduleSeriesRefresh);
$("lookupSeries").onclick = () => refreshSeries(true);
$("translate").onclick = () => runJob("translate");
$("save").onclick = () => {
  setStatus("Saving settings…", 0.4, true);
  window.pywebview.api.save_settings(form());
};
$("refresh").onclick = async () => {
  setStatus("Refreshing Ollama models…", 0.3, true);
  const res = await window.pywebview.api.refresh_models();
  applyModels(res.models, $("model").value);
};
$("browse").onclick = async () => {
  const res = await window.pywebview.api.browse_folder();
  if (res.path) $("output").value = res.path;
};
$("openEpub").onclick = () => {
  setStatus("Opening EPUB…", 0.3, true);
  window.pywebview.api.open_epub();
};
$("openSelected").onclick = () => {
  setStatus("Opening book… cleaning pages if needed", 0.2, true);
  window.pywebview.api.open_selected(selected);
};
$("findHeadset").onclick = async () => {
  setStatus("Looking for SpatialLauncher on Wi‑Fi…", 0.2, true);
  await window.pywebview.api.save_settings(form());
  const res = await window.pywebview.api.discover_headset(form());
  await applyHeadsetDiscovery(res);
  setStatus(res.message || (res.ok ? "Headset found" : "Headset not found"), res.ok ? 1 : 0, false);
};
$("sendHeadset").onclick = async () => {
  if (!selected) {
    setStatus("Select a translated book in the library first", 0, false);
    return;
  }
  setStatus("Sending EPUB to headset…", 0.25, true);
  await window.pywebview.api.save_settings(form());
  if (!$("headsetHost").value) {
    const found = await window.pywebview.api.discover_headset(form());
    await applyHeadsetDiscovery(found);
    if (!found.ok) {
      setStatus(found.message || "Headset not found", 0, false);
      return;
    }
    await window.pywebview.api.save_settings(form());
  }
  const res = await window.pywebview.api.send_selected(selected);
  if (res.host) await applyHeadsetDiscovery(res);
  setStatus(res.message || (res.ok ? "Sent" : "Send failed"), res.ok ? 1 : 0, false);
  if (res.message) $("log").textContent += res.message + "\n";
};
$("logToggle").onclick = () => setLogOpen(!$("logCard").classList.contains("open"));
$("refreshRecs").onclick = () => loadRecommendations(true);
document.querySelectorAll("[data-filter]").forEach((btn) => {
  btn.onclick = async () => {
    filter = btn.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((b) => b.classList.remove("current"));
    btn.classList.add("current");
    if (filter === "recommended") {
      showLibraryMode();
      await loadRecommendations(false);
      return;
    }
    const state = await window.pywebview.api.state();
    renderLibrary(state.library);
  };
});
document.querySelectorAll("[data-act]").forEach((btn) => {
  btn.onclick = () => {
    if (btn.dataset.act === "open") $("openEpub").click();
    if (btn.dataset.act === "translate") $("translate").click();
    if (btn.dataset.act === "save") $("save").click();
  };
});
