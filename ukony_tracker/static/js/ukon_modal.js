// Shared úkon overlay (dashboard + full list). Edit links and the new-úkon
// button fetch their form fragments into the same dialog. Delegation covers
// rows swapped in later by search and filters.
(function () {
  var modal = document.getElementById("ukon-modal");
  var modalBody = document.getElementById("ukon-modal-body");
  if (!modal || !modalBody) return;
  var modalCard = modal.querySelector(".modal-card");
  var lastFocused = null;
  var openSerial = 0;
  var closeTimer;

  function openModal(url, isNew, isScan) {
    var serial = ++openSerial;
    clearTimeout(closeTimer);
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        // Non-OK (e.g. the úkon was deleted meanwhile) → fall back to plain
        // navigation via .catch instead of rendering an error page in the modal.
        if (!r.ok) throw new Error("modal " + r.status);
        return r.text();
      })
      .then(function (html) {
        if (serial !== openSerial) return;
        modalBody.innerHTML = html;
        modalCard.classList.toggle("modal-card--new", !!isNew);
        modalCard.classList.toggle("modal-card--scan", !!isScan);
        if (isNew) document.dispatchEvent(new CustomEvent('ukon:new-form-shown', { detail: { form: modalBody.querySelector('#ukon-form') } }));
        lastFocused = document.activeElement;
        modal.hidden = false;
        if (isScan) document.dispatchEvent(new CustomEvent('ukon:scan-shown'));
        // Reserve the width the scrollbar occupied before overflow:hidden hides
        // it, so locking background scroll doesn't shift the page sideways.
        var sbw = window.innerWidth - document.documentElement.clientWidth;
        document.body.classList.add("modal-open");
        if (sbw > 0) document.body.style.paddingRight = sbw + "px";
        requestAnimationFrame(function () {
          modal.classList.add("is-open");
          // Skip the hidden `back` input — focusing it silently does nothing,
          // so the intended "cursor in first field" never happened.
          var first = isScan ? modal.querySelector('[data-modal-close]') : isNew ? modalBody.querySelector('#rz') :
            modalBody.querySelector("input:not([type=hidden]), select, button");
          if (first) first.focus();
        });
      })
      .catch(function () {
        if (serial !== openSerial) return;
        if (isScan) { window.alert('Skenování se nepodařilo otevřít. Obnovte stránku a zkuste to znovu.'); return; }
        window.location.href = isNew ? '/ukony' : url.replace(/[?&]modal=1/, "");
      });
  }

  function closeModal() {
    var event = new CustomEvent('ukon:modal-closing', {cancelable: true});
    if (!document.dispatchEvent(event)) return;
    ++openSerial;
    modal.classList.remove("is-open");
    document.body.classList.remove("modal-open");
    document.body.style.paddingRight = "";
    closeTimer = setTimeout(function () { modal.hidden = true; modalBody.innerHTML = ""; }, 280);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    var url = new URL(window.location.href);
    if (url.searchParams.has('novy')) {
      url.searchParams.delete('novy');
      history.replaceState({}, '', url.pathname + url.search + url.hash);
    }
  }
  window.UkonModal = {close: closeModal};
  window.addEventListener('pagehide', function () {
    ++openSerial; // A fragment arriving after navigation must not open a camera.
    clearTimeout(closeTimer);
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-orv-sken]')) return;
    e.preventDefault();
    if (!modal.hidden) return;
    openModal('/ukony/orv-sken', false, true);
  });

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

  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-new-ukon]');
    if (!trigger) return;
    e.preventDefault();
    var filter = document.querySelector('#filter-form select[name=firma]');
    var q = new URLSearchParams({ modal: '1' });
    if (filter && filter.value) q.set('firma', filter.value);
    openModal('/ukony/novy?' + q.toString(), true);
  });

  if (new URLSearchParams(window.location.search).get('novy') === '1' &&
      window.location.pathname === '/ukony/vse') {
    var filter = document.querySelector('#filter-form select[name=firma]');
    var q = new URLSearchParams({ modal: '1' });
    if (filter && filter.value) q.set('firma', filter.value);
    openModal('/ukony/novy?' + q.toString(), true);
  }

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
        // stránka s výběrem firmy si drží odpovědi v cache — po editaci ji zahoď
        document.dispatchEvent(new CustomEvent("ukon:saved", { detail: { id: m[1] } }));
        closeModal();
      })
      .catch(function () {
        // cokoliv nečekaného → klasické odeslání, ať se změna nikdy neztratí
        if (btn) btn.disabled = false;
        form.submit();
      });
  });

  // Pay / částečná platba / smazat BEZ přenačtení — na /ukony/vse smaže plný
  // reload rozepsané hledání v poli i scroll pozici při KAŽDÉ takové akci,
  // takže je uživatel po každém "✓ zapl." musel zadávat filtr i scroll znovu.
  // Delegace na document — pokrývá i řádky, které tu ještě nebyly při načtení
  // stránky (živé hledání je bere z rows[] zachyceného na startu, ale nové
  // submity na nich zachytí tenhle listener stejně, protože je na documentu).
  function applyPayResult(item, d) {
    if (!item) { window.location.reload(); return; }
    var payEl = item.querySelector(".recent-pay");
    if (payEl && d.pay_badge_html != null) payEl.innerHTML = d.pay_badge_html;
    var slotEl = item.querySelector(".stav-slot");
    if (slotEl && d.stav_slot_html != null) slotEl.innerHTML = d.stav_slot_html;
    var flashEl = item.querySelector("a.recent-row") || item;
    flashEl.classList.add("row-saved");
    setTimeout(function () { flashEl.classList.remove("row-saved"); }, 1200);
  }

  function removeItem(item) {
    if (!item) { window.location.reload(); return; }
    // /ukony/vse drží si vlastní rows[] pro živé hledání a součet — bez
    // vyřazení by smazaný řádek strašil v počtu i součtu, dokud se nehledá.
    if (window.ukonyRemoveRow) window.ukonyRemoveRow(item);
    item.style.transition = "opacity .15s ease";
    item.style.opacity = "0";
    setTimeout(function () { item.remove(); }, 160);
  }

  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form");
    if (!form) return;
    var action = form.getAttribute("action") || "";

    var mPay = /\/ukony\/(\d+)\/zaplaceno$/.exec(action);
    if (mPay) {
      e.preventDefault();
      var item = form.closest(".ukony-item");
      var btn = form.querySelector('button[type="submit"]');
      if (btn) btn.disabled = true;
      fetch(action, {
        method: "POST", body: new FormData(form),
        headers: { "X-Requested-With": "fetch" }
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d.ok) throw new Error("chyba");
          applyPayResult(item, res.d);
          // firma-výběr si drží součet měsíce v cache — platba ho mění
          document.dispatchEvent(new CustomEvent("ukon:saved", { detail: { id: mPay[1] } }));
        })
        .catch(function () {
          // cokoliv nečekaného → klasické odeslání, ať se platba nikdy neztratí
          if (btn) btn.disabled = false;
          form.submit();
        });
      return;
    }

    var mDel = /\/ukony\/(\d+)\/smazat$/.exec(action);
    if (mDel) {
      // Smazat má inline onsubmit="return confirm(...)" — pokud uživatel dal
      // Zrušit, ten handler už submit zamítl (e.defaultPrevented). Nic nedělej.
      if (e.defaultPrevented) return;
      e.preventDefault();
      var item2 = form.closest(".ukony-item");
      fetch(action, {
        method: "POST", body: new FormData(form),
        headers: { "X-Requested-With": "fetch" }
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d.ok) throw new Error("chyba");
          removeItem(item2);
          document.dispatchEvent(new CustomEvent("ukon:saved", { detail: { id: mDel[1] } }));
        })
        .catch(function () { form.submit(); });
    }
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
    if (e.key === 'Tab' && !modal.hidden && modalCard.classList.contains('modal-card--scan')) {
      var focusable = Array.from(modal.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href]'))
        .filter(function (el) { return el.getClientRects().length; });
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
})();
