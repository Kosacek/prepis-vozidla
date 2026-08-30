// Shared inline úkon-edit modal (dashboard + /ukony list).
// Clicking any a.recent-row edit link opens its form fragment (?modal=1) in a
// blurred overlay instead of navigating away. Saving submits normally (full
// reload via the form's hidden `back`, so the page reflects the change). Falls
// back to the plain edit page when the fetch fails or JS is off (real links).
// Extracted from dashboard.js so the /ukony list gets the exact same behavior;
// delegation is document-level, covering rows swapped in by either search box.
(function () {
  var modal = document.getElementById("ukon-modal");
  var modalBody = document.getElementById("ukon-modal-body");
  if (!modal || !modalBody) return;
  var lastFocused = null;

  function openModal(url) {
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        // Non-OK (e.g. the úkon was deleted meanwhile) → fall back to plain
        // navigation via .catch instead of rendering an error page in the modal.
        if (!r.ok) throw new Error("modal " + r.status);
        return r.text();
      })
      .then(function (html) {
        modalBody.innerHTML = html;
        lastFocused = document.activeElement;
        modal.hidden = false;
        // Reserve the width the scrollbar occupied before overflow:hidden hides
        // it, so locking background scroll doesn't shift the page sideways.
        var sbw = window.innerWidth - document.documentElement.clientWidth;
        document.body.classList.add("modal-open");
        if (sbw > 0) document.body.style.paddingRight = sbw + "px";
        requestAnimationFrame(function () {
          modal.classList.add("is-open");
          // Skip the hidden `back` input — focusing it silently does nothing,
          // so the intended "cursor in first field" never happened.
          var first = modalBody.querySelector("input:not([type=hidden]), select, button");
          if (first) first.focus();
        });
      })
      .catch(function () { window.location.href = url.replace(/[?&]modal=1/, ""); });
  }

  function closeModal() {
    modal.classList.remove("is-open");
    document.body.classList.remove("modal-open");
    document.body.style.paddingRight = "";
    setTimeout(function () { modal.hidden = true; modalBody.innerHTML = ""; }, 280);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  // Open — delegated on document so it covers the dashboard recent list, the
  // /ukony list, and any rows swapped in later by a live search.
  document.addEventListener("click", function (e) {
    var row = e.target.closest("a.recent-row");
    if (!row) return;
    var href = row.getAttribute("href");
    if (!href || href.indexOf("/upravit") < 0) return;
    e.preventDefault();
    openModal(href + (href.indexOf("?") >= 0 ? "&" : "?") + "modal=1");
  });

  // Uložení BEZ přenačtení stránky: pošleme formulář fetchem a vyměníme jen
  // ten jeden řádek. Reload jinak shodil rozepsané hledání i filtry — a při
  // doplňování SPZ po jednom autě to bylo nepoužitelné.
  function swapRow(uid, data) {
    var link = document.querySelector('a.recent-row[href*="/ukony/' + uid + '/upravit"]');
    if (!link) return false;
    var tmp = document.createElement("div");
    tmp.innerHTML = (data.html || "").trim();
    var fresh = tmp.querySelector("a.recent-row");
    if (!fresh) return false;
    var item = link.closest(".ukony-item");
    link.parentNode.replaceChild(fresh, link);
    if (item) {
      // /ukony/vse drží v obalu index pro hledání a cenu pro živý součet
      if (data.search != null) item.setAttribute("data-search", data.search);
      if (data.celkem != null) item.setAttribute("data-kc", data.celkem);
      if (window.ukonySyncRow) window.ukonySyncRow(item);
    }
    fresh.classList.add("row-saved");
    setTimeout(function () { fresh.classList.remove("row-saved"); }, 1200);
    return true;
  }

  modalBody.addEventListener("submit", function (e) {
    var form = e.target.closest("form");
    if (!form) return;
    var m = /\/ukony\/(\d+)\/upravit/.exec(form.getAttribute("action") || "");
    if (!m) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    fetch(form.action, {
      method: "POST", body: new FormData(form),
      headers: { "X-Requested-With": "fetch" }
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d.ok) throw new Error((res.d && res.d.error) || "chyba");
        if (!swapRow(m[1], res.d)) { window.location.reload(); return; }
        closeModal();
      })
      .catch(function () {
        // cokoliv nečekaného → klasické odeslání, ať se změna nikdy neztratí
        if (btn) btn.disabled = false;
        form.submit();
      });
  });

  // Close — backdrop click, the × button, or the form's "Zpět" link.
  modal.addEventListener("click", function (e) {
    if (e.target === modal || e.target.closest("[data-modal-close]")) {
      e.preventDefault();
      closeModal();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
})();
