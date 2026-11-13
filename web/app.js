/* Niimparty — página do convidado (JS puro, sem build). */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let S = {};            // textos do idioma
  let info = null;
  let jobId = null;
  let source = null;     // EventSource
  let pollTimer = null;

  const tr = (key, vars = {}) =>
    (S[key] || key).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));

  function show(name) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.toggle("active", el.id === `screen-${name}`));
    window.scrollTo({ top: 0 });
  }

  function busy(key) {
    $("busy-text").textContent = tr(key);
    show("busy");
  }

  function fail(message) {
    $("error-text").textContent = message || tr("error_unknown");
    show("error");
  }

  // ---------------------------------------------------------- início

  async function init() {
    try {
      const res = await fetch("/api/info", { cache: "no-store" });
      info = await res.json();
    } catch {
      document.body.classList.add("offline");
      return;
    }
    S = info.strings || {};
    document.documentElement.lang = S.html_lang || info.lang || "pt-BR";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = tr(el.dataset.i18n); });
    const name = info.event.name || S.page_title;
    $("event-name").textContent = name;
    document.title = name;
    $("sample").alt = info.template.name;
    $("preview").alt = tr("preview_title");

    if (info.guest.enabled) {
      $("guest-wrap").classList.remove("hidden");
      $("guest-label").textContent = info.guest.label;
      $("guest-name").maxLength = info.guest.max_chars;
      try { $("guest-name").value = localStorage.getItem("niimparty-name") || ""; } catch { /* sem storage */ }
    }
  }

  // ---------------------------------------------------------- envio

  /** Reduz fotos grandes no próprio celular para enviar mais rápido. */
  async function shrink(file) {
    const MAX = 2400;
    if (!window.createImageBitmap || file.size < 1.5 * 1024 * 1024) return file;
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, MAX / Math.max(bmp.width, bmp.height));
      if (scale === 1 && file.type === "image/jpeg") { bmp.close?.(); return file; }
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close?.();
      const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.9));
      return blob && blob.size < file.size ? new File([blob], "foto.jpg", { type: "image/jpeg" }) : file;
    } catch {
      return file; // ex.: HEIC em navegador sem suporte: o servidor converte
    }
  }

  async function onFile(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    busy("sending");
    const guest = $("guest-name").value.trim();
    try { if (guest) localStorage.setItem("niimparty-name", guest); } catch { /* ok */ }

    const body = new FormData();
    body.append("photo", await shrink(file));
    body.append("guest_name", guest);
    let res;
    try {
      res = await fetch("/upload", { method: "POST", body });
    } catch {
      return fail(tr("error_network"));
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return fail(data.message);
    jobId = data.id;
    busy("preparing");
    const img = $("preview");
    img.onload = () => show("preview");
    img.onerror = () => fail(tr("error_unknown"));
    img.src = `${data.preview}?t=${Date.now()}`;
  }

  // ---------------------------------------------------------- fila

  async function onPrint() {
    if (!jobId) return;
    $("btn-print").disabled = true;
    let res;
    try {
      res = await fetch(`/print/${jobId}`, { method: "POST" });
    } catch {
      $("btn-print").disabled = false;
      return fail(tr("error_network"));
    }
    $("btn-print").disabled = false;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return fail(data.message);
    renderStatus(data);
    show("queue");
    follow(jobId);
  }

  function renderStatus(st) {
    const badge = $("queue-badge");
    const note = $("queue-note");
    badge.classList.remove("done");
    $("btn-again").classList.add("hidden");
    note.classList.add("hidden");

    if (st.status === "done") {
      badge.textContent = "✓";
      badge.classList.add("done");
      $("queue-text").textContent = tr("done");
      $("btn-again").classList.remove("hidden");
      if (navigator.vibrate) navigator.vibrate(120);
      return;
    }
    if (st.status === "error") {
      fail(tr("error_unknown"));
      return;
    }
    if (st.status === "printing") {
      badge.textContent = "⎙";
      $("queue-text").textContent = tr("printing_now");
    } else {
      const n = st.position || 1;
      badge.textContent = String(n);
      $("queue-text").textContent = n <= 1 ? tr("queue_next") : tr("queue_position", { n });
    }
    if (st.error) {
      note.textContent = tr(`error_${st.error}`);
      note.classList.remove("hidden");
    } else if (st.paused) {
      note.textContent = tr("paused");
      note.classList.remove("hidden");
    }
  }

  function stopFollowing() {
    if (source) { source.close(); source = null; }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function follow(id) {
    stopFollowing();
    const finished = (st) => ["done", "error", "cancelled"].includes(st.status);
    if ("EventSource" in window) {
      source = new EventSource(`/status/${id}`);
      source.onmessage = (ev) => {
        const st = JSON.parse(ev.data);
        renderStatus(st);
        if (finished(st)) stopFollowing();
      };
      source.onerror = () => {   // rede instável: cai para consulta periódica
        if (source) { source.close(); source = null; }
        poll(id, finished);
      };
    } else {
      poll(id, finished);
    }
  }

  function poll(id, finished) {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/job/${id}`, { cache: "no-store" });
        if (!res.ok) return;
        const st = await res.json();
        renderStatus(st);
        if (finished(st)) stopFollowing();
      } catch { /* tenta de novo */ }
    }, 2000);
  }

  function restart() {
    stopFollowing();
    jobId = null;
    show("start");
  }

  // ---------------------------------------------------------- eventos

  $("input-camera").addEventListener("change", onFile);
  $("input-gallery").addEventListener("change", onFile);
  $("btn-print").addEventListener("click", onPrint);
  $("btn-change").addEventListener("click", restart);
  $("btn-again").addEventListener("click", restart);
  $("btn-retry").addEventListener("click", restart);

  init();
})();
