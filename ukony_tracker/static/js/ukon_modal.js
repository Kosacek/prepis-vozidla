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
  // Techničák zůstává pod druhým overlayem: editace úkonu se otevírá NAD ním
  // (sken se neodebírá), takže se po zavření vracíš přesně tam, kde jsi byl.
  var stack = null;
  var stackTimer;

  function stackBody() {
    return stack && stack.querySelector('#ukon-stack-body');
  }

  function closeStack() {
    if (!stack) return;
    var target = stack;
    stack = null;
    clearTimeout(stackTimer);
    target.classList.remove('is-open');
    stackTimer = setTimeout(function () { target.remove(); }, 220);
    var focus = target.__returnFocus;
    if (focus && focus.isConnected) focus.focus({ preventScroll: true });
  }

  function stackError(form, text) {
    var box = form.querySelector('.modal-form-error');
    if (!box) {
      box = document.createElement('div');
      box.className = 'flash flash-error modal-form-error';
      box.setAttribute('role', 'alert');
      form.prepend(box);
    }
    box.textContent = text;
  }

  function submitStacked(wrap, event) {
    var form = event.target.closest('form');
    if (!form) return;
    var m = /\/ukony\/(\d+)\/upravit/.exec(form.getAttribute('action') || '');
    if (!m) return;
    event.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    fetch(form.action, {
      method: 'POST', body: new FormData(form),
      headers: { 'X-Requested-With': 'fetch' }
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d.ok) {
          var err = new Error((res.d && res.d.error) || 'chyba');
          err.shown = !!(res.d && res.d.error);
          throw err;
        }
        swapRow(m[1], res.d);
        closeStack();
        // Karta skenu dostane „✓ Upraveno"; sken sám zůstává otevřený.
        document.dispatchEvent(new CustomEvent('ukon:saved', { detail: { id: m[1] } }));
      })
      .catch(function (err) {
        if (btn) btn.disabled = false;
        if (err && err.shown) { stackError(form, err.message); return; }
        form.submit();
      });
  }

  function openStackedEdit(uid, returnFocus) {
    if (stack) return;
    var wrap = document.createElement('div');
    wrap.className = 'modal-stack';
    wrap.hidden = true;
    var card = document.createElement('div');
    card.className = 'modal-card card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.setAttribute('aria-labelledby', 'ukon-stack-title');
    var close = document.createElement('button');
    close.className = 'modal-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Zavřít úpravu úkonu');
    close.setAttribute('data-stack-close', '');
    close.innerHTML = '&times;';
    var body = document.createElement('div');
    body.className = 'modal-body';
    body.id = 'ukon-stack-body';
    card.append(close, body);
    wrap.append(card);
    wrap.__returnFocus = returnFocus || document.activeElement;
    modal.append(wrap);
    stack = wrap;
    var serial = ++openSerial;
    fetch('/ukony/' + encodeURIComponent(uid) + '/upravit?modal=1',
          { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { if (!r.ok) throw new Error('modal ' + r.status); return r.text(); })
      .then(function (html) {
        if (stack !== wrap || serial !== openSerial) return;
        body.innerHTML = html;
        var title = body.querySelector('.card-title');
        if (title) title.id = title.id || 'ukon-stack-title';
        body.addEventListener('submit', function (event) { submitStacked(wrap, event); });
        wrap.hidden = false;
        requestAnimationFrame(function () {
          if (stack === wrap) wrap.classList.add('is-open');
        });
        var first = body.querySelector('input:not([type=hidden]), select, button');
        setTimeout(function () {
          if (stack === wrap && first && first.isConnected) first.focus({ preventScroll: true });
        }, 40);
      })
      .catch(function () {
        if (stack === wrap) closeStack();
        window.alert('Úkon se nepodařilo otevřít. Zkuste to znovu.');
      });
  }

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
        lastFocused = document.activeElement;
        modalBody.innerHTML = html;
        modalCard.classList.toggle("modal-card--new", !!isNew);
        modalCard.classList.toggle("modal-card--scan", !!isScan);
        if (isNew) document.dispatchEvent(new CustomEvent('ukon:new-form-shown', { detail: { form: modalBody.querySelector('#ukon-form') } }));
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

  function closeModal(savedId) {
    if (stack) closeStack();
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
  window.UkonModal = {close: function () { closeModal(); }, openEdit: function (uid) {
    if (modalCard.classList.contains("modal-card--scan")) {
      openStackedEdit(uid, document.activeElement);
      return;
    }
    openModal('/ukony/' + encodeURIComponent(uid) + '/upravit?modal=1', false, false);
  }};
  window.addEventListener('pagehide', function () {
    ++openSerial; // A fragment arriving after navigation must not open a camera.
    clearTimeout(closeTimer);
    clearTimeout(stackTimer);
    stack = null;
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
    var item = link.closest(".ukony-item");
    // /ukony/vse: vyměň celou položku (platba, iniciála, koš), jinde jen odkaz.
    var freshItem = null;
    if (item && data.item_html && item.closest(".ukony-list")) {
      tmp.innerHTML = data.item_html.trim();
      freshItem = tmp.querySelector(".ukony-item");
    }
    if (freshItem) {
      // Doklady: the row's trash deletes its doklad, never the úkon — keep
      // that form instead of the úkon trash the fresh row comes with.
      var dokladDel = item.querySelector('form[action^="/doklady/"]');
      var ukonDel = dokladDel && freshItem.querySelector('form[action$="/smazat"]');
      if (ukonDel) ukonDel.parentNode.replaceChild(dokladDel, ukonDel);
      item.parentNode.replaceChild(freshItem, item);
      if (window.ukonyReplaceRow) window.ukonyReplaceRow(item, freshItem);
      var freshLink = freshItem.querySelector("a.recent-row");
      if (freshLink) {
        freshLink.classList.add("row-saved");
        setTimeout(function () { freshLink.classList.remove("row-saved"); }, 1200);
      }
      return true;
    }
    tmp.innerHTML = (data.html || "").trim();
    var fresh = tmp.querySelector("a.recent-row");
    if (!fresh) return false;
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

  function showFormError(form, text) {
    var box = form.querySelector(".modal-form-error");
    if (!box) {
      box = document.createElement("div");
      box.className = "flash flash-error modal-form-error";
      box.setAttribute("role", "alert");
      form.prepend(box);
    }
    box.textContent = text;
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
        if (!res.ok || !res.d.ok) {
          var err = new Error((res.d && res.d.error) || "chyba");
          err.shown = !!(res.d && res.d.error);
          throw err;
        }
        // Řádek není na stránce: bez reportu techničáku stačí reload; s ním
        // se stránka obnoví až při zavření skenu (sken zmizet nesmí).
        if (!swapRow(m[1], res.d)) { window.location.reload(); return; }
        // stránka s výběrem firmy si drží odpovědi v cache — po editaci ji zahoď
        document.dispatchEvent(new CustomEvent("ukon:saved", { detail: { id: m[1] } }));
        closeModal(m[1]);
      })
      .catch(function (err) {
        if (btn) btn.disabled = false;
        // Validační chyba → ukaž ji přímo v okně, žádný skok na jinou stránku.
        if (err && err.shown) { showFormError(form, err.message); return; }
        // cokoliv nečekaného → klasické odeslání, ať se změna nikdy neztratí
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
    // Overlay úpravy nad skenem: zavírá jen on, nikdy celý techničák.
    if (stack) {
      if (e.target === stack || e.target.closest('[data-stack-close]') ||
          e.target.closest('[data-modal-close]')) {
        e.preventDefault();
        closeStack();
        return;
      }
      if (stack.contains(e.target)) return;  // klik uvnitř karty úprav
    }
    if (e.target === modal || e.target.closest("[data-modal-close]")) {
      e.preventDefault();
      closeModal();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && stack) { e.preventDefault(); closeStack(); return; }
    if (e.key === "Escape" && !modal.hidden) closeModal();
    if (e.key === 'Tab' && stack) {
      var inStack = Array.from(stack.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]'))
        .filter(function (el) { return el.getClientRects().length; });
      var sFirst = inStack[0], sLast = inStack[inStack.length - 1];
      if (sFirst && sLast) {
        if (e.shiftKey && document.activeElement === sFirst) { e.preventDefault(); sLast.focus(); }
        else if (!e.shiftKey && document.activeElement === sLast) { e.preventDefault(); sFirst.focus(); }
      }
      return;
    }
    if (e.key === 'Tab' && !modal.hidden && modalCard.classList.contains('modal-card--scan')) {
      var focusable = Array.from(modal.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href]'))
        .filter(function (el) { return el.getClientRects().length; });
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
})();
