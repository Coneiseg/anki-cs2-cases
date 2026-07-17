/* CS2 Cases — presentation layer. Authoritative decisions come from Python;
   this file renders, animates, and plays sound only. */
(function () {
  "use strict";

  var TILE = 150;      // px pitch per reel tile (must match --tile + gap in CSS)
  var WIN_INDEX = 52;  // winning_index from unboxing.build_reel

  function $(s, r) { return (r || document).querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function scrollTop() { var c = $(".content"); if (c) c.scrollTop = 0; }
  function assetBase() { return (window.__state && window.__state.asset_base) || ""; }
  function imgUrl(image) {
    if (!image) return null;
    return /^https?:\/\//.test(image) ? image : (assetBase() + image);
  }
  function cfg(k) { return window.__state && window.__state.config && window.__state.config[k]; }
  function muted() { return !!cfg("muted"); }
  function reducedMotion() { return !!cfg("reduced_motion"); }
  function rarities() { return (window.__state && window.__state.rarities) || {}; }
  function rarityRank(r) { return Object.keys(rarities()).indexOf(r); }
  function rarityColor(entry) {
    if (entry.rarity_meta && entry.rarity_meta.color) return entry.rarity_meta.color;
    var m = rarities()[entry.rarity];
    return (m && m.color) || "#4b69ff";
  }

  // ---- audio: prefer real drop-in files, else synthesize -------------------
  var SND = { ready: {}, ctx: null, noise: null, tickPool: [], tickIdx: 0 };
  function audioCtx() {
    if (!SND.ctx) { var AC = window.AudioContext || window.webkitAudioContext; if (AC) SND.ctx = new AC(); }
    return SND.ctx;
  }
  function noiseBuffer() {
    var a = audioCtx(); if (!a) return null;
    if (!SND.noise) {
      var n = Math.floor(a.sampleRate * 0.2), buf = a.createBuffer(1, n, a.sampleRate), d = buf.getChannelData(0);
      for (var i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
      SND.noise = buf;
    }
    return SND.noise;
  }
  function tryLoadSound(key, file) {
    try {
      var url = assetBase() + file, el = new Audio();
      el.preload = "auto"; el.src = url;
      el.addEventListener("canplaythrough", function () { SND.ready[key] = url; }, { once: true });
      el.addEventListener("error", function () { SND.ready[key] = null; });
    } catch (e) { SND.ready[key] = null; }
  }
  function initSounds() {
    // Real CS2 audio: the scroll tick, the case-open whoosh, and per-rarity reveal
    // stingers. Synth is only a fallback if a file is missing.
    tryLoadSound("tick", "sounds/tick.wav");
    tryLoadSound("open", "sounds/crate_open.wav");
    Object.keys(rarities()).forEach(function (r) {
      tryLoadSound("reveal_" + r, "sounds/reveal_" + r + ".mp3");
    });
  }
  function playOpen() { if (!muted()) playFile("open", 0.55); }
  function stopTick() {
    SND.tickPool.forEach(function (el) { try { el.pause(); el.currentTime = 0; } catch (e) {} });
  }
  function playFile(key, vol) {
    var url = SND.ready[key]; if (!url) return false;
    try { var a = new Audio(url); a.volume = (vol == null ? 0.7 : vol); a.play(); return true; }
    catch (e) { return false; }
  }
  function playTick() {
    if (muted()) return;
    // Round-robin voice pool so rapid ticks OVERLAP (each full click rings), giving
    // CS2's smooth fast-scroll blur early and clean discrete ticks as it slows —
    // rather than one element restarting and chopping each click to its attack.
    var url = SND.ready["tick"];
    if (url) {
      try {
        if (!SND.tickPool.length) {
          for (var i = 0; i < 8; i++) { var el = new Audio(url); el.volume = 0.32; SND.tickPool.push(el); }
        }
        var voice = SND.tickPool[SND.tickIdx++ % SND.tickPool.length];
        voice.currentTime = 0; voice.play();
        return;
      } catch (e) {}
    }
    var a = audioCtx(); if (!a) return;
    var src = a.createBufferSource(); src.buffer = noiseBuffer();
    var bp = a.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 2200; bp.Q.value = 1.2;
    var g = a.createGain(), t = a.currentTime;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.14, t + 0.002);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
    src.connect(bp).connect(g).connect(a.destination); src.start(t); src.stop(t + 0.05);
  }
  function playReveal(rarity) {
    if (muted()) return;
    stopTick();  // kill the scroll tick so its tail can't overlap the reveal
    var special = rarity === "special";
    if (playFile("reveal_" + rarity, 0.8)) return;  // real per-rarity CS2 stinger
    var a = audioCtx(); if (!a) return;             // else synth fallback
    var t = a.currentTime;
    var src = a.createBufferSource(); src.buffer = noiseBuffer();
    var lp = a.createBiquadFilter(); lp.type = "lowpass";
    lp.frequency.setValueAtTime(400, t); lp.frequency.exponentialRampToValueAtTime(4200, t + 0.35);
    var wg = a.createGain();
    wg.gain.setValueAtTime(0.0001, t);
    wg.gain.exponentialRampToValueAtTime(0.09, t + 0.05);
    wg.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
    src.connect(lp).connect(wg).connect(a.destination); src.start(t); src.stop(t + 0.45);
    var notes = special ? [392, 523, 659, 784] : rarity === "covert" ? [330, 494, 659]
      : rarity === "classified" ? [294, 440, 587] : rarity === "restricted" ? [262, 392] : [196, 294];
    notes.forEach(function (f, i) {
      var tt = t + 0.02 + i * 0.05, o = a.createOscillator(), g = a.createGain();
      o.type = "triangle"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, tt);
      g.gain.exponentialRampToValueAtTime(0.11, tt + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, tt + 0.5);
      o.connect(g).connect(a.destination); o.start(tt); o.stop(tt + 0.55);
    });
  }

  // ---- toast ---------------------------------------------------------------
  var _toastTimer = null;
  function toast(msg, isErr) {
    var el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isErr ? " err" : "");
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () { el.classList.add("hidden"); }, 2600);
  }

  // ---- cell builders -------------------------------------------------------
  function cellArtHtml(image, weapon) {
    var u = imgUrl(image);
    return u
      ? '<img src="' + esc(u) + '" onerror="this.style.display=\'none\'">'
      : '<span class="noimg">' + esc(weapon || "") + "</span>";
  }
  function itemCellHtml(entry, extra) {
    var st = entry.stattrak ? '<span class="st">ST™</span> ' : "";
    return '<div class="art">' + cellArtHtml(entry.item.image, entry.item.weapon) + "</div>"
      + (entry.favorite ? '<span class="fav" title="Favourite — protected from selling">★</span>' : "")
      + '<div class="bar"></div>'
      + '<div class="info"><div class="wpn">' + st + esc(entry.item.weapon) + "</div>"
      + '<div class="skn">' + esc(entry.item.skin || "—") + "</div>"
      + '<div class="sub"><span>' + esc(entry.wear.name) + "</span>"
      + '<span class="val">$' + entry.value.toFixed(2) + "</span></div></div>"
      + (extra || "");
  }
  function makeItemCell(entry) {
    var el = document.createElement("div");
    el.className = "cell";
    el.style.setProperty("--rc", rarityColor(entry));
    el.setAttribute("data-uid", entry.uid);
    el.setAttribute("data-rarity", entry.rarity);
    return el;
  }

  // ---- views ---------------------------------------------------------------
  function setView(name) {
    if (name !== "store") _storeDetail = null;  // leaving store resets any preview
    ["store", "inventory", "tradeup", "stats"].forEach(function (v) {
      $("#view-" + v).classList.toggle("hidden", v !== name);
    });
    document.querySelectorAll(".tab").forEach(function (t) {
      t.classList.toggle("active", t.getAttribute("data-view") === name);
    });
    render();
    scrollTop();  // start each view at the top
  }
  function currentView() {
    var a = document.querySelector(".tab.active");
    return a ? a.getAttribute("data-view") : "store";
  }
  function render() {
    var v = currentView();
    if (v === "store") renderStore();
    else if (v === "inventory") renderInventory();
    else if (v === "tradeup") renderTradeUp();
    else renderStats();
  }

  var _storeDetail = null;
  var CAT_LABELS = { "Case": "Weapon Cases", "Souvenir": "Souvenir Packages", "Souvenir Highlight": "Souvenir Highlights" };
  var CAT_ORDER = ["Case", "Souvenir", "Souvenir Highlight"];
  function openCase(caseId) {
    var a = audioCtx(); if (a && a.state === "suspended") a.resume();
    cs2.send("open", { case_id: caseId });
  }
  function caseCardHtml(c) {
    var afford = (window.__state.balance || 0) >= c.price, u = imgUrl(c.image);
    return '<div class="cell case click" data-id="' + esc(c.id) + '">'
      + '<div class="art">' + (u ? '<img src="' + esc(u) + '" onerror="this.style.display=\'none\'">'
        : '<span class="box">Case</span>') + "</div>"
      + '<div class="name">' + esc(c.name) + "</div>"
      + '<div class="openwrap"><button class="btn open"' + (afford ? "" : " disabled")
      + ">Open $" + c.price.toFixed(2) + "</button></div></div>";
  }
  function renderStore() {
    var s = window.__state, el = $("#view-store");
    if (_storeDetail) { renderCaseDetail(el, _storeDetail); return; }
    var banner = "";
    if (!s.is_full_catalog) {
      banner = '<div class="banner"><span>You’re on the starter set. Download the full '
        + 'catalog (all cases + packages) with real images.</span>'
        + '<button class="btn small" id="dl-catalog">Download real cases</button></div>';
    }
    // Group containers by category into collapsible sections; weapon cases open,
    // the large souvenir groups collapsed to keep the window uncluttered.
    var groups = {};
    s.cases.forEach(function (c) { var k = c.category || "Case"; (groups[k] = groups[k] || []).push(c); });
    var order = CAT_ORDER.filter(function (k) { return groups[k]; });
    Object.keys(groups).forEach(function (k) { if (order.indexOf(k) === -1) order.push(k); });
    var sections = order.map(function (cat) {
      var list = groups[cat], collapsed = cat !== "Case";
      return '<div class="rar-section' + (collapsed ? " collapsed" : "") + '">'
        + '<div class="rar-head"><span class="caret">▾</span> ' + esc(CAT_LABELS[cat] || cat)
        + ' <span class="cnt">' + list.length + "</span></div>"
        + '<div class="grid rar-grid">' + list.map(caseCardHtml).join("") + "</div></div>";
    }).join("");
    el.innerHTML = banner + sections;
    if (!s.is_full_catalog) {
      $("#dl-catalog").onclick = function () { toast("Downloading catalog + images…"); cs2.send("refresh"); };
    }
    el.querySelectorAll(".rar-head").forEach(function (h) {
      h.onclick = function () { h.parentNode.classList.toggle("collapsed"); };
    });
    el.querySelectorAll(".case").forEach(function (card) {
      var id = card.getAttribute("data-id");
      card.onclick = function () { cs2.send("case_detail", { case_id: id }); };
      var ob = card.querySelector(".open");
      if (ob) ob.onclick = function (ev) { ev.stopPropagation(); openCase(id); };
    });
  }

  function previewCell(item, color) {
    return '<div class="cell" style="--rc:' + esc(color || "#4b69ff") + '">'
      + '<div class="art">' + cellArtHtml(item.image, item.weapon) + "</div>"
      + '<div class="bar"></div>'
      + '<div class="info"><div class="wpn">' + esc(item.weapon) + "</div>"
      + '<div class="skn">' + esc(item.skin || "") + "</div></div></div>";
  }
  function renderCaseDetail(el, d) {
    var afford = (window.__state.balance || 0) >= d.price;
    var order = Object.keys(rarities()).slice().reverse();  // gold/rarest first
    var sections = order.map(function (r) {
      var pool = d.items[r] || [];
      if (!pool.length) return "";
      var meta = rarities()[r] || {};
      var op = d.odds && d.odds[r] != null ? d.odds[r] * 100 : null;
      var odds = op != null ? op.toFixed(2) + "%" : "";
      // Collapse big sections by default (the knife pool is ~65 items) so the page
      // stays short; small weapon tiers start expanded.
      var collapsed = pool.length > 12;
      var cells = pool.map(function (it) { return previewCell(it, meta.color); }).join("");
      return '<div class="rar-section' + (collapsed ? " collapsed" : "") + '">'
        + '<div class="rar-head" style="color:' + esc(meta.color || "#fff") + '">'
        + '<span class="caret">▾</span> ' + esc(meta.name || r)
        + ' <span class="odds">' + odds + "</span>"
        + '<span class="cnt">' + pool.length + " skins</span></div>"
        + '<div class="grid rar-grid">' + cells + "</div></div>";
    }).join("");
    el.innerHTML =
      '<div class="detail-top"><button class="btn sec small" id="back">‹ Back</button>'
      + '<span class="dtitle">' + esc(d.name) + "</span>"
      + '<button class="btn small" id="dopen"' + (afford ? "" : " disabled")
      + ">Open $" + d.price.toFixed(2) + "</button></div>" + sections
      + '<div style="height:56px"></div>'
      + '<button class="btn sec back-fab" id="backfab">‹ Back</button>';
    function back() { _storeDetail = null; renderStore(); scrollTop(); }
    $("#back").onclick = back;
    $("#backfab").onclick = back;
    $("#dopen").onclick = function () { openCase(d.id); };
    el.querySelectorAll(".rar-head").forEach(function (h) {
      h.onclick = function () { h.parentNode.classList.toggle("collapsed"); };
    });
  }

  // ---- stats ---------------------------------------------------------------
  function statRow(label, value, cls) {
    return '<div class="stat"><span class="k">' + esc(label) + '</span>'
      + '<span class="v ' + (cls || "") + '">' + value + "</span></div>";
  }
  function renderStats() {
    var s = window.__state, el = $("#view-stats");
    var st = s.stats || {};
    var spent = st.spent || 0, invVal = s.inventory_value || 0;
    var net = invVal - spent;                       // unbox profit/loss on cases
    var netCls = net >= 0 ? "up" : "down";
    var netStr = (net >= 0 ? "+$" : "-$") + Math.abs(net).toFixed(2);

    // --- rarity pyramid: colored bars, not a wall of numbers ------------------
    var pulls = st.pulls || {};
    var order = Object.keys(rarities());
    var totalPulls = order.reduce(function (a, r) { return a + (pulls[r] || 0); }, 0);
    var shown = order;  // always show every tier, even at 0 — the empty rows are the point
    var maxPull = shown.reduce(function (a, r) { return Math.max(a, pulls[r] || 0); }, 0) || 1;
    var rarityHtml = shown.map(function (r) {
      var meta = rarities()[r] || {}, n = pulls[r] || 0;
      var col = meta.color || "#fff";
      var w = (n / maxPull) * 100;
      var share = totalPulls ? (n / totalPulls * 100).toFixed(1) + "%" : "—";
      return '<div class="rbar-row">'
        + '<span class="rbar-name" style="color:' + esc(col) + '">' + esc(meta.name || r) + "</span>"
        + '<div class="rbar-track"><div class="rbar-fill" style="width:' + w.toFixed(1)
        + "%;background:" + esc(col) + ";color:" + esc(col) + '"></div></div>'
        + '<span class="rbar-n">' + n + "</span>"
        + '<span class="rbar-pct">' + share + "</span></div>";
    }).join("");
    var drought = st.since_special || 0;

    var hist = s.history || [];
    var rows = hist.length
      ? hist.slice(0, 20).map(function (h) {
          var col = (rarities()[h.rarity] || {}).color || "#fff";
          return '<div class="histrow"><span class="dot" style="background:' + col + '"></span>'
            + '<span class="hname">' + esc(h.name) + "</span>"
            + '<span class="hval">$' + (h.value || 0).toFixed(2) + "</span></div>";
        }).join("")
      : '<div class="empty" style="padding:24px 0">No unboxes yet.</div>';

    el.innerHTML =
      '<div class="section-title">Career</div>'
      + '<div class="stats-grid">'
      + statRow("Cards answered", (st.cards || 0).toLocaleString())
      + statRow("Cases opened", (st.cases_opened || 0).toLocaleString())
      + statRow("Spent on cases", "$" + spent.toFixed(2), "down")
      + statRow("Unboxing net", netStr, netCls)
      + "</div>"
      + '<div class="section-title" style="margin-top:18px">Unboxed by Rarity'
      + '<span class="note">' + totalPulls.toLocaleString() + " unboxed · " + drought + " since ★</span></div>"
      + '<div class="rbar">' + rarityHtml + "</div>"
      + '<div class="collline"><span>' + (s.inventory_count || 0) + " items owned</span>"
      + '<span class="cv">$' + invVal.toFixed(2) + "</span></div>"
      + '<div class="section-title" style="margin-top:18px">Recent Unboxes</div>'
      + '<div class="histlist">' + rows + "</div>"
      + '<div class="section-title" style="margin-top:18px">Settings</div>'
      + '<label class="setting"><input type="checkbox" id="set-mute"'
      + (cfg("muted") ? " checked" : "") + "> Mute sounds</label>"
      + '<label class="setting"><input type="checkbox" id="set-motion"'
      + (cfg("reduced_motion") ? " checked" : "") + "> Reduced motion (skip the reel)</label>";
    $("#set-mute").onchange = function () { cs2.send("set_config", { key: "muted", value: this.checked }); };
    $("#set-motion").onchange = function () { cs2.send("set_config", { key: "reduced_motion", value: this.checked }); };
  }

  // ---- inventory + management ----------------------------------------------
  var _inv = { q: "", sort: "new", rarity: "all", sel: {} };
  function invSelCount() { return Object.keys(_inv.sel).length; }
  function invSelValue() {
    var s = window.__state, sum = 0;
    s.inventory.forEach(function (e) { if (_inv.sel[e.uid]) sum += e.value; });
    return sum;
  }
  function filteredInventory() {
    var s = window.__state, q = _inv.q.toLowerCase();
    var items = s.inventory.filter(function (e) {
      if (_inv.rarity !== "all" && e.rarity !== _inv.rarity) return false;
      if (q) {
        var name = (e.item.weapon + " " + e.item.skin).toLowerCase();
        if (name.indexOf(q) === -1) return false;
      }
      return true;
    });
    items.sort(function (a, b) {
      if (_inv.sort === "value") return b.value - a.value;
      if (_inv.sort === "rarity") return (rarityRank(b.rarity) - rarityRank(a.rarity)) || (b.value - a.value);
      return b.uid - a.uid; // newest
    });
    return items;
  }
  function duplicateUids() {
    // Keep the highest-value copy of each weapon|skin; the rest are duplicates.
    // Favourites are never offered up for selling.
    var groups = {};
    window.__state.inventory.forEach(function (e) {
      if (e.favorite) return;
      var k = e.item.weapon + "|" + e.item.skin;
      (groups[k] = groups[k] || []).push(e);
    });
    var dups = [];
    Object.keys(groups).forEach(function (k) {
      var g = groups[k];
      if (g.length > 1) {
        g.sort(function (a, b) { return b.value - a.value; });
        for (var i = 1; i < g.length; i++) dups.push(g[i].uid);
      }
    });
    return dups;
  }
  function renderInventory() {
    var s = window.__state, el = $("#view-inventory");
    if (!s.inventory.length) {
      el.innerHTML = '<div class="empty">Empty inventory — answer cards to earn, then open a case.</div>';
      return;
    }
    var rarOpts = '<option value="all">All rarities</option>' + Object.keys(rarities()).map(function (r) {
      return '<option value="' + r + '"' + (_inv.rarity === r ? " selected" : "") + ">"
        + esc(rarities()[r].name) + "</option>";
    }).join("");
    var sortOpts = [["new", "Newest"], ["value", "Value"], ["rarity", "Rarity"]].map(function (o) {
      return '<option value="' + o[0] + '"' + (_inv.sort === o[0] ? " selected" : "") + ">" + o[1] + "</option>";
    }).join("");
    var dupCount = duplicateUids().length;
    el.innerHTML =
      '<div class="controls">'
      + '<input id="inv-q" placeholder="Search skins…" value="' + esc(_inv.q) + '">'
      + '<select id="inv-sort">' + sortOpts + "</select>"
      + '<select id="inv-rar">' + rarOpts + "</select>"
      + '<span class="spacer"></span>'
      + '<span class="count">' + s.inventory.length + " items</span>"
      + '<button class="btn sec small" id="inv-dups"' + (dupCount ? "" : " disabled") + ">Sell duplicates (" + dupCount + ")</button>"
      + "</div>"
      + '<div class="grid" id="inv-grid"></div>'
      + '<div class="scroll-pad"></div>'
      + '<div class="actionbar" id="inv-selbar" style="display:none"></div>';

    var grid = $("#inv-grid");
    filteredInventory().forEach(function (e) {
      var cell = makeItemCell(e);
      cell.classList.add("click");
      if (_inv.sel[e.uid]) cell.classList.add("selected");
      cell.innerHTML = itemCellHtml(e);  // no per-cell Sell button; tap to select, sell from the bottom bar
      cell.onclick = function () {
        if (_inv.sel[e.uid]) delete _inv.sel[e.uid]; else _inv.sel[e.uid] = true;
        cell.classList.toggle("selected");
        renderSelBar();
      };
      grid.appendChild(cell);
    });

    $("#inv-q").oninput = function () { _inv.q = this.value; var pos = this.selectionStart; renderInventory(); var q = $("#inv-q"); if (q) { q.focus(); q.selectionStart = q.selectionEnd = pos; } };
    $("#inv-sort").onchange = function () { _inv.sort = this.value; renderInventory(); };
    $("#inv-rar").onchange = function () { _inv.rarity = this.value; renderInventory(); };
    $("#inv-dups").onclick = function () { var u = duplicateUids(); if (u.length) cs2.send("sell_many", { uids: u }); };
    renderSelBar();
  }
  function renderSelBar() {
    var bar = $("#inv-selbar"); if (!bar) return;
    var n = invSelCount();
    if (!n) { bar.style.display = "none"; bar.innerHTML = ""; return; }
    bar.style.display = "flex";
    // If everything selected is already a favourite, the button unfavourites instead.
    var selected = window.__state.inventory.filter(function (e) { return _inv.sel[e.uid]; });
    var allFav = selected.length > 0 && selected.every(function (e) { return !!e.favorite; });
    bar.innerHTML =
      '<span class="count">' + n + " selected · $" + invSelValue().toFixed(2) + "</span>"
      + '<button class="btn sec small" id="sel-fav">' + (allFav ? "Unfavourite" : "Favourite") + "</button>"
      + '<button class="btn danger small" id="sel-sell">Sell selected</button>'
      + '<button class="btn sec small" id="sel-clear">Clear</button>';
    $("#sel-fav").onclick = function () {
      cs2.send("favorite", { uids: Object.keys(_inv.sel).map(Number), value: !allFav });
    };
    $("#sel-sell").onclick = function () { cs2.send("sell_many", { uids: Object.keys(_inv.sel).map(Number) }); };
    $("#sel-clear").onclick = function () { _inv.sel = {}; renderInventory(); };
  }

  // ---- trade-up ------------------------------------------------------------
  var _tuSel = {}, _tuRarity = null;
  function tuTarget() { return _tuRarity === "covert" ? 5 : 10; }  // red->gold takes 5
  function renderTradeUp() {
    var s = window.__state, el = $("#view-tradeup");
    // Everything except the top Special/gold tier can be traded up.
    var tradeable = s.trade_up_order.filter(function (r) { return r !== "special"; });
    _tuSel = {}; _tuRarity = null;
    el.innerHTML =
      '<div class="section-title">Trade Up<span class="note">10 of a rarity → 1 next tier · '
      + '5 Covert → Gold · StatTrak™ share = output odds</span></div>'
      + '<div class="grid" id="tu-grid"></div>'
      + '<div class="scroll-pad"></div>'
      + '<div class="actionbar"><span class="count" id="tu-count">0 / 10 selected</span>'
      + '<button class="btn small" id="tu-go" disabled>Trade Up</button></div>';
    var grid = $("#tu-grid");
    if (!s.inventory.length) { grid.innerHTML = '<div class="empty">Open cases to collect skins first.</div>'; return; }
    s.inventory.slice().sort(function (a, b) { return (rarityRank(a.rarity) - rarityRank(b.rarity)) || (b.uid - a.uid); })
      .forEach(function (e) {
        // Favourites are protected — not eligible as contract inputs.
        var usable = tradeable.indexOf(e.rarity) !== -1 && !e.favorite;
        var cell = makeItemCell(e);
        if (usable) cell.classList.add("click"); else cell.classList.add("dim");
        cell.innerHTML = itemCellHtml(e);
        if (usable) cell.onclick = function () { toggleTu(e, cell); };
        grid.appendChild(cell);
      });
    $("#tu-go").onclick = function () {
      var uids = Object.keys(_tuSel).map(Number);
      if (uids.length === tuTarget()) cs2.send("trade_up", { uids: uids });
    };
  }
  function toggleTu(e, cell) {
    if (_tuSel[e.uid]) {
      delete _tuSel[e.uid]; cell.classList.remove("selected");
      if (!Object.keys(_tuSel).length) _tuRarity = null;
    } else {
      if (_tuRarity && _tuRarity !== e.rarity) { toast("Pick skins of the same rarity.", true); return; }
      var wouldBeRarity = _tuRarity || e.rarity;
      var target = wouldBeRarity === "covert" ? 5 : 10;
      if (Object.keys(_tuSel).length >= target) { toast("Already selected " + target + ".", true); return; }
      if (wouldBeRarity === "covert") {  // red -> gold can't mix StatTrak
        var picked = window.__state.inventory.filter(function (x) { return _tuSel[x.uid]; });
        if (picked.length && !!picked[0].stattrak !== !!e.stattrak) {
          toast("Red → Gold can't mix StatTrak™.", true); return;
        }
      }
      _tuRarity = e.rarity; _tuSel[e.uid] = true; cell.classList.add("selected");
    }
    var n = Object.keys(_tuSel).length, target = tuTarget();
    $("#tu-count").textContent = n + " / " + target + " selected";
    $("#tu-go").disabled = n !== target;
    document.querySelectorAll("#tu-grid .cell.click").forEach(function (c) {
      var mismatch = _tuRarity && c.getAttribute("data-rarity") !== _tuRarity;
      c.classList.toggle("dim", !!mismatch);
    });
  }

  // ---- opening flow --------------------------------------------------------
  function reelCell(t) {
    var el = document.createElement("div");
    el.className = "cell";
    el.style.setProperty("--rc", t.color);
    if (t.rarity === "special") {
      // Hide the knife/glove identity during the scroll — CS2 shows a generic gold
      // "Rare Special Item" and only reveals what it is if you actually land on it.
      el.classList.add("special-hidden");
      el.innerHTML = '<div class="art"><span class="goldstar">★</span></div>'
        + '<div class="bar"></div>'
        + '<div class="info"><div class="wpn">Rare Special</div><div class="skn">Item</div></div>';
      return el;
    }
    el.innerHTML = '<div class="art">' + cellArtHtml(t.image, t.weapon) + "</div>"
      + '<div class="bar"></div>'
      + '<div class="info"><div class="wpn">' + esc(t.weapon) + "</div>"
      + '<div class="skn">' + esc(t.skin || "") + "</div></div>";
    return el;
  }
  function startOpening(drop, reel, newState) {
    var ac = audioCtx(); if (ac && ac.state === "suspended") { try { ac.resume(); } catch (e) {} }
    playOpen();  // case-open whoosh as the reel starts
    var overlay = $("#opening"); overlay.classList.remove("hidden");
    $(".reel-viewport").style.display = "";  // restore (a prior trade-up hides it)
    var glow = $("#screenglow"); glow.classList.remove("on");
    glow.style.setProperty("--rc", (drop.rarity_meta && drop.rarity_meta.color) || "#4b69ff");
    $("#goldflash").classList.remove("flash");
    var reveal = $("#reveal"); reveal.classList.add("hidden"); reveal.innerHTML = "";
    var strip = $("#reel"); strip.innerHTML = ""; strip.style.transform = "translateX(0)";
    reel.forEach(function (t) { strip.appendChild(reelCell(t)); });
    // Note: the winning tile is NOT highlighted during the spin — that would spoil
    // the tease. It only lights up once the reel lands (see finishOpening).

    var viewportW = $(".reel-viewport").clientWidth;
    var tileInner = TILE - 10;
    var winCenter = WIN_INDEX * TILE + tileInner / 2;
    var jitter = (Math.random() - 0.5) * tileInner * 0.5;
    var finalX = -(winCenter - viewportW / 2 + jitter);

    // Quick-open: click anywhere during the spin to skip straight to the result.
    var skip = false;
    function requestSkip() { skip = true; }
    var ov = $("#opening");
    ov.addEventListener("click", requestSkip);
    function done() {
      ov.removeEventListener("click", requestSkip);
      finishOpening(drop, newState);
    }

    if (reducedMotion()) {
      strip.style.transform = "translateX(" + finalX + "px)";
      done();
      return;
    }

    var duration = 7000, start = performance.now();
    var lastIdx = -1, lastTick = 0, glowed = false, lastX = 0;
    function frame(now) {
      var p = (now - start) / duration; if (p > 1) p = 1;
      var eased = 1 - Math.pow(1 - p, 5); // easeOutQuint: fast start, long slow landing
      var x = finalX * eased;
      if (skip) { strip.style.transform = "translateX(" + finalX + "px)"; glow.classList.add("on"); done(); return; }
      strip.style.transform = "translateX(" + x + "px)";
      var idx = Math.floor((-x + viewportW / 2) / TILE);
      if (idx !== lastIdx) { lastIdx = idx; if (now - lastTick > 22) { playTick(); lastTick = now; } }
      if (!glowed && p > 0.7) { glowed = true; glow.classList.add("on"); }
      // Reveal as soon as it's visually settled — skip the dead tail where the
      // reel has effectively stopped but the easing hasn't reached p=1.
      var settled = p > 0.6 && Math.abs(x - lastX) < 0.15;
      lastX = x;
      if (p >= 1 || settled) { done(); return; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  function wearBarHtml(drop) {
    var pct = Math.max(0, Math.min(1, drop.float)) * 100;
    return '<div class="wearbar"><div class="track"><span class="pin" style="left:' + pct.toFixed(2) + '%"></span></div>'
      + '<div class="flabel"><span>0.00 Factory New</span><span>Battle-Scarred 1.00</span></div></div>';
  }
  function finishOpening(drop, newState) {
    // Light up the landed reel tile only now, at the reveal.
    var wt = $("#reel").children[WIN_INDEX];
    if (wt) { wt.style.setProperty("--rc", (drop.rarity_meta && drop.rarity_meta.color) || "#4b69ff"); wt.classList.add("win"); }
    showReveal(drop, newState, false);
  }
  // Trade-up: a forge, not a case, so no reel — go straight to the reveal, which
  // carries the output tier's color bar and plays that tier's reveal sound.
  function startTradeupReveal(drop) {
    var ov = $("#opening"); ov.classList.remove("hidden");
    var glow = $("#screenglow"); glow.classList.remove("on");
    glow.style.setProperty("--rc", (drop.rarity_meta && drop.rarity_meta.color) || "#4b69ff");
    $("#goldflash").classList.remove("flash");
    $(".reel-viewport").style.display = "none";
    $("#reveal").classList.add("hidden");
    glow.classList.add("on");
    showReveal(drop, null, true);
  }
  function showReveal(drop, newState, tradeup) {
    var special = drop.rarity === "special";
    playReveal(drop.rarity);  // the output tier's sound
    if (special) { var gf = $("#goldflash"); gf.classList.remove("flash"); void gf.offsetWidth; gf.classList.add("flash"); }
    var reveal = $("#reveal");
    var color = (drop.rarity_meta && drop.rarity_meta.color) || "#4b69ff";
    reveal.style.setProperty("--rc", color);  // the grade color bar
    var st = drop.stattrak ? '<span class="st">StatTrak™</span> ' : "";
    reveal.innerHTML =
      (special ? '<div class="special-banner">★ Rare Special Item ★</div>'
        : tradeup ? '<div class="rname" style="margin-top:0">Trade-Up Contract</div>' : "")
      + '<div class="big-art">' + cellArtHtml(drop.item.image, drop.item.weapon) + "</div>"
      + '<div class="rname">' + esc(drop.rarity_meta ? drop.rarity_meta.name : drop.rarity) + "</div>"
      + '<div class="title">' + st + esc(drop.item.weapon) + " | " + esc(drop.item.skin || "—") + "</div>"
      + '<div class="sub">' + esc(drop.wear.name) + " · float " + drop.float.toFixed(6) + "</div>"
      + wearBarHtml(drop)
      + '<div class="value">$' + drop.value.toFixed(2) + "</div>"
      + '<div class="actions"><button class="btn continue">Continue</button>'
      + (tradeup ? "" : '<button class="btn sec again">Open Another</button>')
      + '<button class="btn danger sellnow">Sell $' + drop.value.toFixed(2) + "</button></div>";
    reveal.classList.remove("hidden");
    var overlayMode = window.__MODE__ === "overlay";
    $("#reveal .continue").onclick = function () {
      hideOpening();
      if (overlayMode) cs2.send("overlay_done");
      else { if (newState) applyState(newState); render(); }
    };
    $("#reveal .sellnow").onclick = function () {
      hideOpening();
      if (overlayMode) cs2.send("overlay_sell", { uid: drop.uid });
      else { if (newState) applyState(newState); cs2.send("sell", { uid: drop.uid }); render(); }
    };
    if (!tradeup) {
      $("#reveal .again").onclick = function () {
        if (overlayMode) cs2.send("overlay_reopen", { case_id: drop.case_id });
        else { if (newState) applyState(newState); cs2.send("open", { case_id: drop.case_id }); }
      };
    }
  }
  function hideOpening() {
    $("#opening").classList.add("hidden");
    $("#screenglow").classList.remove("on");
  }

  // ---- state + bridge ------------------------------------------------------
  function applyState(s) { window.__state = s; $("#balance").textContent = s.balance.toFixed(2); }

  // Anki injects its pycmd bridge asynchronously, so on first paint it may not exist
  // yet. Wait for it rather than firing (and warning) too early.
  function bridgeReady() { return typeof pycmd === "function"; }
  function whenBridgeReady(cb, tries) {
    tries = tries == null ? 60 : tries;   // ~3s of 50ms polls
    if (bridgeReady()) { cb(); return; }
    if (tries <= 0) return;               // give up quietly — the boot state is already shown
    setTimeout(function () { whenBridgeReady(cb, tries - 1); }, 50);
  }

  window.cs2 = {
    send: function (action, args) {
      if (!bridgeReady()) { toast("Bridge unavailable (pycmd missing).", true); return; }
      pycmd("cs2:" + action + (args ? ":" + JSON.stringify(args) : ""));
    },
    on: function (action, res) {
      if (action === "play") { startOpening(res.drop, res.reel, null); return; }         // overlay: case open
      if (action === "tradeup") { startTradeupReveal(res.drop); return; }                // overlay: trade-up
      if (!res || !res.ok) { toast((res && res.error) || "Something went wrong.", true); return; }
      if (action === "case_detail") {
        _storeDetail = res.case_detail;
        if (currentView() === "store") { renderStore(); scrollTop(); }
        return;
      }
      if (action === "open") { startOpening(res.drop, res.reel, res.state); return; }
      if (res.state) applyState(res.state);
      if (action === "sell") toast("Sold for $" + res.amount.toFixed(2));
      if (action === "sell_many") {
        _inv.sel = {};
        var msg = "Sold " + res.count + " skins for $" + res.amount.toFixed(2);
        if (res.protected) msg += " · " + res.protected + " favourite" + (res.protected > 1 ? "s" : "") + " kept";
        toast(msg);
      }
      if (action === "favorite") {
        toast((res.favorite ? "Favourited " : "Unfavourited ") + res.count + " skin" + (res.count > 1 ? "s" : ""));
      }
      render();
    }
  };

  // ---- init ----------------------------------------------------------------
  function init() {
    window.onerror = function (msg, src, line) {
      try { toast("JS error: " + msg + " (line " + line + ")", true); } catch (e) {}
    };
    var mode = window.__MODE__ || "market";
    var boot = window.__BOOT_STATE__ || { balance: 0, cases: [], inventory: [], rarities: {},
      wear_tiers: [], trade_up_order: [], config: {}, asset_base: "" };
    applyState(boot);
    initSounds();   // after state so per-rarity sound files are known

    if (mode === "overlay") {
      // Full-window opening overlay: no chrome, just wait for a "play" push.
      document.body.classList.add("overlay-mode");
      return;
    }
    // Market panel (sidebar): tabs + views. Openings are launched into the overlay.
    document.querySelectorAll(".tab").forEach(function (t) {
      t.onclick = function () { setView(t.getAttribute("data-view")); };
    });
    render();
    // Refresh from Python once the bridge is actually up (the page already rendered
    // from the injected boot state, so there's nothing to wait on visually).
    whenBridgeReady(function () { cs2.send("state"); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
