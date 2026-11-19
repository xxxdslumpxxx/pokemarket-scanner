(() => {
  const $ = (id) => document.getElementById(id);
  const DB_NAME = "pokemarket_local_db";
  const STORE_NAME = "saved_cards";

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE_NAME)) {
          req.result.createObjectStore(STORE_NAME, { keyPath: "id" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function dbGetAll() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const req = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve((req.result || []).sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0)));
      req.onerror = () => reject(req.error);
    });
  }

  async function dbPut(entry) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(entry);
      tx.oncomplete = () => resolve(entry);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function dbDelete(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }

  const state = {
    view: "scan",
    prevTab: "scan",
    result: null,       // CardInfoResponse corrente
    photoBlob: null,    // foto dell'utente (per salvare)
    photoUrl: null,     // URL mostrabile della foto
    savedId: null,      // se il risultato viene dalle salvate
    readIdent: null,    // cosa ha letto l'OCR dalla foto
  };

  // ---------- utilità ----------
  const eur = (v) =>
    v === null || v === undefined || Number.isNaN(Number(v))
      ? "–"
      : `€ ${Number(v).toFixed(2).replace(".", ",")}`;

  let toastTimer;
  function toast(msg, isErr = false) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (isErr ? " err" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3500);
  }

  function show(view) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    $(`view-${view}`).classList.add("active");
    state.view = view;
    const isTab = ["scan", "search", "saved"].includes(view);
    if (isTab) state.prevTab = view;
    document.querySelectorAll(".bottom-nav button").forEach((b) =>
      b.classList.toggle("active", b.dataset.nav === (isTab ? view : state.prevTab))
    );
    $("btn-back").hidden = view !== "result";
    window.scrollTo({ top: 0 });
    if (view === "saved") loadSaved();
  }

  async function apiJson(resp) {
    let data = {};
    try { data = await resp.json(); } catch {}
    if (!resp.ok) throw new Error(data.detail || `Errore ${resp.status}`);
    return data;
  }

  // ---------- immagini ----------
  function resizeImage(file, maxDim = 960) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        let { naturalWidth: w, naturalHeight: h } = img;
        const r = Math.min(1, maxDim / Math.max(w, h));
        w = Math.round(w * r);
        h = Math.round(h * r);
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        c.getContext("2d").drawImage(img, 0, 0, w, h);
        c.toBlob((b) => (b ? resolve(b) : reject(new Error("Foto non valida"))), "image/jpeg", 0.82);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Foto non valida")); };
      img.src = url;
    });
  }

  function setImg(el, url, fallbackText) {
    if (url) {
      el.src = url;
      el.onerror = () => {
        if (url.endsWith(".webp")) el.src = url.replace(/\.webp$/, ".png");
      };
      el.style.visibility = "visible";
    } else {
      el.removeAttribute("src");
      el.style.visibility = fallbackText ? "visible" : "hidden";
    }
  }

  // ---------- scansione ----------
  async function handleFile(file) {
    if (!file) return;
    try {
      const blob = await resizeImage(file);
      if (state.photoUrl && state.photoUrl.startsWith("blob:")) URL.revokeObjectURL(state.photoUrl);
      state.photoBlob = blob;
      state.photoUrl = URL.createObjectURL(blob);
      state.savedId = null;
      $("loading-photo").src = state.photoUrl;
      $("loading-text").textContent = "Leggo la carta…";
      show("loading");
      const stepTimer = setTimeout(() => ($("loading-text").textContent = "Cerco su Cardmarket…"), 1500);

      const fd = new FormData();
      fd.append("file", blob, "carta.jpg");
      try {
        const data = await apiJson(await fetch("/api/scan", { method: "POST", body: fd }));
        state.readIdent = data.identification;
        renderResult(data);
      } finally {
        clearTimeout(stepTimer);
      }
    } catch (e) {
      show("scan");
      toast(e.message || "Errore durante la scansione", true);
    }
  }

  // ---------- risultato ----------
  function renderResult(data) {
    state.result = data;
    show("result");

    setImg($("res-card-img"), data.image_url);
    $("res-photo-wrap").hidden = !state.photoUrl;
    if (state.photoUrl) setImg($("res-photo-img"), state.photoUrl);

    $("res-name").textContent = data.card_name || "Carta non trovata";
    const setParts = [data.set_name, data.card_number ? `#${data.card_number}` : null].filter(Boolean);
    $("res-set").textContent = setParts.join(" • ") || "Set non identificato";
    const sym = $("res-set-symbol");
    if (data.set_symbol_url) { sym.src = data.set_symbol_url; sym.hidden = false; } else sym.hidden = true;

    const chips = $("res-chips");
    chips.innerHTML = "";
    const ident = state.readIdent || data.identification || {};
    const read = [ident.set_name, ident.card_number ? (ident.total_in_set ? `${ident.card_number}/${ident.total_in_set}` : ident.card_number) : null]
      .filter(Boolean).join(" ");
    const chipTexts = [];
    if (read) chipTexts.push(`🔖 Letto: ${read}`);
    if (ident.language && ident.language !== "N/D") chipTexts.push(`🌐 ${ident.language}`);
    if (data.rarity) chipTexts.push(data.rarity);
    if (data.hp) chipTexts.push(`${data.hp} PS`);
    (data.types || []).forEach((t) => chipTexts.push(t));
    chipTexts.forEach((t) => {
      const s = document.createElement("span");
      s.className = "chip";
      s.textContent = t;
      chips.appendChild(s);
    });

    const tm = data.timings || {};
    const tParts = [];
    if (tm.ocr_ms) tParts.push(`lettura ${(tm.ocr_ms / 1000).toFixed(1)}s`);
    if (tm.lookup_ms) tParts.push(`ricerca ${(tm.lookup_ms / 1000).toFixed(1)}s`);
    $("res-match").textContent = [data.match_info, tParts.join(" · ")].filter(Boolean).join(" — ");

    const p = data.prices || {};
    $("price-low").textContent = eur(p.lowest_price);
    $("price-avg").textContent = eur(p.average_price);
    $("price-trend").textContent = p.trend_price != null ? `Trend ${eur(p.trend_price)}` : "";
    $("price-high").textContent = eur(p.highest_price);
    $("price-avg1").textContent = eur(p.avg1);
    $("price-avg7").textContent = eur(p.avg7);
    $("price-avg30").textContent = eur(p.avg30);
    $("price-rev-low").textContent = eur(p.reverse_holo_low);
    $("price-rev-trend").textContent = eur(p.reverse_holo_trend);
    $("res-rarity").textContent = data.rarity || "–";
    $("res-extra").textContent = [data.artist ? `Illustratore: ${data.artist}` : null, data.data_source].filter(Boolean).join(" • ");

    $("res-cm-link").href = data.cardmarket_url || "https://www.cardmarket.com/it/Pokemon";

    const saveBtn = $("btn-save");
    saveBtn.hidden = !!state.savedId;
    saveBtn.disabled = false;
    saveBtn.classList.remove("saved");
    saveBtn.textContent = "⭐ Salva";
    $("btn-delete").hidden = !state.savedId;

    const alts = data.alternatives || [];
    $("alt-section").hidden = alts.length === 0 || !!state.savedId;
    const list = $("alt-list");
    list.innerHTML = "";
    alts.forEach((a) => {
      const b = document.createElement("button");
      b.className = "alt-item";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = a.name || "";
      if (a.image_url) img.src = a.image_url;
      const s = document.createElement("span");
      s.textContent = [a.set_name, a.card_number ? `#${a.card_number}` : null].filter(Boolean).join(" ");
      b.append(img, s);
      b.addEventListener("click", () => chooseAlternative(a.tcgdex_id));
      list.appendChild(b);
    });
  }

  async function chooseAlternative(id) {
    if (!id) return;
    try {
      $("loading-text").textContent = "Carico la versione scelta…";
      $("loading-photo").src = state.photoUrl || "";
      show("loading");
      const prevAlts = (state.result && state.result.alternatives) || [];
      const prevMain = state.result;
      const data = await apiJson(await fetch(`/api/card/${encodeURIComponent(id)}`));
      // Mantieni le altre alternative (inclusa la carta proposta prima)
      const others = prevAlts.filter((a) => a.tcgdex_id !== id);
      if (prevMain && prevMain.tcgdex_id) {
        others.unshift({
          tcgdex_id: prevMain.tcgdex_id,
          name: prevMain.card_name,
          set_name: prevMain.set_name,
          card_number: prevMain.card_number,
          image_url: prevMain.image_url ? prevMain.image_url.replace("/high.", "/low.") : null,
        });
      }
      data.alternatives = others;
      data.match_info = "Versione scelta da te";
      renderResult(data);
    } catch (e) {
      show("result");
      toast(e.message, true);
    }
  }

  async function saveCurrent() {
    if (!state.result) return;
    const btn = $("btn-save");
    btn.disabled = true;
    try {
      const card = { ...state.result, identification: state.readIdent || state.result.identification };
      const entry = {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        saved_at: Date.now() / 1000,
        card,
        photoBlob: state.photoBlob || null,
      };
      await dbPut(entry);
      btn.textContent = "✓ Salvata";
      btn.classList.add("saved");
      toast("Carta salvata sul telefono con la tua foto ⭐");
    } catch (e) {
      btn.disabled = false;
      toast(e.message || "Errore salvataggio locale", true);
    }
  }

  async function deleteCurrent() {
    if (!state.savedId || !confirm("Eliminare questa carta dalle salvate?")) return;
    try {
      await dbDelete(state.savedId);
      toast("Eliminata");
      state.savedId = null;
      show("saved");
    } catch (e) {
      toast(e.message || "Errore eliminazione", true);
    }
  }

  // ---------- ricerca manuale ----------
  async function manualSearch(ev) {
    ev.preventDefault();
    const name = $("input-name").value.trim();
    if (!name) return;
    const params = new URLSearchParams({ name });
    const num = $("input-number").value.trim();
    const set = $("input-set").value.trim();
    if (num) params.set("number", num);
    if (set) params.set("set_name", set);
    state.photoBlob = null;
    state.photoUrl = null;
    state.savedId = null;
    state.readIdent = null;
    $("loading-photo").removeAttribute("src");
    $("loading-text").textContent = "Cerco su Cardmarket…";
    show("loading");
    try {
      renderResult(await apiJson(await fetch(`/api/search?${params}`)));
    } catch (e) {
      show("search");
      toast(e.message, true);
    }
  }

  // ---------- salvate (IndexedDB locale sul telefono) ----------
  async function loadSaved() {
    const list = $("saved-list");
    try {
      const items = await dbGetAll();
      list.innerHTML = "";
      let total = 0;
      items.forEach((it) => {
        const c = it.card || {};
        const price = c.prices ? c.prices.average_price ?? c.prices.trend_price : null;
        if (price) total += Number(price);
        const row = document.createElement("div");
        row.className = "saved-item";
        const ph = document.createElement("img");
        const localPhotoUrl = it.photoBlob ? URL.createObjectURL(it.photoBlob) : null;
        if (localPhotoUrl) ph.src = localPhotoUrl;
        const ci = document.createElement("img");
        if (c.image_url) ci.src = c.image_url.replace("/high.", "/low.");
        const info = document.createElement("div");
        const t = document.createElement("div");
        t.className = "t";
        t.textContent = c.card_name || "Carta";
        const s = document.createElement("div");
        s.className = "s";
        const d = new Date((it.saved_at || 0) * 1000);
        s.textContent = [c.set_name, c.card_number ? `#${c.card_number}` : null, d.toLocaleDateString("it-IT")].filter(Boolean).join(" • ");
        info.append(t, s);
        const p = document.createElement("div");
        p.className = "p";
        p.textContent = eur(price);
        row.append(ph, ci, info, p);
        row.addEventListener("click", () => {
          state.savedId = it.id;
          state.photoBlob = it.photoBlob || null;
          state.photoUrl = it.photoBlob ? URL.createObjectURL(it.photoBlob) : null;
          state.readIdent = c.identification || null;
          renderResult(c);
        });
        list.appendChild(row);
      });
      $("saved-count").textContent = String(items.length);
      $("saved-total").textContent = eur(total);
      if (!items.length) list.innerHTML = '<div class="empty">Nessuna carta salvata.<br>Scansiona una carta e premi ⭐ Salva.</div>';
    } catch (e) {
      list.innerHTML = `<div class="empty">Errore: ${e.message}</div>`;
    }
  }

  // ---------- eventi ----------
  ["input-camera", "input-gallery"].forEach((id) =>
    $(id).addEventListener("change", (e) => {
      handleFile(e.target.files && e.target.files[0]);
      e.target.value = "";
    })
  );
  document.querySelectorAll(".bottom-nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.nav)));
  $("btn-back").addEventListener("click", () => show(state.prevTab));
  $("btn-new-scan").addEventListener("click", () => show("scan"));
  $("btn-save").addEventListener("click", saveCurrent);
  $("btn-delete").addEventListener("click", deleteCurrent);
  $("search-form").addEventListener("submit", manualSearch);
  ["res-card-img", "res-photo-img"].forEach((id) =>
    $(id).addEventListener("click", (e) => {
      if (!e.target.src) return;
      $("lightbox-img").src = e.target.src.replace("/low.", "/high.");
      $("lightbox").hidden = false;
    })
  );
  $("lightbox").addEventListener("click", () => ($("lightbox").hidden = true));

  fetch("/api/status")
    .then((r) => r.json())
    .then((d) => { $("source-badge").textContent = "ONNX pronto"; })
    .catch(() => { const b = $("source-badge"); b.textContent = "Offline"; b.classList.add("warn"); });
})();
