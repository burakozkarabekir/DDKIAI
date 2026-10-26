/* Sağ alt köşedeki AI Asistan sohbet penceresi. app.js'ten bağımsızdır: başka bir betikteki hata bu pencereyi bozmaz. */
(function () {
  "use strict";
  const root = document.getElementById("chatbot");
  if (!root) return;
  const win = root.querySelector(".cb-win");
  const log = root.querySelector("[data-cb-log]");
  const form = root.querySelector("[data-cb-form]");
  const input = form.querySelector("textarea");
  const sendBtn = form.querySelector(".cb-send");
  const launch = root.querySelector("[data-cb-toggle]");
  const ctxBar = root.querySelector("[data-cb-ctx]");
  const avatarSvg = root.querySelector(".cb-av").innerHTML;
  const page = root.dataset.page || location.pathname;
  const pm = page.match(/^\/projeler\/(\d+)/);
  const projectId = pm ? Number(pm[1]) : null;
  const h1 = document.querySelector(".page-head h1");
  const title = h1 ? h1.textContent.trim() : "";
  let busy = false;
  let started = false;

  // Sayfaya göre bağlam ve hazır sorular
  let ctx = "";
  let sugg = ["Hangi projeler risk altında ve neden?", "Bu hafta yönetime hangi 3 konuyu raporlamalıyım?", "Ölçümü eksik canlı projeler hangileri?"];
  if (projectId) {
    ctx = "Bu sayfa: " + title;
    sugg = ["Bu projenin son durumu ve riskleri neler?", "DT raporları ile manuel durum arasında çelişki var mı?", "Bu proje için yönetime 3 cümlelik özet yaz."];
  } else if (page.startsWith("/guvenlik/copilot")) {
    ctx = "Bu sayfa: Copilot kullanım metrikleri";
    sugg = ["Copilot benimsemesi en düşük departmanlar hangileri?", "Kullanılmayan lisanslar için ne önerirsin?", "Benimsemeyi artırmak için 30 günlük plan öner."];
  } else if (page.startsWith("/alan/")) {
    ctx = "Bu sayfa: " + title;
    sugg = ["Bu dokümanlardaki ana mesajlar neler?", "Dokümanlar arasında çelişki veya eksik var mı?", "Yönetime hangi kararlar sunulmalı?"];
  } else if (page.startsWith("/guvenlik")) {
    ctx = "Bu sayfa: AI Security";
    sugg = ["Shadow AI riskini azaltmak için ne yapmalıyız?", "Güvenlik değerlendirmesi eksik projeler hangileri?", "AI Security için aylık özet yaz."];
  }
  if (ctx) { ctxBar.textContent = ctx; ctxBar.hidden = false; }

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const scroll = () => { log.scrollTop = log.scrollHeight; };
  const mini = () => { const m = el("div", "cb-mini"); m.innerHTML = avatarSvg; return m; };

  function bubble(role, content, html) {
    const row = el("div", "cb-row " + role);
    if (role !== "user") row.appendChild(mini());
    const b = el("div", "cb-bubble" + (role === "bot" ? " prose" : ""));
    if (html) b.innerHTML = content; else b.textContent = content;
    row.appendChild(b);
    log.appendChild(row);
    scroll();
    return b;
  }

  function chips() {
    const box = el("div", "cb-chips");
    sugg.forEach((q) => {
      const c = el("button", "cb-chip", q);
      c.type = "button";
      c.addEventListener("click", () => ask(q));
      box.appendChild(c);
    });
    log.appendChild(box);
    scroll();
  }

  function welcome() {
    bubble("bot", "Merhaba! Ben AI Impact asistanıyım. Projeler, DT raporları, yönetici özetleri ve Copilot metrikleri hakkında sorularınızı yanıtlayabilirim.");
    chips();
  }

  function start() {
    if (started) return;
    started = true;
    fetch("/api/danisman/gecmis", { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : { messages: [] }))
      .then((d) => {
        const msgs = (d && d.messages) || [];
        if (!msgs.length) { welcome(); return; }
        log.appendChild(el("div", "cb-div", "Önceki konuşma"));
        msgs.forEach((m) => (m.role === "assistant" ? bubble("bot", m.html, true) : bubble("user", m.text)));
        log.appendChild(el("div", "cb-div", "Bu sayfada sorabilecekleriniz"));
        chips();
      })
      .catch(() => welcome());
  }

  function typing() {
    const row = el("div", "cb-row bot");
    row.appendChild(mini());
    const b = el("div", "cb-bubble cb-typing");
    b.setAttribute("aria-label", "Yazıyor");
    b.append(el("span"), el("span"), el("span"));
    row.appendChild(b);
    log.appendChild(row);
    scroll();
    return row;
  }

  function errorBubble(msg) {
    const b = bubble("err", msg);
    const a = el("a", "", "AI bağlantısını test et →");
    a.href = "/ayarlar#ai";
    b.appendChild(document.createElement("br"));
    b.appendChild(a);
  }

  function autosize() {
    input.style.height = "";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  async function ask(text) {
    const q = (text || "").trim();
    if (!q || busy) return;
    busy = true;
    sendBtn.disabled = true;
    log.querySelectorAll(".cb-chips").forEach((c) => c.remove());
    const asked = bubble("user", q).parentNode;
    input.value = "";
    autosize();
    const t = typing();
    try {
      const r = await fetch("/api/danisman", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question: q, page: page, project_id: projectId }),
      });
      let d;
      try { d = await r.json(); } catch (e) { d = { error: "Sunucudan beklenmeyen yanıt geldi (HTTP " + r.status + ")." }; }
      t.remove();
      if (!r.ok || d.error) errorBubble(d.error || "İstek başarısız (HTTP " + r.status + ").");
      else {
        bubble("bot", d.answer_html, true);
        log.scrollTop = Math.max(0, asked.offsetTop - 12);  // uzun yanıtta sorudan itibaren göster
      }
    } catch (e) {
      t.remove();
      errorBubble("Sunucuya ulaşılamadı. Uygulamanın çalıştığından emin olun.");
    }
    busy = false;
    sendBtn.disabled = false;
    input.focus();
  }

  function setOpen(open) {
    win.hidden = !open;
    root.classList.toggle("open", open);
    launch.setAttribute("aria-expanded", open ? "true" : "false");
    try { sessionStorage.setItem("cb-open", open ? "1" : ""); } catch (e) { /* tarayıcı izin vermiyor */ }
    if (open) { start(); setTimeout(() => input.focus(), 30); scroll(); }
  }

  launch.addEventListener("click", () => setOpen(win.hidden));
  root.querySelector("[data-cb-close]").addEventListener("click", () => setOpen(false));
  root.querySelector("[data-cb-new]").addEventListener("click", () => {
    fetch("/api/danisman/temizle", { method: "POST" }).catch(() => {});
    log.innerHTML = "";
    welcome();
    input.focus();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !win.hidden) setOpen(false); });
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
  });
  input.addEventListener("input", autosize);
  try { if (sessionStorage.getItem("cb-open")) setOpen(true); } catch (e) { /* yok */ }
})();
