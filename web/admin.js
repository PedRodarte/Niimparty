/* Niimparty — painel do organizador (JS puro, sem build). */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let S = {};
  let lang = "pt-BR";
  let state = null;        // resposta de /admin/api/state
  let draft = null;        // configuração sendo editada
  let testPhoto = null;    // foto de teste (Blob), só para a prévia
  let previews = [];
  let colorIdx = 0;
  let previewTimer = null;
  let previewCtrl = null;
  let pollTimer = null;
  let activeTab = "label";
  let loggedIn = false;

  const tr = (key, vars = {}) =>
    (S[key] || key).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const editable = (cfg) => ({
    template: cfg.template,
    event: { name: cfg.event?.name || "", date: cfg.event?.date || "" },
    texts: { ...(cfg.texts || {}) },
    guest_name: !!cfg.guest_name,
    label: { width_mm: Number(cfg.label.width_mm), height_mm: Number(cfg.label.height_mm) },
    paper: cfg.paper,
  });
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  class AuthError extends Error {}

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, { cache: "no-store", credentials: "same-origin", ...opts });
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw new Error(tr("adm_network"));
    }
    if (res.status === 401 && path !== "/admin/api/login") {
      showLogin(loggedIn ? tr("adm_session_expired") : "");
      loggedIn = false;
      throw new AuthError();
    }
    const type = res.headers.get("content-type") || "";
    const body = type.includes("json") ? await res.json() : null;
    if (!res.ok) throw new Error((body && body.message) || tr("error_unknown"));
    return body;
  }

  function applyStrings() {
    document.documentElement.lang = S.html_lang || lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = tr(el.dataset.i18n); });
    document.title = tr("adm_title") + " · Niimparty";
  }

  // ------------------------------------------------------------ login

  function showLogin(message) {
    stopPolling();
    $("panel").classList.add("hidden");
    $("login").classList.remove("hidden");
    const err = $("login-error");
    err.textContent = message || "";
    err.classList.toggle("hidden", !message);
    $("pin").value = "";
    $("pin").focus();
  }

  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/admin/api/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: $("pin").value }),
      });
      await openPanel();
    } catch (e) {
      if (!(e instanceof AuthError)) showLogin(e.message);
    }
  });

  $("logout").addEventListener("click", async () => {
    try { await api("/admin/api/logout", { method: "POST" }); } catch { /* tanto faz */ }
    showLogin();
  });

  // ------------------------------------------------------------ painel

  async function openPanel() {
    state = await api("/admin/api/state");
    loggedIn = true;
    draft = editable(state.config);
    $("login").classList.add("hidden");
    $("panel").classList.remove("hidden");
    $("guest-link").href = state.url || "/";
    renderForm();
    renderQueueState(state.queue);
    $("driver-note").classList.toggle("hidden", state.driver !== "mock");
    schedulePreview(0);
    startPolling();
    const fromHash = Object.keys(TAB_HASH).find((k) => TAB_HASH[k] === location.hash);
    if (fromHash) selectTab(document.querySelector(`.tab[data-tab=${fromHash}]`));
  }

  const TAB_HASH = { label: "#etiqueta", queue: "#fila", photos: "#fotos" };

  function selectTab(tab) {
    activeTab = tab.dataset.tab;
    history.replaceState(null, "", TAB_HASH[activeTab]);
    document.querySelectorAll(".tab").forEach((t) => {
      const on = t === tab;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("active", b.id === `tab-${activeTab}`));
    if (activeTab === "queue") { lastJobsKey = ""; refreshJobs(); }
  }

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => selectTab(tab)));

  // ------------------------------------------------------------ formulário

  const currentTemplate = () => state.templates.find((t) => t.id === draft.template) || state.templates[0];

  function renderForm() {
    // modelos
    const grid = $("templates");
    grid.textContent = "";
    for (const t of state.templates) {
      const label = document.createElement("label");
      label.className = "tpl";
      label.title = t.description || t.name;
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "template";
      input.value = t.id;
      input.checked = t.id === draft.template;
      input.addEventListener("change", () => selectTemplate(t.id));
      const img = document.createElement("img");
      img.src = t.thumb;
      img.alt = "";
      const name = document.createElement("span");
      name.textContent = t.name;
      label.append(input, img, name);
      grid.append(label);
    }
    $("event-name").value = draft.event.name;
    $("event-date").value = draft.event.date;
    renderTemplateFields();
    updateDirty();
  }

  function renderTemplateFields() {
    const t = currentTemplate();
    // textos
    const box = $("texts");
    box.textContent = "";
    for (const spec of t.texts) {
      const label = document.createElement("label");
      label.className = "field";
      const span = document.createElement("span");
      span.textContent = spec.label;
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = spec.max_chars;
      input.placeholder = spec.default;
      input.value = draft.texts[spec.id] ?? "";
      input.addEventListener("input", () => {
        if (input.value.trim()) draft.texts[spec.id] = input.value;
        else delete draft.texts[spec.id];
        changed();
      });
      label.append(span, input);
      box.append(label);
    }
    $("texts-card").classList.toggle("hidden", !t.texts.length && !t.guest);
    $("guest").checked = draft.guest_name && t.guest;
    $("guest").disabled = !t.guest;
    $("guest-wrap").classList.toggle("hidden", !t.guest);
    $("guest-unsupported").classList.toggle("hidden", t.guest);

    // tamanho
    const fixed = t.label_mm;
    $("size-chips").classList.toggle("hidden", !!fixed);
    $("size-custom").classList.toggle("hidden", !!fixed);
    $("size-fixed").classList.toggle("hidden", !fixed);
    if (fixed) {
      draft.label = { width_mm: fixed[0], height_mm: fixed[1] };
      $("size-fixed").textContent = tr("adm_label_fixed", { size: `${fixed[0]} × ${fixed[1]}` });
    } else {
      renderSizeChips();
    }
    $("label-w").value = draft.label.width_mm;
    $("label-h").value = draft.label.height_mm;

    // papel
    const gray = state.profile.grayscale;
    if (!gray) draft.paper = "regular";
    document.querySelectorAll("input[name=paper]").forEach((r) => {
      r.checked = r.value === draft.paper;
      r.disabled = r.value === "photo" && !gray;
    });
    $("paper-forced").classList.toggle("hidden", gray);

    // logo
    $("logo-card").classList.toggle("hidden", !t.logo);
    $("logo-remove").classList.toggle("hidden", !state.logo);
  }

  function renderSizeChips() {
    const box = $("size-chips");
    box.textContent = "";
    for (const [w, h] of state.profile.label_sizes || []) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = `${w} × ${h}`;
      b.classList.toggle("active", draft.label.width_mm === w && draft.label.height_mm === h);
      b.addEventListener("click", () => {
        draft.label = { width_mm: w, height_mm: h };
        $("label-w").value = w;
        $("label-h").value = h;
        renderSizeChips();
        changed();
      });
      box.append(b);
    }
  }

  function selectTemplate(id) {
    const before = currentTemplate();
    draft.template = id;
    const t = currentTemplate();
    // mantém só os textos com o mesmo id no modelo novo
    const ids = new Set(t.texts.map((s) => s.id));
    for (const k of Object.keys(draft.texts)) if (!ids.has(k)) delete draft.texts[k];
    if (before.label_mm && !t.label_mm) {
      // saindo de um modelo de tamanho fixo: volta ao tamanho salvo, ou ao primeiro do perfil
      const savedFixed = state.templates.find((x) => x.id === state.config.template)?.label_mm;
      const first = (state.profile.label_sizes || [[50, 80]])[0];
      draft.label = savedFixed ? { width_mm: first[0], height_mm: first[1] } : editable(state.config).label;
    }
    if (!t.guest) draft.guest_name = false;
    else if (!before.guest) draft.guest_name = true;
    renderTemplateFields();
    changed();
  }

  $("event-name").addEventListener("input", (e) => { draft.event.name = e.target.value; changed(); });
  $("event-date").addEventListener("change", (e) => { draft.event.date = e.target.value; changed(); });
  $("guest").addEventListener("change", (e) => { draft.guest_name = e.target.checked; changed(); });
  for (const [id, key] of [["label-w", "width_mm"], ["label-h", "height_mm"]]) {
    $(id).addEventListener("input", (e) => {
      const v = Number(e.target.value);
      if (v >= 5) { draft.label[key] = v; renderSizeChips(); changed(); }
    });
  }
  document.querySelectorAll("input[name=paper]").forEach((r) =>
    r.addEventListener("change", () => { draft.paper = r.value; changed(); }));

  function changed() {
    updateDirty();
    schedulePreview();
  }

  function updateDirty() {
    const dirty = !same(draft, editable(state.config));
    $("save").disabled = !dirty;
    $("discard").classList.toggle("hidden", !dirty);
    const msg = $("save-msg");
    if (dirty) { msg.textContent = tr("adm_unsaved"); msg.className = "small"; }
    else if (!msg.classList.contains("ok")) msg.textContent = "";
  }

  $("discard").addEventListener("click", () => {
    draft = editable(state.config);
    renderForm();
    schedulePreview(0);
  });

  $("save").addEventListener("click", async () => {
    const btn = $("save");
    btn.disabled = true;
    try {
      state = await api("/admin/api/config", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
      });
      draft = editable(state.config);
      const msg = $("save-msg");
      msg.textContent = tr("adm_saved");
      msg.className = "small ok";
      setTimeout(() => { if (msg.classList.contains("ok")) { msg.textContent = ""; msg.className = "small"; } }, 5000);
      renderForm();
    } catch (e) {
      if (e instanceof AuthError) return;
      $("save-msg").textContent = e.message;
      $("save-msg").className = "small err";
      btn.disabled = false;
    }
  });

  // ------------------------------------------------------------ prévia ao vivo

  function schedulePreview(delay = 350) {
    clearTimeout(previewTimer);
    $("preview-img").classList.add("stale");
    $("rendering").classList.remove("hidden");
    previewTimer = setTimeout(renderPreview, delay);
  }

  async function renderPreview() {
    if (previewCtrl) previewCtrl.abort();
    previewCtrl = new AbortController();
    const form = new FormData();
    form.append("settings", JSON.stringify(draft));
    if (testPhoto) form.append("photo", testPhoto, "teste.jpg");
    try {
      const res = await api("/admin/api/preview", { method: "POST", body: form, signal: previewCtrl.signal });
      previews = res.images;
      if (colorIdx >= previews.length) colorIdx = 0;
      showPreview();
      renderDots();
      const w = $("warnings");
      w.textContent = "";
      if (res.warnings.length) {
        const title = document.createElement("strong");
        title.textContent = tr("adm_warnings");
        const ul = document.createElement("ul");
        for (const text of res.warnings) {
          const li = document.createElement("li");
          li.textContent = text;
          ul.append(li);
        }
        w.append(title, ul);
      }
      w.classList.toggle("hidden", !res.warnings.length);
      $("preview-note").classList.toggle("hidden", !currentTemplate().label_mm);
    } catch (e) {
      if (e.name === "AbortError" || e instanceof AuthError) return;
      toast(e.message);
    } finally {
      $("rendering").classList.add("hidden");
    }
  }

  function showPreview() {
    const img = $("preview-img");
    img.src = previews[colorIdx] || "";
    img.alt = tr("adm_preview");
    img.classList.remove("stale");
  }

  function renderDots() {
    const box = $("color-dots");
    box.textContent = "";
    box.classList.toggle("hidden", previews.length < 2);
    if (previews.length < 2) return;
    // a cor de cada bolinha vem do canto da própria prévia
    previews.forEach((src, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "dot" + (i === colorIdx ? " active" : "");
      b.setAttribute("aria-label", String(i + 1));
      const probe = new Image();
      probe.onload = () => {
        const c = document.createElement("canvas");
        c.width = c.height = 1;
        const ctx = c.getContext("2d");
        ctx.drawImage(probe, 2, 2, 1, 1, 0, 0, 1, 1);
        const [r, g, bl] = ctx.getImageData(0, 0, 1, 1).data;
        b.style.background = `rgb(${r},${g},${bl})`;
      };
      probe.src = src;
      b.addEventListener("click", () => { colorIdx = i; showPreview(); renderDots(); });
      box.append(b);
    });
  }

  /** Reduz a foto de teste no navegador antes de enviar. */
  async function shrink(file, max = 1600) {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * k);
      c.height = Math.round(bmp.height * k);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      return await new Promise((ok) => c.toBlob((b) => ok(b || file), "image/jpeg", 0.88));
    } catch {
      return file; // HEIC no desktop, por exemplo: o servidor converte
    }
  }

  $("test-photo").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    testPhoto = await shrink(file);
    schedulePreview(0);
  });

  // ------------------------------------------------------------ logo

  $("logo-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("logo", file);
    try {
      await api("/admin/api/logo", { method: "POST", body: form });
      state.logo = true;
      $("logo-remove").classList.remove("hidden");
      schedulePreview(0);
    } catch (err) {
      if (!(err instanceof AuthError)) toast(err.message);
    }
  });

  $("logo-remove").addEventListener("click", async () => {
    try {
      await api("/admin/api/logo", { method: "DELETE" });
      state.logo = false;
      $("logo-remove").classList.add("hidden");
      schedulePreview(0);
    } catch (err) {
      if (!(err instanceof AuthError)) toast(err.message);
    }
  });

  // ------------------------------------------------------------ fila

  function renderQueueState(q) {
    state.queue = q;
    $("queue-state").textContent = q.paused ? tr("adm_queue_paused") : tr("adm_queue_running");
    const reason = !q.paused ? "" : q.reason === "manual" ? tr("adm_reason_manual") : tr("error_" + q.reason);
    $("queue-reason").textContent = [reason, q.length ? tr("adm_in_queue", { n: q.length }) : ""]
      .filter(Boolean).join(" · ");
    const btn = $("queue-toggle");
    btn.textContent = q.paused ? tr("adm_resume") : tr("adm_pause");
    btn.className = "btn " + (q.paused ? "btn-primary" : "btn-secondary");
    const count = $("queue-count");
    count.textContent = q.length;
    count.classList.toggle("hidden", !q.length);
    const banner = $("pause-banner");
    banner.textContent = q.paused ? `${tr("adm_queue_paused")}${reason ? " — " + reason : ""}` : "";
    banner.classList.toggle("hidden", !q.paused);
  }

  $("queue-toggle").addEventListener("click", async () => {
    try {
      const q = await api(`/admin/api/queue/${state.queue.paused ? "resume" : "pause"}`, { method: "POST" });
      renderQueueState(q);
      refreshJobs();
    } catch (e) {
      if (!(e instanceof AuthError)) toast(e.message);
    }
  });

  let lastJobsKey = "";

  async function refreshJobs() {
    let data;
    try { data = await api("/admin/api/jobs"); } catch { return; }
    renderQueueState(data.queue);
    const key = JSON.stringify(data.jobs.map((j) => [j.id, j.status, j.position, j.error]));
    if (key === lastJobsKey) return;
    lastJobsKey = key;
    const list = $("jobs");
    list.textContent = "";
    $("jobs-empty").classList.toggle("hidden", data.jobs.length > 0);
    const fmt = new Intl.DateTimeFormat(S.html_lang || lang, { hour: "2-digit", minute: "2-digit" });
    for (const j of data.jobs) {
      const li = document.createElement("li");
      li.className = "job";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = `${j.image}?s=${j.status}`;
      const meta = document.createElement("div");
      meta.className = "meta";
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = j.guest_name || "—";
      const when = document.createElement("span");
      when.className = "muted small";
      when.textContent = fmt.format(new Date((j.queued_at || j.created_at) * 1000));
      const st = document.createElement("span");
      st.className = `status ${j.status}`;
      st.textContent = tr(`adm_status_${j.status}`) + (j.status === "queued" && j.position ? ` · ${j.position}º` : "");
      meta.append(who, when, st);
      if (j.error) {
        const e = document.createElement("span");
        e.className = "muted small";
        e.textContent = tr("error_" + j.error);
        meta.append(e);
      }
      const row = document.createElement("div");
      row.className = "actions-row";
      const again = document.createElement("button");
      again.type = "button";
      again.className = "btn btn-secondary";
      again.textContent = tr("adm_reprint");
      again.disabled = j.status === "queued" || j.status === "printing";
      again.addEventListener("click", () => jobAction(j.id, "reprint"));
      const del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn-danger";
      del.textContent = tr("adm_delete");
      del.disabled = j.status === "printing";
      del.addEventListener("click", () => { if (confirm(tr("adm_confirm_delete"))) jobAction(j.id, "delete"); });
      row.append(again, del);
      li.append(img, meta, row);
      list.append(li);
    }
  }

  async function jobAction(id, action) {
    try {
      if (action === "reprint") await api(`/admin/api/jobs/${id}/reprint`, { method: "POST" });
      else await api(`/admin/api/jobs/${id}`, { method: "DELETE" });
      lastJobsKey = "";
      refreshJobs();
    } catch (e) {
      if (!(e instanceof AuthError)) toast(e.message);
    }
  }

  function startPolling() {
    stopPolling();
    refreshJobs();
    pollTimer = setInterval(() => { if (!document.hidden) refreshJobs(); }, 3000);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  // ------------------------------------------------------------ fotos

  $("delete-all").addEventListener("click", async () => {
    if (!confirm(tr("adm_confirm_delete_all"))) return;
    try {
      const res = await api("/admin/api/jobs/delete-all", { method: "POST" });
      const msg = $("photos-msg");
      msg.textContent = tr("adm_deleted", { n: res.deleted });
      msg.className = "msg msg-ok";
      lastJobsKey = "";
      refreshJobs();
    } catch (e) {
      if (!(e instanceof AuthError)) toast(e.message);
    }
  });

  // ------------------------------------------------------------ início

  async function init() {
    try {
      const res = await fetch("/admin/api/strings", { cache: "no-store" });
      const data = await res.json();
      S = data.strings;
      lang = data.lang;
    } catch { /* sem textos: mostra as chaves */ }
    applyStrings();
    try {
      await openPanel();
    } catch (e) {
      if (!(e instanceof AuthError)) showLogin(e.message);
    }
  }

  init();
})();
