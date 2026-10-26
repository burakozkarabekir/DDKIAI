// AI Impact Merkezi — istemci davranışları (CSP gereği satır içi script kullanılmaz)
(function () {
  // Tema
  try {
    const t = localStorage.getItem("theme");
    if (t) document.documentElement.dataset.theme = t;
  } catch (e) { /* depolama kapalı olabilir */ }
  document.addEventListener("click", (e) => {
    const tg = e.target.closest("[data-theme-toggle]");
    if (!tg) return;
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (err) { /* yok say */ }
  });

  // Mobil menü
  document.addEventListener("click", (e) => {
    const nav = document.querySelector(".nav");
    if (e.target.closest("[data-menu]")) { nav.classList.toggle("open"); return; }
    if (nav && nav.classList.contains("open") && !e.target.closest(".nav")) nav.classList.remove("open");
  });

  // Onay isteyen formlar
  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) { e.preventDefault(); return; }
    const btn = e.target.querySelector("[data-busy]");
    if (btn) { btn.disabled = true; btn.textContent = btn.dataset.busy; }
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-print]")) { e.preventDefault(); window.print(); }
  });

  // Otomatik gönderen filtreler
  document.querySelectorAll("[data-autosubmit]").forEach((el) =>
    el.addEventListener("change", () => el.form.submit()));

  // Grafik tooltip
  const tip = document.createElement("div");
  tip.className = "tooltip";
  document.body.appendChild(tip);
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) { tip.classList.remove("on"); return; }
    tip.textContent = t.dataset.tip;
    tip.classList.add("on");
  });
  document.addEventListener("mousemove", (e) => {
    if (!tip.classList.contains("on")) return;
    const x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px";
    tip.style.top = (e.clientY - 34) + "px";
  });

  // İşlenen dokümanlar / arka plan işleri bitince sayfayı yenile
  const docs = document.querySelector("[data-poll-docs]");
  if (docs && docs.dataset.pollDocs) {
    const poll = () => fetch(`/api/dokumanlar/durum?ids=${docs.dataset.pollDocs}`).then((r) => r.json()).then((d) => {
      if (!d.pending) location.reload(); else setTimeout(poll, 3000);
    }).catch(() => setTimeout(poll, 8000));
    setTimeout(poll, 2500);
  }
  const job = document.querySelector("[data-poll-job]");
  if (job) {
    const poll = () => fetch(`/api/is/${job.dataset.pollJob}`).then((r) => r.json()).then((d) => {
      if (d.status === "tamam" || d.status === "hata" || !d.status) location.reload(); else setTimeout(poll, 3000);
    }).catch(() => setTimeout(poll, 8000));
    setTimeout(poll, 2500);
  }

  // Sürükle-bırak yükleme alanı
  document.querySelectorAll(".drop").forEach((zone) => {
    const input = zone.querySelector("input[type=file]");
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("over")));
    zone.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; });
  });

  // AI danışman sohbeti
  const form = document.querySelector("#chat-form");
  if (form) {
    const log = document.querySelector("#chat-log");
    const input = form.querySelector("textarea");
    const scroll = () => { log.scrollTop = log.scrollHeight; };
    scroll();
    const add = (cls, html, isText) => {
      const div = document.createElement("div");
      div.className = "msg " + cls + (cls === "assistant" ? " prose" : "");
      if (isText) div.textContent = html; else div.innerHTML = html;
      log.appendChild(div);
      scroll();
      return div;
    };
    const ask = (q) => {
      if (!q.trim()) return;
      const empty = log.querySelector(".empty");
      if (empty) empty.remove();
      add("user", q, true);
      input.value = "";
      const wait = add("assistant thinking", "Danışman düşünüyor…", true);
      fetch("/api/danisman", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) })
        .then((r) => r.json())
        .then((d) => {
          wait.classList.remove("thinking");
          if (d.error) wait.textContent = d.error; else wait.innerHTML = d.answer_html;
          scroll();
        })
        .catch(() => { wait.textContent = "Bağlantı hatası."; });
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); }
    });
    document.querySelectorAll("[data-ask]").forEach((c) => c.addEventListener("click", () => ask(c.dataset.ask)));
  }

  // Toplu durum girişi: değişen satırı vurgula
  document.querySelectorAll(".bulk-table [data-row]").forEach((tr) => {
    tr.addEventListener("input", () => tr.classList.add("changed"));
    tr.addEventListener("change", () => tr.classList.add("changed"));
  });

  // Seçili satırları işaretle/kaldır
  document.querySelectorAll("[data-check-all]").forEach((box) => box.addEventListener("change", () => {
    document.querySelectorAll(box.dataset.checkAll).forEach((c) => { c.checked = box.checked; });
  }));

  // Sayaçlar: data-count="123.4" olan öğeler görünür olunca sıfırdan sayar
  const counters = document.querySelectorAll("[data-count]");
  if (counters.length) {
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const fmt = (v, dec) => v.toLocaleString("tr-TR", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const run = (el) => {
      const target = parseFloat(el.dataset.count);
      if (isNaN(target)) return;
      const dec = (el.dataset.count.split(".")[1] || "").length;
      const pre = el.dataset.prefix || "", suf = el.dataset.suffix || "";
      if (reduce) { el.textContent = pre + fmt(target, dec) + suf; return; }
      const t0 = performance.now(), dur = 1100;
      const step = (t) => {
        const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        el.textContent = pre + fmt(target * e, dec) + suf;
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { run(en.target); io.unobserve(en.target); } }));
      counters.forEach((c) => io.observe(c));
    } else counters.forEach(run);
  }
})();
