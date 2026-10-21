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

  // Rapor analizi bekleniyorsa durumu yokla
  const pending = document.querySelector("[data-report-pending]");
  if (pending) {
    const id = pending.dataset.reportPending;
    const poll = () => fetch(`/api/raporlar/${id}/durum`).then((r) => r.json()).then((d) => {
      if (d.status === "tamam" || d.status === "hata") location.reload();
      else setTimeout(poll, 3000);
    }).catch(() => setTimeout(poll, 6000));
    setTimeout(poll, 2500);
  }

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

  // Seçili satırları işaretle/kaldır
  document.querySelectorAll("[data-check-all]").forEach((box) => box.addEventListener("change", () => {
    document.querySelectorAll(box.dataset.checkAll).forEach((c) => { c.checked = box.checked; });
  }));
})();
