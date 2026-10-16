/* Veiled Eye — runtime helper for the web UI.
 *
 * Loaded before the Angular bundle (see tools/ui_build/patch.py). The
 * bundle is patched in three tiny places to call into this object:
 *   - quick search  -> window.__veiled.form(term)   (auto-detects the selector)
 *   - gatherAdvance / gatherAdvanceIncremental -> window.__veiled.extend(...)
 *     which fires the identity modules the stock UI does not know about.
 *
 * It also renders "More sources": the stock Gatherer page only has cards
 * for its own modules, so results of the extended modules (maigret,
 * dark-sherlock, phone, crypto, ...) are captured from /result responses
 * and drawn as Veiled Eye cards under the stock ones.
 *
 * Every captured result is also kept in a small store (window.__veiled.
 * state()) that the relationship graph (graph.js, /graph) is built from.
 */
(function () {
  "use strict";

  // theme scope for veiled.css (outranks the Angular component styles)
  document.documentElement.classList.add("ve");

  var EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
  var PHONE = /^\+?[\d\s().\-]{7,20}$/;
  var WALLET = /^(0x[a-fA-F0-9]{40}|(bc1|ltc1)[a-z0-9]{20,90}|T[1-9A-HJ-NP-Za-km-z]{33}|[13LMD][1-9A-HJ-NP-Za-km-z]{25,34}|[48][1-9A-HJ-NP-Za-km-z]{94})$/;

  // Identity modules for a username / handle (same set as backend chain.py)
  var USERNAME_MODULES = [
    "maigret", "userscanner", "darksherlock", "whatsmyname", "telegram",
    "steam", "bluesky", "hackernews", "stackexchange", "kick", "snapchat",
    "instagram", "wayback", "pgp", "ahmia", "darkweb",
  ];
  var EMAIL_MODULES = ["userscanner", "emailreg", "gravatar", "pgp", "ahmia", "darkweb"];

  function kind(value) {
    var v = String(value || "").trim();
    if (!v) return "empty";
    if (EMAIL.test(v)) return "email";
    if (WALLET.test(v)) return "wallet";
    var digits = v.replace(/[\s().\-]/g, "");
    if ((v.charAt(0) === "+" && PHONE.test(v) && digits.length >= 9) || /^0?\d{10,14}$/.test(digits)) return "phone";
    return "username";
  }

  function emptyForm() {
    return {
      email: "", username: "", twitter: "", instagram: "", linkedin: "",
      github: "", tiktok: "", tinder: "", venmo: "", reddit: "", spotify: "",
      twitch: "", keybase: "", mastodon: "", youtube: "",
    };
  }

  // Quick search. Several selectors can be given at once, separated by
  // commas, semicolons or new lines ("john@acme.com, johndoe, +90532...").
  // The first e-mail fills the e-mail field, the first other selector the
  // username field; the rest run through extend() as extra roots.
  var extras = [];
  var roots = [];          // selectors the analyst typed for the current case
  var results = {};        // "module|param" -> raw result (every module)
  var listeners = [];
  var storeRef = null;     // the Angular gatherer store (set by extend)

  // The case survives a page reload (this tab only). Storage can be
  // unavailable or full: the graph then just starts empty after a reload.
  var CASE_KEY = "veiled:case";
  var saveTimer = 0;
  try {
    var saved = JSON.parse(sessionStorage.getItem(CASE_KEY) || "null");
    if (saved && saved.results && typeof saved.results === "object") {
      results = saved.results;
      roots = Array.isArray(saved.roots) ? saved.roots : [];
    }
  } catch (e) { /* no storage */ }

  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try { sessionStorage.setItem(CASE_KEY, JSON.stringify({ roots: roots, results: results })); }
      catch (e) { try { sessionStorage.removeItem(CASE_KEY); } catch (e2) { /* no storage */ } }
    }, 800);
  }

  function notify() {
    save();
    listeners.forEach(function (fn) { try { fn(); } catch (e) { /* listener error */ } });
  }

  function splitTerms(term) {
    return String(term || "")
      .split(/[,;\n]+/)
      .map(function (t) { return t.trim().replace(/^@(?=[^@]+$)/, ""); })
      .filter(Boolean);
  }

  function form(term) {
    var f = emptyForm();
    extras = [];
    splitTerms(term).forEach(function (t) {
      var k = kind(t);
      if (k === "email" && !f.email) f.email = t;
      else if (k !== "email" && !f.username) f.username = t;
      else extras.push(t);
    });
    return f;
  }

  function runFor(run, value) {
    var k = kind(value);
    if (k === "phone") run("phone", value, "User", 100);
    else if (k === "wallet") run("crypto", value, "User", 100);
    else if (k === "email") ["holehe", "emailrep"].concat(EMAIL_MODULES).forEach(function (m) { run(m, value, "User", 100); });
    else ["github", "search"].concat(USERNAME_MODULES).forEach(function (m) { run(m, value, "User", 100); });
  }

  function extend(store, e, gate, fresh) {
    storeRef = store;
    if (fresh) {
      resetFeed();
      results = {};
      sideSeen = {};
      sideQueue = [];
      generation++;
      roots = [e && e.email, e && e.username].concat(extras).filter(Boolean).map(String);
      notify();
    }
    try {
      var run = function (module, param, from, score) {
        if (param && (!gate || gate(module))) store.executeIfAllowed(module, param, from, score);
      };
      if (e && e.username) {
        var u = String(e.username).trim();
        var k = kind(u);
        if (k === "phone") run("phone", u, "User", 100);
        else if (k === "wallet") run("crypto", u, "User", 100);
        else if (k === "email") EMAIL_MODULES.forEach(function (m) { run(m, u, "User", 100); });
        else ["github"].concat(USERNAME_MODULES).forEach(function (m) { run(m, u.replace(/^@/, ""), "User", 100); });
      }
      if (e && e.email) {
        EMAIL_MODULES.forEach(function (m) { run(m, e.email, "User", 100); });
        if (!e.username) {
          var local = String(e.email).split("@")[0];
          USERNAME_MODULES.forEach(function (m) { run(m, local, "auto", 1); });
        }
      }
      if (fresh && extras.length) {
        var more = extras;
        extras = [];
        more.forEach(function (v) { runFor(run, v); });
      }
    } catch (err) {
      if (window.console) console.warn("veiled extend failed", err);
    }
  }


  // ------------------------------------------------------------------
  // More sources (results of the extended modules)
  // ------------------------------------------------------------------
  var NATIVE = {
    emailrep: 1, leaklookup: 1, holehe: 1, peopledatalabs: 1, leaks: 1,
    socialscan: 1, hudsonrock: 1, dorks: 1, search: 1, github: 1, keybase: 1,
    linkedin: 1, mastodon: 1, reddit: 1, spotify: 1, tiktok: 1, twitch: 1,
    twitter: 1, venmo: 1, youtube: 1, tweetiment: 1, twitter_info: 1,
    twitter_infos: 1, twitter_comp: 1, twitter_comps: 1, instagram: 1, tinder: 1,
  };
  var LABEL = {
    maigret: "Maigret", userscanner: "User-Scanner", darksherlock: "Dark-Sherlock",
    whatsmyname: "WhatsMyName", telegram: "Telegram", steam: "Steam",
    bluesky: "Bluesky", hackernews: "Hacker News", stackexchange: "Stack Exchange",
    kick: "Kick", snapchat: "Snapchat", wayback: "Wayback Machine", pgp: "PGP keys",
    ahmia: "Ahmia (.onion)", darkweb: "Dark web", gravatar: "Gravatar", emailreg: "E-mail registrations", domaininfo: "Domain",
    phone: "Phone", crypto: "Crypto wallet", crossref: "Cross-analysis",
    gitsniff: "GitSniff", crosslinked: "CrossLinked", gitlab: "GitLab",
    // stock modules (names used by the graph)
    github: "GitHub", twitter: "Twitter / X", instagram: "Instagram", reddit: "Reddit",
    linkedin: "LinkedIn", tiktok: "TikTok", keybase: "Keybase", mastodon: "Mastodon",
    spotify: "Spotify", twitch: "Twitch", youtube: "YouTube", venmo: "Venmo",
    holehe: "Holehe", emailrep: "EmailRep", leaklookup: "Leak-Lookup", peopledatalabs: "People Data Labs",
    leaks: "Leaks", socialscan: "SocialScan", hudsonrock: "Hudson Rock", dorks: "Dorks", search: "Web search",
  };
  var ICON = {
    maigret: "fas fa-user-astronaut", userscanner: "fas fa-user-check",
    darksherlock: "fas fa-user-secret", whatsmyname: "fas fa-id-badge",
    telegram: "fab fa-telegram", steam: "fab fa-steam", bluesky: "fas fa-cloud",
    hackernews: "fab fa-hacker-news", stackexchange: "fab fa-stack-exchange",
    kick: "fas fa-video", snapchat: "fab fa-snapchat", wayback: "fas fa-clock-rotate-left",
    pgp: "fas fa-key", ahmia: "fas fa-mask", darkweb: "fas fa-spider",
    gravatar: "fas fa-circle-user", emailreg: "fas fa-envelope-open-text", domaininfo: "fas fa-globe", phone: "fas fa-phone", crypto: "fas fa-wallet",
    crossref: "fas fa-diagram-project", gitsniff: "fab fa-git-alt",
    crosslinked: "fab fa-linkedin", gitlab: "fab fa-gitlab",
  };
  var MAX_ROWS = 40;
  var CAT_LABEL = {
    underground: "Underground forum", forum: "Forum", social: "Social network",
    messaging: "Messaging", dev: "Developer", coding: "Developer", gaming: "Gaming",
    video: "Video", music: "Music", art: "Art and design", photo: "Photo",
    dating: "Dating", finance: "Finance", crypto: "Crypto", shopping: "Shopping",
    blog: "Blog", identity: "Keys and identity", professional: "Professional",
  };

  var NETWORK = /HTTP 0|ConnectionPool|Max retries|ProxyError|timed? ?out|network|erisilemedi|not reachable|blocked/i;

  // Backend reasons can be raw exception text; keep the useful part.
  function cleanReason(r) {
    r = String(r || "").replace(/^warn: /, "").trim();
    if (!r) return "The source returned an error.";
    if (NETWORK.test(r)) {
      var host = (r.match(/https?:\/\/([^/\s'"]+)/) || r.match(/host='([^']+)'/) || [])[1];
      return "Could not reach " + (host || "the source") + ". Check the network or proxy and run the search again.";
    }
    return r.length > 160 ? r.slice(0, 157) + "..." : r;
  }
  var feed = {};          // "module|param" -> parsed result
  var edges = [];         // pivot trail: {from, module, to, via}
  var ran = {};           // selector -> modules that answered for it
  var order = [];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) {
    u = String(u || "");
    return /^https?:\/\//i.test(u) ? u : "";
  }
  function pick(result, key) {
    for (var i = 0; i < result.length; i++) {
      var el = result[i];
      if (el && typeof el === "object" && key in el) return el[key];
    }
    return undefined;
  }

  // force: a stock module run here for a second value (the stock card only
  // shows the first one), so it gets a feed card too
  function parse(result, force) {
    if (!Array.isArray(result)) return null;
    var module = pick(result, "module");
    if (!module || (NATIVE[module] && !force)) return null;
    var raw = pick(result, "raw");
    var head = Array.isArray(raw) && raw[0] && raw[0].status ? raw[0] : null;
    var graphic = pick(result, "graphic") || [];
    var nodes = [];
    for (var g = 0; g < graphic.length; g++) {
      if (graphic[g] && Array.isArray(graphic[g][module])) { nodes = graphic[g][module]; break; }
    }
    var cats = {};
    var profile = pick(result, "profile") || [];
    profile.forEach(function (p) {
      (p && p.social || []).forEach(function (s) {
        if (s && s.url) cats[s.url] = s.category || "";
        if (s && s.name) cats["name:" + String(s.name).toLowerCase()] = s.category || "";
      });
    });
    var extra = {};
    for (var gi = 0; gi < graphic.length; gi++) {
      var gk = graphic[gi] && Object.keys(graphic[gi])[0];
      if (gk === "activity" || gk === "places") extra[gk] = graphic[gi][gk];
    }
    return {
      activity: extra.activity || null,
      module: module,
      param: pick(result, "param") || "",
      validation: pick(result, "validation") || "",
      status: head ? String(head.status).toLowerCase() : "ok",
      reason: head ? (head.reason || "") : "",
      root: nodes[0] || null,
      rows: nodes.slice(1),
      cats: cats,
    };
  }

  function catOf(item, row) {
    var c = item.cats[row.help] || item.cats["name:" + String(row.title || "").toLowerCase()] || "";
    return String(c).split(",")[0].trim().toLowerCase();
  }

  // 24 bars of activity by UTC hour, with the local-time estimate.
  function activityHtml(a) {
    if (!a || !a.samples) return "";
    var max = Math.max.apply(null, a.hours_utc) || 1;
    var bars = a.hours_utc.map(function (n, h) {
      var hgt = Math.max(2, Math.round((n / max) * 40));
      return '<rect x="' + (h * 11) + '" y="' + (44 - hgt) + '" width="8" height="' + hgt + '" rx="1"><title>' +
        (h < 10 ? "0" : "") + h + ":00 UTC — " + n + "</title></rect>";
    }).join("");
    return '<div class="ve-act"><svg viewBox="0 0 264 58" role="img" aria-label="Activity by hour (UTC)">' + bars +
      '<text x="0" y="56">00</text><text x="121" y="56">12</text><text x="264" y="56" text-anchor="end">23 UTC</text></svg>' +
      '<p>' + (a.estimate ? "Likely time zone <b>" + esc(a.estimate) + "</b> — " : "") + esc(a.basis) + "</p></div>";
  }

  function cardHtml(item) {
    var label = LABEL[item.module] || item.module;
    var sub = item.root && item.root.subtitle ? item.root.subtitle : (item.rows.length + (item.rows.length === 1 ? " result" : " results"));
    var icon = ICON[item.module] || (item.root && item.root.icon) || "fas fa-eye";
    var h = '<article class="ve-card ve-' + esc(item.status) + '">' +
      '<header class="ve-card-h"><i class="' + esc(icon) + '"></i>' +
      '<span class="ve-card-t">' + esc(label) + '</span>' +
      '<span class="ve-card-p">' + esc(item.param) + '</span>' +
      '<span class="ve-card-n">' + esc(sub) + '</span>' +
      '<span class="ve-val ve-val-' + esc(item.validation) + '" title="validation: ' + esc(item.validation) + '"></span></header>';
    h += activityHtml(item.activity);
    if (item.status !== "ok") {
      h += '<div class="ve-card-msg">' + esc(cleanReason(item.reason)) + "</div>";
    } else if (!item.rows.length) {
      h += '<div class="ve-card-msg">Nothing found for this selector.</div>';
    } else {
      h += '<ul class="ve-rows">';
      item.rows.slice(0, MAX_ROWS).forEach(function (r) {
        if (r.handles && r.handles.length) { h += handlesRow(r); return; }
        if (r.picture) { h += reverseRow(r); return; }
        var url = safeUrl(r.help);
        var cat = catOf(item, r);
        var title = esc(r.title || r["name-node"] || "");
        h += "<li>" +
          '<i class="' + esc(r.icon || "fas fa-angle-right") + '"></i>' +
          '<span class="ve-r-t">' + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + title + "</a>" : title) + "</span>" +
          (function () {
            // with a category label the subtitle is usually the same tag;
            // show where the account lives instead
            var plain = String(r.subtitle || "").toLowerCase();
            var isTag = !plain || plain === cat || plain.split(",")[0].trim() === cat;
            var sub = cat && url && isTag ? url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "") : r.subtitle;
            return sub ? '<span class="ve-r-s">' + esc(sub) + "</span>" : "";
          })() +
          (cat ? '<span class="ve-cat ve-cat-' + esc(cat.replace(/[^a-z]/g, "")) + '">' + esc(CAT_LABEL[cat] || (cat.charAt(0).toUpperCase() + cat.slice(1))) + "</span>" : "") +
          (!url && r.help ? '<span class="ve-r-h">' + esc(r.help) + "</span>" : "") +
          "</li>";
      });
      if (item.rows.length > MAX_ROWS) h += '<li class="ve-more">' + (item.rows.length - MAX_ROWS) + " more on the Identity page</li>";
      h += "</ul>";
    }
    return h + "</article>";
  }

  // "Handle patterns to try": each one starts a search when clicked.
  function handlesRow(r) {
    return '<li class="ve-row-wide"><i class="' + esc(r.icon || "fas fa-user-tag") + '"></i>' +
      '<span class="ve-r-t">' + esc(r.title) + '</span><span class="ve-r-s ve-chips">' +
      r.handles.map(function (hd) {
        return '<button type="button" class="ve-chip" data-ve-search="' + esc(hd) + '" title="Search ' + esc(hd) + '">' + esc(hd) + "</button>";
      }).join("") + "</span></li>";
  }

  // Reverse image search on three engines for one picture.
  function reverseRow(r) {
    var links = reverseLinks(r.picture);
    return '<li class="ve-row-wide"><i class="fas fa-magnifying-glass"></i>' +
      '<span class="ve-r-t">' + esc(r.title) + '</span><span class="ve-r-s ve-chips">' +
      '<img class="ve-thumb" src="' + esc(safeUrl(r.picture)) + '" alt="" loading="lazy" referrerpolicy="no-referrer">' +
      Object.keys(links).map(function (k) {
        return '<a class="ve-chip" href="' + esc(links[k]) + '" target="_blank" rel="noopener noreferrer">' + esc(k) + "</a>";
      }).join("") + (r.subtitle ? '<span class="ve-chip-note">' + esc(r.subtitle) + "</span>" : "") + "</span></li>";
  }

  function reverseLinks(picture) {
    var u = encodeURIComponent(String(picture || ""));
    return {
      Yandex: "https://yandex.com/images/search?rpt=imageview&url=" + u,
      Bing: "https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:" + u,
      "Google Lens": "https://lens.google.com/uploadbyurl?url=" + u,
    };
  }

  // Start a new search from the UI (same path as typing it in the search box).
  function search(value) {
    var btn = document.querySelector(".header-search-btn");
    if (!btn) return;
    btn.click();
    setTimeout(function () {
      var input = document.querySelector("vey-search-overlay input");
      if (!input) return;
      input.focus();
      if (!value) return; // just open the search box
      input.value = String(value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
    }, 350);
  }

  document.addEventListener("click", function (ev) {
    var t = ev.target && ev.target.closest && ev.target.closest("[data-ve-search]");
    if (t) { ev.preventDefault(); search(t.getAttribute("data-ve-search")); }
  });

  // findings first, then empty, then failed modules
  function ranked() {
    function rank(it) { return it.status !== "ok" ? 2 : (it.rows.length ? 0 : 1); }
    return order.slice().sort(function (a, b) { return rank(feed[a]) - rank(feed[b]); });
  }

  var renderQueued = false;
  function render() {
    renderQueued = false;
    var shell = document.querySelector(".gatherer-page");
    if (!shell) return;
    var box = document.getElementById("ve-feed");
    if (!box) {
      box = document.createElement("section");
      box.id = "ve-feed";
      shell.appendChild(box);
    }
    if (!order.length && !edges.length) { box.innerHTML = ""; box.hidden = true; return; }
    box.hidden = false;
    // Cards only for modules that found something; the rest collapse into
    // two short lines so the page is not a wall of empty boxes.
    var found = 0, cards = [], empty = [], down = [];
    ranked().forEach(function (k) {
      var it = feed[k];
      var label = LABEL[it.module] || it.module;
      if (it.status === "ok" && it.rows.length) { found += it.rows.length; cards.push(cardHtml(it)); }
      else if (it.status === "fail" || NETWORK.test(it.reason || "")) down.push('<span title="' + esc(cleanReason(it.reason)) + '">' + esc(label) + "</span>");
      else empty.push(esc(label));
    });
    var html =
      '<div class="ve-feed-h"><h2 class="ve-feed-t">More sources</h2>' +
      '<span class="ve-feed-s">' + found + (found === 1 ? " result" : " results") + " from " + order.length + " modules</span></div>";
    if (cards.length) html += '<div class="ve-grid">' + cards.join("") + "</div>";
    if (empty.length) html += '<p class="ve-line"><span class="ve-line-k">No results</span>' + empty.join(", ") + "</p>";
    if (down.length) html += '<p class="ve-line"><span class="ve-line-k ve-bad">Could not reach</span>' + down.join(", ") +
      '<span class="ve-line-hint">Hover a name for details. Check the network or proxy, then run the search again.</span></p>';
    box.innerHTML = html + trailHtml();
  }
  function queueRender() {
    if (renderQueued) return;
    renderQueued = true;
    (window.requestAnimationFrame || setTimeout)(render);
  }
  function resetFeed() { feed = {}; order = []; edges = []; ran = {}; queueRender(); }

  function recordEdges(result) {
    if (!Array.isArray(result)) return;
    var module = pick(result, "module"), param = String(pick(result, "param") || "");
    if (!module || !param) return;
    (ran[param.toLowerCase()] = ran[param.toLowerCase()] || {})[module] = 1;
    (pick(result, "tasks") || []).forEach(function (t) {
      if (!t || !t.param || String(t.param).toLowerCase() === param.toLowerCase()) return;
      var dup = edges.some(function (x) { return x.from === param && x.to === t.param && x.module === module; });
      if (!dup) edges.push({ from: param, module: module, to: String(t.param), via: t.module });
    });
  }

  // Pivot trail: which finding led to which selector, from the roots the
  // analyst typed. Each selector lists the modules that answered for it.
  function trailHtml() {
    if (!edges.length) return "";
    var targets = {};
    edges.forEach(function (e) { targets[e.to.toLowerCase()] = 1; });
    var roots = [];
    edges.forEach(function (e) {
      if (!targets[e.from.toLowerCase()] && roots.indexOf(e.from) < 0) roots.push(e.from);
    });
    var shown = {};
    function branch(sel, depth) {
      if (depth > 3 || shown[sel.toLowerCase()]) return "";
      shown[sel.toLowerCase()] = 1;
      var kids = {};
      edges.forEach(function (e) {
        if (e.from.toLowerCase() !== sel.toLowerCase()) return;
        (kids[e.to] = kids[e.to] || []).indexOf(e.module) < 0 && kids[e.to].push(e.module);
      });
      var names = Object.keys(kids);
      if (!names.length) return "";
      return "<ul>" + names.map(function (to) {
        var mods = Object.keys(ran[to.toLowerCase()] || {});
        return '<li><span class="ve-tr-sel">' + esc(to) + '</span>' +
          '<span class="ve-tr-via">found by ' + esc(kids[to].map(function (m) { return LABEL[m] || m; }).join(", ")) + "</span>" +
          (mods.length ? '<span class="ve-tr-ran">' + mods.length + (mods.length === 1 ? " source checked" : " sources checked") + "</span>" : "") +
          branch(to, depth + 1) + "</li>";
      }).join("") + "</ul>";
    }
    var body = roots.map(function (r) {
      return '<li class="ve-tr-root"><span class="ve-tr-sel">' + esc(r) + "</span>" + branch(r, 1) + "</li>";
    }).join("");
    return '<section class="ve-trail"><h3 class="ve-trail-t">Pivot trail</h3><ul>' + body + "</ul></section>";
  }

  // ------------------------------------------------------------------
  // Lead follower. The stock store runs each module for one value only
  // (a second username for maigret, a second e-mail for emailreg... is
  // refused), which would drop most pivots. Leads the store refuses are
  // run here instead, two at a time, and land in the feed and the graph.
  // ------------------------------------------------------------------
  var sideSeen = {}, sideQueue = [], sideActive = 0, generation = 0, SIDE_MAX = 2;

  function taskexec() {
    try { return (storeRef && storeRef.gathered && storeRef.gathered().taskexec) || []; } catch (e) { return []; }
  }
  function allowedModules() {
    try {
      var tl = storeRef && storeRef.taskList && storeRef.taskList();
      return tl && tl.modules ? tl.modules : null;
    } catch (e) { return null; }
  }
  function same(a, b) { return String(a).trim().toLowerCase() === String(b).trim().toLowerCase(); }

  function follow(res, side) {
    var tasks = pick(res, "tasks");
    if (!Array.isArray(tasks) || !tasks.length || !storeRef) return;
    var from = pick(res, "module") || "auto";
    var mods = allowedModules();
    var claimed = {}; // module -> param the stock store will run from this response
    tasks.forEach(function (t) {
      if (!t || !t.module || t.param === undefined || t.param === "") return;
      var m = t.module, p = String(t.param);
      if (mods && mods.indexOf(m) < 0) return;
      if (results[m + "|" + p] || sideSeen[m + "|" + p.toLowerCase()]) return;
      var runs = taskexec().filter(function (r) { return r.module === m; });
      if (runs.some(function (r) { return same(r.param, p); })) return;
      if (!runs.length && !claimed[m]) {
        claimed[m] = p;
        // nothing ran for this module yet: the store takes it (its own card)
        if (side) storeRef.executeIfAllowed(m, p, from, 10);
        return;
      }
      if (claimed[m] && same(claimed[m], p)) return;
      sideSeen[m + "|" + p.toLowerCase()] = 1;
      sideQueue.push({ module: m, param: p, from: from, gen: generation });
    });
    pumpSide();
  }

  function api(path) { return "/api/" + path; }

  function pumpSide() {
    while (sideActive < SIDE_MAX && sideQueue.length) {
      var job = sideQueue.shift();
      if (job.gen !== generation) continue;
      sideActive++;
      runSide(job).then(done, done);
    }
    function done() { sideActive--; pumpSide(); }
  }

  function runSide(job) {
    var F0 = rawFetch || window.fetch;
    var body = { username: job.param, from: job.from };
    if (job.module === "dorks") body.dorks = "";
    return F0(api(job.module), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (sent) {
      if (!sent || !sent.task) return null;
      var tries = 0;
      var poll = function () {
        if (job.gen !== generation) return null;
        tries++;
        return F0(api("result/" + encodeURIComponent(sent.task) + "?wait=20")).then(function (r) {
          if (r.status === 504 && tries < 60) return poll();
          if (!r.ok) return null;
          return r.text().then(function (txt) { if (job.gen === generation) capture(api("result/" + sent.task), txt, true); });
        }, function () { return tries < 60 ? new Promise(function (ok) { setTimeout(ok, 3000); }).then(poll) : null; });
      };
      return poll();
    });
  }

  function capture(url, text, side) {
    if (!/\/result\//.test(url || "")) return;
    try {
      var body = JSON.parse(text);
      var res = body && body.result;
      if (Array.isArray(res)) {
        results[pick(res, "module") + "|" + pick(res, "param")] = res;
        notify();
        follow(res, !!side);
      }
      recordEdges(res);
      queueRender();
      var item = parse(body && body.result, !!side);
      if (!item) return;
      var key = item.module + "|" + item.param;
      if (!feed[key]) order.push(key);
      feed[key] = item;
      queueRender();
    } catch (err) { /* not JSON / not a module result */ }
  }

  // Angular's HttpClient may use fetch() or XHR depending on the build:
  // hook both (read-only — responses are cloned, never modified).
  var rawFetch = null;
  if (window.fetch) {
    var F = window.fetch;
    rawFetch = function () { return F.apply(window, arguments); };
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var pr = F.apply(this, arguments);
      if (/\/api\/apikey/.test(url)) {
        return pr.then(function (res) {
          try { res.clone().json().then(rememberKeys, function () {}); } catch (e) { /* opaque */ }
          return res;
        });
      }
      if (!/\/result\//.test(url)) return pr;
      // Read a clone *before* handing the response to Angular: Angular
      // aborts the request once it has consumed the body, which would also
      // kill a clone read later. The tee keeps the original body intact.
      return pr.then(function (res) {
        if (!res || !res.ok) return res;
        var copy;
        try { copy = res.clone(); } catch (e) { return res; }
        return copy.text().then(function (txt) { capture(url, txt); return res; }, function () { return res; });
      });
    };
  }

  // XHR fallback (builds without withFetch()).
  var XO = XMLHttpRequest.prototype.open;
  var XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__veUrl = url;
    return XO.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    var xhr = this;
    if (/\/result\//.test(xhr.__veUrl || "")) {
      xhr.addEventListener("load", function () {
        if (xhr.status === 200 && (xhr.responseType === "" || xhr.responseType === "text")) capture(xhr.__veUrl, xhr.responseText);
        else if (xhr.status === 200 && xhr.responseType === "json") capture(xhr.__veUrl, JSON.stringify(xhr.response));
      });
    }
    return XS.apply(this, arguments);
  };

  // Home: a real search entry point instead of a decorative hero.
  // Home: the eye in the middle, the platforms it watches in orbit.
  var ORBIT = [
    // [icon, background, foreground, ring]
    ["fa-github", "#f5f7f9", "#0d1117", 1], ["fa-telegram", "#29a9eb", "#fff", 1],
    ["fa-discord", "#5865f2", "#fff", 1], ["fa-instagram", "linear-gradient(45deg,#f9ce34,#ee2a7b 55%,#6228d7)", "#fff", 1],
    ["fa-reddit-alien", "#ff4500", "#fff", 1], ["fa-x-twitter", "#000", "#fff", 1],
    ["fa-tiktok", "#010101", "#fff", 2], ["fa-snapchat", "#fffc00", "#111", 2],
    ["fa-youtube", "#ff0033", "#fff", 2], ["fa-linkedin-in", "#0a66c2", "#fff", 2],
    ["fa-steam", "#1b2838", "#c7d5e0", 2], ["fa-spotify", "#1ed760", "#000", 2],
    ["fa-twitch", "#9146ff", "#fff", 2], ["fa-facebook-f", "#1877f2", "#fff", 2],
    ["fa-mastodon", "#6364ff", "#fff", 2], ["fa-soundcloud", "#ff5500", "#fff", 2],
  ];

  function heroHtml() {
    var rings = { 1: [], 2: [] };
    ORBIT.forEach(function (o) { rings[o[3]].push(o); });
    var h = '<div class="ve-orbit" aria-hidden="true">';
    [1, 2].forEach(function (r) {
      var list = rings[r];
      h += '<div class="ve-ring ve-ring-' + r + '">';
      list.forEach(function (o, i) {
        var a = (360 / list.length) * i + (r === 2 ? 11 : 0);
        h += '<span class="ve-planet" style="--a:' + a + 'deg;--bg:' + o[1] + ';--fg:' + o[2] + '">' +
          '<i class="fa-brands ' + o[0] + '"></i></span>';
      });
      h += "</div>";
    });
    h += '<div class="ve-core"><span class="ve-reticle"></span><span class="ve-scan"></span>' +
      '<img src="assets/images/logo.png" alt=""></div></div>' +
      '<h1 class="ve-hero-t">Veiled Eye</h1><p class="ve-hero-s">Every shadow has a story</p>';
    return h;
  }

  function homeSearch() {
    var body = document.querySelector(".principal-layout .logo-body");
    if (!body || body.querySelector(".ve-hero")) return;
    var hero = document.createElement("div");
    hero.className = "ve-hero";
    hero.innerHTML = heroHtml();
    var b = document.createElement("button");
    b.type = "button";
    b.className = "ve-home-search";
    b.innerHTML = '<i class="fas fa-magnifying-glass"></i><span>E-mail, username, phone or wallet</span>';
    b.addEventListener("click", function () {
      var btn = document.querySelector(".header-search-btn");
      if (btn) btn.click();
    });
    hero.appendChild(b);
    body.appendChild(hero);
  }

  // ------------------------------------------------------------------
  // Relationship graph page (/graph). Libraries load on first visit.
  // ------------------------------------------------------------------
  var GRAPH_ASSETS = [
    "assets/graph/cytoscape.min.js",
    "assets/graph/layout-base.js",
    "assets/graph/cose-base.js",
    "assets/graph/cytoscape-fcose.js",
    "graph.js",
  ];
  var graphLoading = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("could not load " + src)); };
      document.head.appendChild(s);
    });
  }

  function loadGraph() {
    if (!graphLoading) {
      // the UMD bundles must not see an AMD loader
      var savedDefine = window.define;
      window.define = undefined;
      graphLoading = GRAPH_ASSETS.reduce(function (p, src) {
        return p.then(function () { return loadScript(src); });
      }, Promise.resolve()).then(function () {
        window.define = savedDefine;
      }, function (err) {
        window.define = savedDefine;
        graphLoading = null;
        throw err;
      });
    }
    return graphLoading;
  }

  function onRoute() {
    var onAbout = /^\/about\/?$/.test(location.pathname);
    document.documentElement.classList.toggle("ve-on-about", onAbout);
    if (onAbout) showAbout(); else hideAbout();
    var onGraph = /^\/graph\/?$/.test(location.pathname);
    document.documentElement.classList.toggle("ve-on-graph", onGraph);
    if (onGraph) {
      loadGraph().then(function () {
        if (window.__veiledGraph) window.__veiledGraph.show();
      }, function (err) {
        if (window.console) console.error(err);
      });
    } else if (window.__veiledGraph) {
      window.__veiledGraph.hide();
    }
  }

  ["pushState", "replaceState"].forEach(function (fn) {
    var orig = history[fn];
    history[fn] = function () {
      var out = orig.apply(this, arguments);
      setTimeout(onRoute, 0);
      return out;
    };
  });
  window.addEventListener("popstate", onRoute);

  // Re-attach after Angular re-renders the Gatherer / Home page.
  function watch() {
    new MutationObserver(function () {
      homeSearch();
      keyAreas();
      advancedMore();
      reportButton();
      if (document.querySelector(".gatherer-page") && !document.getElementById("ve-feed")) queueRender();
    }).observe(document.body, { childList: true, subtree: true });
  }
  // ------------------------------------------------------------------
  // Report button: the toolbar's (disabled) "Report" now downloads the PDF
  // ------------------------------------------------------------------
  function caseTarget() {
    if (roots.length) return roots[0];
    var keys = Object.keys(results);
    return keys.length ? keys[0].split("|").slice(1).join("|") : "";
  }
  function downloadReport(fmt) {
    var t = caseTarget();
    if (!t) return;
    var a = document.createElement("a");
    a.href = "/api/export/" + encodeURIComponent(t) + "?format=" + (fmt || "pdf");
    a.target = "_blank";
    a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
  }
  function reportButton() {
    var b = document.querySelector('button.toolbar-action[title^="Generate report"]');
    if (!b || b.__ve) return;
    b.__ve = true;
    b.removeAttribute("disabled");
    b.disabled = false;
    b.title = "Download the PDF report (all sources, correlated)";
    b.classList.add("ve-report-btn");
    b.addEventListener("click", function (ev) { ev.preventDefault(); downloadReport("pdf"); });
  }

  // ------------------------------------------------------------------
  // Advanced search: phone number(s) and any number of extra selectors,
  // all investigated together with the e-mail and username of the form.
  // ------------------------------------------------------------------
  function advancedMore() {
    var groups = document.querySelectorAll(".adv-body .primary-field-group");
    if (groups.length < 2 || document.querySelector(".ve-adv-more")) return;
    var box = document.createElement("div");
    box.className = "ve-adv-more";
    box.innerHTML =
      '<div class="ve-adv-div"><span>Phone \u00b7 more selectors</span></div>' +
      '<div class="ve-adv-row"><i class="fas fa-phone"></i><input type="text" class="ve-adv-in" id="ve-adv-phone" autocomplete="off" ' +
      'placeholder="Phone number in international format, e.g. +90 532 123 45 67"></div>' +
      '<div class="ve-adv-row"><i class="fas fa-layer-group"></i><textarea class="ve-adv-in" id="ve-adv-extra" rows="2" spellcheck="false" ' +
      'placeholder="More e-mails, usernames, phones or wallets \u2014 one per line or comma separated. All of them are investigated together."></textarea></div>' +
      '<p class="ve-adv-hint" id="ve-adv-hint"></p>';
    groups[1].parentNode.insertBefore(box, groups[1].nextSibling);
    var hint = box.querySelector("#ve-adv-hint");
    var update = function () {
      var terms = advancedTerms();
      var kinds = {};
      terms.forEach(function (t) { var k = kind(t); kinds[k] = (kinds[k] || 0) + 1; });
      hint.textContent = terms.length ? terms.length + " extra selector" + (terms.length > 1 ? "s" : "") + ": " +
        Object.keys(kinds).map(function (k) { return kinds[k] + " " + k; }).join(", ") : "";
    };
    box.addEventListener("input", update);
    box.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && (ev.target.id === "ve-adv-phone" || ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        var go = document.querySelector(".adv-footer .search-btn");
        if (go) go.click();
      }
    });
  }

  function advancedTerms() {
    var p = document.getElementById("ve-adv-phone"), x = document.getElementById("ve-adv-extra");
    return splitTerms([p ? p.value : "", x ? x.value : ""].join("\n"));
  }

  // Runs before Angular's own click handler (capture phase).
  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest && ev.target.closest(".adv-footer .search-btn");
    if (!btn) return;
    var terms = advancedTerms();
    var user = document.querySelector('.adv-body .primary-field-group input.adv-input:not([placeholder="Email"])');
    var mail = document.querySelector('.adv-body input.adv-input[placeholder="Email"]');
    // the form needs an e-mail or a username to start: lend it the first term
    if (terms.length && user && !user.value.trim() && !(mail && mail.value.trim())) {
      // prefer a username (it fans out widest), then an e-mail, then anything
      var pickIdx = terms.findIndex(function (t) { return kind(t) === "username"; });
      if (pickIdx < 0) pickIdx = terms.findIndex(function (t) { return kind(t) === "email"; });
      if (pickIdx < 0) pickIdx = 0;
      var first = terms.splice(pickIdx, 1)[0];
      var target = kind(first) === "email" && mail ? mail : user;
      target.value = first;
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
    extras = terms;
  }, true);

  // ------------------------------------------------------------------
  // API keys page: multi-line editors for lists and cookie boxes
  // ------------------------------------------------------------------
  var keyCache = {};
  var MULTILINE = {
    proxy_list: "One proxy per line, e.g.\nhttp://user:pass@10.0.0.5:8080\nsocks5://127.0.0.1:9050\ntor",
    proxy_hosts: "One host per line (only these sites go through the proxies), e.g.\ninstagram.com\nx.com",
  };
  function rememberKeys(body) {
    var list = Array.isArray(body) ? body : (body && Array.isArray(body.keys) ? body.keys : []);
    list.forEach(function (k) { if (k && k.name) keyCache[k.name] = k.key || ""; });
  }
  function keyAreas() {
    document.querySelectorAll(".keys-row").forEach(function (row) {
      var nameEl = row.querySelector(".name-col");
      var name = nameEl ? nameEl.textContent.trim() : "";
      var multi = MULTILINE[name] !== undefined || /_cookies$/.test(name);
      if (!multi) return;
      row.classList.add("ve-multi");
      // read-only view keeps the line breaks: remember them for editing
      var shown = row.querySelector(".key-value");
      if (shown && !shown.classList.contains("empty")) keyCache[name] = shown.textContent.replace(/^\s+|\s+$/g, "");
      else if (shown) keyCache[name] = "";
      var input = row.querySelector("input.key-input");
      if (!input || input.__veArea) return;
      var ta = document.createElement("textarea");
      ta.className = "ve-key-area";
      ta.rows = /_cookies$/.test(name) ? 6 : 5;
      ta.spellcheck = false;
      ta.placeholder = MULTILINE[name] || "Paste the Cookie-Editor JSON export, or name=value; name=value";
      ta.value = keyCache[name] !== undefined ? keyCache[name] : input.value;
      input.__veArea = ta;
      // Angular reads event.target.value: serve it from the textarea so the
      // line breaks survive (an <input> drops them).
      Object.defineProperty(input, "value", {
        configurable: true,
        get: function () { return ta.value; },
        set: function (v) { if (v !== ta.value && v !== ta.value.replace(/\n/g, "")) ta.value = v; },
      });
      input.style.display = "none";
      input.parentNode.insertBefore(ta, input.nextSibling);
      var push = function () { input.dispatchEvent(new Event("input", { bubbles: true })); };
      ta.addEventListener("input", push);
      ta.addEventListener("keydown", function (ev) {
        var save = row.querySelector(".save-btn"), cancel = row.querySelector(".cancel-btn");
        if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && save) { ev.preventDefault(); push(); save.click(); }
        if (ev.key === "Escape" && cancel) { ev.preventDefault(); cancel.click(); }
      });
      push();
      setTimeout(function () { ta.focus(); }, 0);
    });
  }

  // ------------------------------------------------------------------
  // About page (/about)
  // ------------------------------------------------------------------
  var GROUPS = [
    ["Usernames", "fa-user-astronaut", ["maigret", "userscanner", "sherlock", "whatsmyname", "darksherlock", "socialscan", "usersearch"]],
    ["E-mail", "fa-envelope-open-text", ["holehe", "emailreg", "emailrep", "gravatar", "pgp", "leaks", "leaklookup", "hudsonrock", "peopledatalabs"]],
    ["Platforms", "fa-share-nodes", ["github", "gitlab", "twitter", "instagram", "linkedin", "tiktok", "reddit", "keybase", "mastodon", "youtube", "twitch", "spotify", "telegram", "steam", "bluesky", "hackernews", "stackexchange", "kick", "snapchat", "venmo"]],
    ["Code and companies", "fa-code-branch", ["gitsniff", "crosslinked", "domaininfo"]],
    ["Phone and wallets", "fa-mobile-screen", ["phone", "crypto"]],
    ["Web and dark web", "fa-globe", ["search", "dorks", "wayback", "ahmia", "darkweb"]],
    ["Analysis", "fa-diagram-project", ["crossref"]],
  ];
  var TOOLS = [
    ["maigret", "MIT", "https://github.com/soxoj/maigret"],
    ["user-scanner", "MIT", "https://github.com/kaifcodec/user-scanner"],
    ["holehe", "GPL-3.0", "https://github.com/megadose/holehe"],
    ["GitSniff", "MIT", "https://github.com/Reginald-Gillespie/GitSniff"],
    ["CrossLinked", "GPL-3.0", "https://github.com/m8sec/CrossLinked"],
    ["dark-sherlock", "MIT", "https://github.com/banaxou/dark-sherlock"],
    ["WhatsMyName", "CC BY-SA 4.0", "https://github.com/WebBreacher/WhatsMyName"],
    ["phonenumbers", "Apache-2.0", "https://github.com/daviddrysdale/python-phonenumbers"],
    ["Cytoscape.js + fCoSE", "MIT", "https://js.cytoscape.org"],
    ["FastAPI, Celery, Redis", "MIT / BSD", "https://fastapi.tiangolo.com"],
  ];
  var aboutEl = null, aboutData = null;

  function position(el) {
    var sb = document.querySelector(".layout-sidebar");
    var left = 0;
    if (sb) { var r = sb.getBoundingClientRect(); if (r.width > 0 && r.right < window.innerWidth * 0.6) left = r.right; }
    var header = document.querySelector(".layout-header, vey-header");
    var footer = document.querySelector(".layout-footer, vey-footer");
    var fr = footer && footer.getBoundingClientRect();
    el.style.left = left + "px";
    el.style.top = (header ? Math.max(0, header.getBoundingClientRect().bottom) : 56) + "px";
    el.style.bottom = (fr && fr.height && fr.top < window.innerHeight ? window.innerHeight - fr.top : 0) + "px";
  }

  function aboutHtml(d) {
    var have = {};
    (d.modules || []).forEach(function (m) { have[m.name] = m.summary; });
    var used = {};
    var h = '<div class="ve-about-in">' +
      '<header class="ve-ab-head"><img src="assets/images/logo.png" alt="" width="84" height="84">' +
      '<div><h1>Veiled Eye</h1><p>Identity investigation and OSINT correlation</p>' +
      '<p class="ve-ab-ver">Version ' + esc(d.version || "") + " \u00b7 " + Object.keys(have).length + " modules</p></div></header>" +
      '<section class="ve-ab-card"><h2>What it does</h2><p>Give it an e-mail address, a username, a phone number or a wallet. ' +
      "Veiled Eye checks them across public sources, follows the leads it finds (a commit e-mail, a linked account, a phone in a bio) " +
      "up to two steps deep, and correlates everything into one identity: accounts with a confidence grade, names, places, a timeline, " +
      "a relationship graph and a report you can export.</p></section>" +
      '<section class="ve-ab-card"><h2>Modules</h2><div class="ve-ab-groups">';
    GROUPS.forEach(function (g) {
      var list = g[2].filter(function (m) { return have[m] !== undefined; });
      if (!list.length) return;
      h += '<div class="ve-ab-group"><h3><i class="fas ' + g[1] + '"></i>' + esc(g[0]) + "<b>" + list.length + "</b></h3><ul>" +
        list.map(function (m) { used[m] = 1; return '<li title="' + esc(have[m]) + '"><span>' + esc(LABEL[m] || m) + "</span><small>" + esc(have[m]) + "</small></li>"; }).join("") + "</ul></div>";
    });
    var rest = Object.keys(have).filter(function (m) { return !used[m]; });
    if (rest.length) {
      h += '<div class="ve-ab-group"><h3><i class="fas fa-puzzle-piece"></i>Other<b>' + rest.length + "</b></h3><ul>" +
        rest.map(function (m) { return '<li><span>' + esc(LABEL[m] || m) + "</span><small>" + esc(have[m]) + "</small></li>"; }).join("") + "</ul></div>";
    }
    h += "</div></section>" +
      '<section class="ve-ab-card"><h2>Open-source tools inside</h2><ul class="ve-ab-tools">' +
      TOOLS.map(function (t) { return '<li><a href="' + esc(t[2]) + '" target="_blank" rel="noopener noreferrer">' + esc(t[0]) + "</a><span>" + esc(t[1]) + "</span></li>"; }).join("") +
      '</ul><p class="ve-ab-note">Licences and notices ship with the package (NOTICE, CREDITS.md).</p></section>' +
      '<section class="ve-ab-card ve-ab-legal"><h2>Responsible use</h2><p>Public sources only. Checks that would notify the person being searched are never run, ' +
      "and your API keys and cookies stay on this machine. Use it within the law and the terms of the sites it reads.</p></section>" +
      '<footer class="ve-ab-by"><span>Designed and developed by</span><a href="https://github.com/emrekybs" target="_blank" rel="noopener noreferrer">' +
      '<i class="fab fa-github"></i>Emre K\u00f6yba\u015f\u0131</a></footer></div>';
    return h;
  }

  function showAbout() {
    if (!aboutEl) {
      aboutEl = document.createElement("section");
      aboutEl.id = "ve-about";
      aboutEl.setAttribute("aria-label", "About Veiled Eye");
      document.body.appendChild(aboutEl);
      window.addEventListener("resize", function () { if (!aboutEl.hidden) position(aboutEl); });
    }
    aboutEl.hidden = false;
    position(aboutEl);
    var render = function (d) { aboutData = d; aboutEl.innerHTML = aboutHtml(d); };
    if (aboutData) render(aboutData);
    else {
      aboutEl.innerHTML = '<div class="ve-about-in"><p class="ve-ab-note">Loading\u2026</p></div>';
      (rawFetch || window.fetch)("/api/about").then(function (r) { return r.json(); }).then(render, function () {
        render({ version: "", modules: [] });
      });
    }
  }
  function hideAbout() { if (aboutEl) aboutEl.hidden = true; }

  // results kept from before a reload go back into the feed
  Object.keys(results).forEach(function (k) {
    var item = parse(results[k]);
    recordEdges(results[k]);
    if (item) { if (!feed[k]) order.push(k); feed[k] = item; }
  });

  if (document.body) { watch(); onRoute(); }
  else document.addEventListener("DOMContentLoaded", function () { watch(); onRoute(); });

  window.__veiled = {
    kind: kind, form: form, extend: extend, reset: resetFeed, search: search, report: downloadReport,
    reverseLinks: reverseLinks, label: function (m) { return LABEL[m] || m; },
    catLabel: function (c) { return CAT_LABEL[c] || c; },
    state: function () { return { results: results, roots: roots.slice() }; },
    subscribe: function (fn) { listeners.push(fn); },
    USERNAME_MODULES: USERNAME_MODULES, EMAIL_MODULES: EMAIL_MODULES,
  };
})();
