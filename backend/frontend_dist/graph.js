/* Veiled Eye — relationship graph (/graph).
 *
 * Built from every module result veiled.js captured for the current case
 * (window.__veiled.state()). Nothing is fetched here: the graph is a view of
 * what the sources already returned.
 *
 *   subject ── selector (e-mail, username, phone, wallet, domain)
 *                 ├── account   (platform + handle, found by which modules)
 *                 ├── fact      (name, organisation, place)
 *                 └┄┄ pivot ┄┄> selector found in a result and followed
 *
 * Accounts carry the cross-analysis grade (confirmed / likely / candidate)
 * and accounts that share a profile picture are joined.
 *
 * Libraries (vendored, MIT): Cytoscape.js, layout-base, cose-base,
 * cytoscape-fcose. Loaded by veiled.js the first time /graph is opened.
 */
(function () {
  "use strict";

  var V = window.__veiled;
  var cytoscape = window.cytoscape;
  if (!V || !cytoscape) return;
  if (window.cytoscapeFcose && !cytoscape.__veFcose) {
    try { cytoscape.use(window.cytoscapeFcose); } catch (e) { /* already registered */ }
    cytoscape.__veFcose = true;
  }

  // ------------------------------------------------------------------
  // Vocabulary
  // ------------------------------------------------------------------
  var TYPES = {
    subject:  { label: "Subject",        color: "#e4e7eb", size: 66 },
    email:    { label: "E-mail",         color: "#4fd2ff", size: 40 },
    username: { label: "Username",       color: "#b4bdc8", size: 40 },
    phone:    { label: "Phone",          color: "#00d68f", size: 40 },
    wallet:   { label: "Wallet",         color: "#ffc94d", size: 40 },
    domain:   { label: "Domain",         color: "#7cc4ff", size: 38 },
    account:  { label: "Account",        color: "#9aa5b1", size: 40 },
    signup:   { label: "Registration",   color: "#6b7480", size: 30 },
    name:     { label: "Name",           color: "#d9dde2", size: 30 },
    org:      { label: "Organisation",   color: "#a78bfa", size: 30 },
    place:    { label: "Place",          color: "#ffa94d", size: 30 },
    more:     { label: "Unconfirmed accounts", color: "#7d8690", size: 44 },
  };
  var ORDER = ["email", "username", "phone", "wallet", "domain", "account", "signup", "name", "org", "place"];

  var CATEGORY = {
    underground: "#ff5d7a", forum: "#ffa94d",
    social: "#4fd2ff", messaging: "#4fd2ff", professional: "#4fd2ff",
    dev: "#00d68f", coding: "#00d68f", identity: "#00d68f",
    gaming: "#a78bfa", video: "#a78bfa", music: "#a78bfa", streaming: "#a78bfa",
    art: "#f472b6", photo: "#f472b6", dating: "#f472b6",
    finance: "#ffc94d", crypto: "#ffc94d", shopping: "#ffc94d",
  };

  // Line icons drawn for this page (24x24, stroked).
  var GLYPH = {
    subject: '<circle cx="12" cy="8.5" r="3.6"/><path d="M5 20.5c.8-3.9 3.6-6 7-6s6.2 2.1 7 6"/>',
    email: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
    username: '<circle cx="12" cy="12" r="3.6"/><path d="M15.6 12v1.4a2.6 2.6 0 0 0 5.2 0V12a8.8 8.8 0 1 0-3.5 7"/>',
    phone: '<rect x="7" y="2.8" width="10" height="18.4" rx="2.2"/><path d="M10.5 18h3"/>',
    wallet: '<rect x="3" y="6.5" width="18" height="13" rx="2"/><path d="M3 10h18M15.5 14.5h2"/><path d="M6 6.5l9-3 1.2 3"/>',
    domain: '<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2M12 3.4c2.4 2.4 3.6 5.3 3.6 8.6s-1.2 6.2-3.6 8.6M12 3.4C9.6 5.8 8.4 8.7 8.4 12s1.2 6.2 3.6 8.6"/>',
    account: '<rect x="4" y="4" width="16" height="16" rx="4.5"/><circle cx="12" cy="10.2" r="2.6"/><path d="M7.6 17c.9-2 2.4-3 4.4-3s3.5 1 4.4 3"/>',
    signup: '<rect x="4" y="4" width="16" height="16" rx="4.5"/><path d="M8.5 12.2l2.4 2.4 4.6-4.8"/>',
    name: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M6 15.5c.6-1.3 1.6-2 3-2s2.4.7 3 2M14.5 10h3M14.5 13h3"/>',
    org: '<path d="M5 20.5V5.5l7-2.5v17.5M12 8.5h7v12M3 20.5h18M8 8h1M8 11h1M8 14h1M15 12h1M15 15h1"/>',
    more: '<rect x="7.5" y="7.5" width="12" height="12" rx="3"/><path d="M4.5 15.5V7a2.5 2.5 0 0 1 2.5-2.5h8.5"/><path d="M11 13.5h5M13.5 11v5"/>',
    place: '<path d="M12 21s-6.5-5.8-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 15.2 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.3"/>',
  };

  // Platform logos (Font Awesome brands, already in the bundle) drawn to an
  // image once per platform. Unknown sites get a monogram.
  var BRAND = {
    github: ["github", "#f0f3f6"], gitlab: ["gitlab", "#fc6d26"], bitbucket: ["bitbucket", "#2684ff"],
    twitter: ["x-twitter", "#f0f3f6"], x: ["x-twitter", "#f0f3f6"], instagram: ["instagram", "#e1306c"],
    facebook: ["facebook", "#1877f2"], threads: ["threads", "#f0f3f6"], tiktok: ["tiktok", "#f0f3f6"],
    snapchat: ["snapchat", "#fffc00"], telegram: ["telegram", "#29a9eb"], discord: ["discord", "#5865f2"],
    whatsapp: ["whatsapp", "#25d366"], skype: ["skype", "#00aff0"], slack: ["slack", "#e01e5a"],
    reddit: ["reddit-alien", "#ff4500"], linkedin: ["linkedin", "#0a66c2"], youtube: ["youtube", "#ff0033"],
    twitch: ["twitch", "#9146ff"], steam: ["steam", "#66c0f4"], steamcommunity: ["steam", "#66c0f4"],
    xbox: ["xbox", "#107c10"], playstation: ["playstation", "#0070d1"], itchio: ["itch-io", "#fa5c5c"],
    spotify: ["spotify", "#1ed760"], soundcloud: ["soundcloud", "#ff5500"], lastfm: ["lastfm", "#d51007"],
    bandcamp: ["bandcamp", "#1da0c3"], deezer: ["deezer", "#a238ff"], mixcloud: ["mixcloud", "#5000ff"],
    pinterest: ["pinterest", "#e60023"], flickr: ["flickr", "#ff0084"], vimeo: ["vimeo", "#1ab7ea"],
    unsplash: ["unsplash", "#f0f3f6"], "500px": ["500px", "#f0f3f6"], behance: ["behance", "#1769ff"],
    dribbble: ["dribbble", "#ea4c89"], deviantart: ["deviantart", "#05cc47"], tumblr: ["tumblr", "#36465d"],
    medium: ["medium", "#f0f3f6"], wordpress: ["wordpress", "#3b9ccc"], devcommunity: ["dev", "#f0f3f6"], dev: ["dev", "#f0f3f6"],
    hackernews: ["hacker-news", "#ff6600"], stackoverflow: ["stack-overflow", "#f48024"], stackexchange: ["stack-exchange", "#4a90d9"],
    kaggle: ["kaggle", "#20beff"], hackerrank: ["hackerrank", "#2ec866"], codepen: ["codepen", "#f0f3f6"],
    npm: ["npm", "#cb3837"], docker: ["docker", "#2496ed"], keybase: ["keybase", "#4c8eff"],
    mastodon: ["mastodon", "#6364ff"], bluesky: ["bluesky", "#1185fe"], vk: ["vk", "#0077ff"],
    quora: ["quora", "#b92b27"], patreon: ["patreon", "#f96854"], paypal: ["paypal", "#009cde"],
    amazon: ["amazon", "#ff9900"], ebay: ["ebay", "#e53238"], etsy: ["etsy", "#f1641e"],
    goodreads: ["goodreads", "#b7a68b"], figma: ["figma", "#a259ff"], dropbox: ["dropbox", "#0061ff"],
    trello: ["trello", "#0079bf"], notion: ["notion", "#f0f3f6"], duolingo: ["duolingo", "#58cc02"],
    letterboxd: ["letterboxd", "#00e054"], weibo: ["weibo", "#e6162d"], yelp: ["yelp", "#d32323"],
    airbnb: ["airbnb", "#ff5a5f"], chesscom: ["chess", "#81b64c", 1], lichess: ["chess", "#f0f3f6", 1],
    tryhackme: ["", "#d2464b"], hackthebox: ["", "#9fef00"], hackerone: ["", "#f0f3f6"],
    gravatar: ["", "#1e8cbe"], kick: ["", "#53fc18"], imgur: ["", "#1bb76e"], adobe: ["", "#fa0f00"],
    cracked: ["", "#ff5d7a"], darkforums: ["", "#ff5d7a"], xss: ["", "#ff5d7a"], breachforums: ["", "#ff5d7a"],
  };
  var brandCache = {};
  var faProbe = null;

  function glyphChar(name, solid) {
    if (!faProbe) {
      faProbe = document.createElement("i");
      faProbe.style.cssText = "position:absolute;left:-9999px;top:0;visibility:hidden";
      document.body.appendChild(faProbe);
    }
    faProbe.className = (solid ? "fa-solid fa-" : "fa-brands fa-") + name;
    var v = getComputedStyle(faProbe).getPropertyValue("--fa").trim().replace(/^["']|["']$/g, "");
    if (/^\\[0-9a-f]+$/i.test(v)) v = String.fromCodePoint(parseInt(v.slice(1), 16));
    return v.length && v.length <= 2 ? v : "";
  }

  function monogram(name) {
    var words = String(name || "?").replace(/[^A-Za-z0-9 ]+/g, " ").trim().split(/\s+/);
    var m = words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2);
    return m.length > 1 ? m[0].toUpperCase() + m[1].toLowerCase() : m.toUpperCase();
  }

  // Draws the platform logo (or a monogram) centred at cx, cy; returns the glyph.
  function paintGlyph(g, platform, display, color, cx, cy, scale) {
    var b = BRAND[platform] || ["", color];
    var ch = b[0] ? glyphChar(b[0], b[2]) : "";
    g.fillStyle = b[1] || color;
    g.textAlign = "center";
    g.textBaseline = "middle";
    if (ch) {
      g.font = (b[2] ? "900 " : "400 ") + Math.round(52 * scale) + "px " + (b[2] ? '"Font Awesome 7 Free"' : '"Font Awesome 7 Brands"');
      g.fillText(ch, cx, cy);
    } else {
      g.font = "500 " + Math.round(38 * scale) + "px Roboto, sans-serif";
      g.fillText(monogram(display || platform), cx, cy);
    }
    return ch;
  }

  function brand(platform, display, fallbackColor) {
    var key = platform + "|" + fallbackColor;
    if (brandCache[key]) return brandCache[key];
    var b = BRAND[platform] || ["", fallbackColor];
    var color = b[1] || fallbackColor;
    var c = document.createElement("canvas");
    c.width = c.height = 96;
    var ch = paintGlyph(c.getContext("2d"), platform, display, color, 48, 50, 1);
    return (brandCache[key] = { img: c.toDataURL("image/png"), color: color, logo: !!ch });
  }

  // Profile pictures (GitHub avatar, Gravatar, Instagram, Telegram...) are
  // loaded once with CORS; only pictures that load are used, so a broken
  // link never leaves an empty node and PNG export keeps working.
  var pics = {};
  function picture(url) {
    var st = pics[url];
    if (st) return st.state === "ok" ? url : "";
    st = pics[url] = { state: "loading" };
    var im = new Image();
    im.crossOrigin = "anonymous";
    im.referrerPolicy = "no-referrer";
    im.onload = function () { st.state = im.naturalWidth > 8 ? "ok" : "fail"; if (st.state === "ok") refresh(); };
    im.onerror = function () { st.state = "fail"; };
    im.src = url;
    return "";
  }

  // small round platform badge drawn over a profile picture
  var badgeCache = {};
  function badge(platform, display, color) {
    var key = platform + "|" + color;
    if (badgeCache[key]) return badgeCache[key];
    var b = brand(platform, display, color);
    var c = document.createElement("canvas");
    c.width = c.height = 64;
    var g = c.getContext("2d");
    g.beginPath(); g.arc(32, 32, 29, 0, Math.PI * 2);
    g.fillStyle = "#05090d"; g.fill();
    g.lineWidth = 4; g.strokeStyle = b.color; g.stroke();
    paintGlyph(g, platform, display, b.color, 32, 33, 0.55);
    return (badgeCache[key] = c.toDataURL("image/png"));
  }

  function bestPhoto(n) {
    var list = Object.keys(n.photos || {}).filter(safeUrl);
    for (var i = 0; i < list.length; i++) { var u = picture(list[i]); if (u) return u; }
    return "";
  }

  function icon(type, color) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="' +
      color + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + (GLYPH[type] || GLYPH.account) + "</svg>";
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }

  var PLATFORM_MODULES = {
    github: 1, gitlab: 1, twitter: 1, instagram: 1, reddit: 1, telegram: 1,
    tiktok: 1, keybase: 1, mastodon: 1, linkedin: 1, youtube: 1, twitch: 1,
    spotify: 1, steam: 1, bluesky: 1, hackernews: 1, stackexchange: 1,
    kick: 1, snapchat: 1, venmo: 1,
  };
  var PLATFORM_ALIAS = {
    x: "twitter", "x | twitter": "twitter", "twitter / x": "twitter", "twitter.com": "twitter",
    "x.com": "twitter", "github.com": "github", "gitlab.com": "gitlab", "reddit.com": "reddit",
    "instagram.com": "instagram", "tiktok.com": "tiktok", "youtube.com": "youtube",
  };
  var WEBSITE = { blog: 1, website: 1, homepage: 1, web: 1, site: 1, personalwebsite: 1 };

  // "Istanbul", "İstanbul" and "Istanbul, Turkey" are one place; "TR" is a country.
  var regionNames = null;
  try { regionNames = new Intl.DisplayNames(["en"], { type: "region" }); } catch (e) { /* old browser */ }
  function placeName(v) {
    if (/^[A-Za-z]{2}$/.test(v) && regionNames) {
      try { return regionNames.of(v.toUpperCase()) || v; } catch (e) { return v; }
    }
    return v;
  }
  function fold(v) {
    return String(v).replace(/\u0130/g, "I").replace(/\u0131/g, "i").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  }
  function placeKey(v) {
    var parts = fold(v).split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    // "city, country" collapses to the city; "district, city" stays distinct
    if (parts.length === 2 && COUNTRY_WORDS.test(parts[1])) return parts[0];
    return parts.join(", ");
  }
  var COUNTRY_WORDS = /^(turkey|turkiye|usa|united states|uk|united kingdom|germany|france|netherlands|spain|italy|russia|ukraine|india|china|japan|canada|brazil|iran|azerbaijan|tr|us|de|gb|nl)$/;

  var SKIP_FACTS = { crossref: 1, crosslinked: 1, dorks: 1, search: 1 };
  var NETWORK = /HTTP 0|ConnectionPool|Max retries|ProxyError|timed? ?out|network|not reachable|blocked|rate.?limit/i;

  // ------------------------------------------------------------------
  // Helpers (same normalisation as the backend: crossref.py / pivots.py)
  // ------------------------------------------------------------------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : ""; }
  function pick(result, key) {
    for (var i = 0; i < (result || []).length; i++) {
      var it = result[i];
      if (it && typeof it === "object" && key in it) return it[key];
    }
    return undefined;
  }
  function normPlatform(name) {
    var v = String(name || "").trim().toLowerCase().replace(/^linkedin - .*/, "linkedin");
    v = PLATFORM_ALIAS[v] || v;
    v = v.replace(/^www\./, "").replace(/\.(com|net|org|io|me|tv|gg|co)$/, "");
    return v.replace(/[^a-z0-9]+/g, "");
  }
  function normHandle(h) { return String(h || "").trim().replace(/^@/, "").toLowerCase(); }
  function canonical(type, value) {
    var v = String(value || "").trim();
    if (type === "email" || type === "domain") return v.toLowerCase();
    if (type === "phone") {
      var d = v.replace(/[\s().\-]/g, "");
      if (d.charAt(0) !== "+" && /^0\d{10}$/.test(d)) d = "+90" + d.slice(1); // backend default region
      return d;
    }
    if (type === "wallet") return /^0x/i.test(v) ? v.toLowerCase() : v;
    return v.replace(/^@/, "").toLowerCase();
  }
  function selectorType(module, value) {
    if (module === "domaininfo") return "domain";
    var k = V.kind(value);
    return k === "empty" ? "" : k;
  }
  // "" = data, "empty" = source answered without data, "fail" = could not check
  function outcome(result) {
    var raw = pick(result, "raw");
    var head = Array.isArray(raw) && raw[0] && raw[0].status ? String(raw[0].status).toLowerCase() : "";
    if (head === "fail" || head === "error") return "fail";
    if (head === "warning") return NETWORK.test(raw[0].reason || "") ? "fail" : "empty";
    return "";
  }
  function failed(result) { return outcome(result) !== ""; }
  function grade(n, hint) {
    if (hint) return hint;
    return n >= 3 ? "confirmed" : n === 2 ? "likely" : "candidate";
  }

  // ------------------------------------------------------------------
  // Model: results -> nodes / edges
  // ------------------------------------------------------------------
  function buildModel(state) {
    var nodes = {}, edges = {};
    var subjectNames = {};

    function node(id, type, label, extra) {
      var n = nodes[id];
      if (!n) {
        n = nodes[id] = {
          id: id, type: type, label: label, value: label, sources: {}, urls: {},
          photos: {}, category: "", confidence: "", notes: [], meta: {},
        };
      }
      if (extra) for (var k in extra) if (extra[k] !== undefined && extra[k] !== "") n[k] = extra[k];
      return n;
    }
    function source(n, module) { if (module) n.sources[module] = 1; }
    function edge(a, b, kind, module, extra) {
      if (!a || !b || a === b) return null;
      var id = "e:" + a + "|" + b, rid = "e:" + b + "|" + a;
      var e = edges[id] || edges[rid];
      if (!e) e = edges[id] = { id: id, source: a, target: b, kind: kind, modules: {}, checks: {}, notes: {} };
      if (module) e.modules[module] = 1;
      // a pivot is stronger information than a plain link: keep it visible
      if (kind === "pivot" && e.kind !== "pivot") { e.kind = "pivot"; e.followed = true; }
      if (extra) for (var k in extra) e.notes[k] = extra[k];
      return e;
    }
    function selector(type, value, module) {
      var c = canonical(type, value);
      if (!c) return null;
      var n = node("sel:" + type + ":" + c, type, String(value).trim().replace(/^@/, ""), { canon: c });
      source(n, module);
      return n;
    }
    function account(platform, handle, display, module) {
      var p = normPlatform(platform), h = normHandle(handle);
      if (!p || !h) return null;
      var n = node("acc:" + p + ":" + h, "account", display || platform, { platform: p, handle: h });
      if (display && (!n.display || n.display.length < display.length)) n.display = display;
      source(n, module);
      return n;
    }

    var results = state.results || {};
    var keys = Object.keys(results);
    var crossref = null;
    var checked = {}; // selector id -> {module: "ok"|"empty"|"fail"}

    keys.forEach(function (key) {
      var r = results[key];
      var module = pick(r, "module"), param = String(pick(r, "param") || "");
      if (!module || !param) return;
      if (module === "crossref") { if (!failed(r)) crossref = r; return; }
      var type = selectorType(module, param);
      if (!type) return;
      var sel = selector(type, param, null);
      if (!sel) return;
      var out = outcome(r);
      checked[sel.id] = checked[sel.id] || {};
      checked[sel.id][module] = out || "ok";
      if (out) return;
      source(sel, module);

      // the node the facts of this result belong to
      var anchor = sel;
      if (PLATFORM_MODULES[module] && type === "username") {
        var own = account(module, param, V.label(module), module);
        if (own) {
          anchor = own;
          own.meta.profileModule = module;
          edge(sel.id, own.id, "found", module);
        }
      }

      var profile = pick(r, "profile") || [];
      profile.forEach(function (entry) {
        if (!entry || typeof entry !== "object") return;
        (Array.isArray(entry.social) ? entry.social : []).forEach(function (s) {
          if (!s || typeof s !== "object" || module === "crosslinked") return;
          var handle = s.username || param;
          var platform = s.name || s.source;
          var plat = normPlatform(platform);
          if (WEBSITE[plat] && safeUrl(s.url)) {
            // a personal site is a domain lead, not an account
            var host = String(s.url).replace(/^https?:\/\//i, "").split(/[/?#]/)[0].replace(/^www\./i, "");
            var site = selector("domain", host, module);
            if (site) { site.urls[s.url] = 1; edge(anchor.id, site.id, "fact", module); }
            return;
          }
          var acc = account(platform, handle, s.name, module);
          if (!acc) return;
          if (module === "emailreg" || (type === "email" && normHandle(handle).indexOf("@") > 0)) {
            acc.type = acc.type === "account" && acc.meta.profileModule ? "account" : "signup";
          }
          var cat = String(s.category || "").split(",")[0].trim().toLowerCase();
          if (cat && !acc.category) acc.category = cat;
          if (safeUrl(s.url)) acc.urls[s.url] = 1;
          if (acc === anchor) return;
          // an account linked from another account's profile (GitHub -> Twitter)
          if (s.linked_from) {
            String(s.linked_from).split(/,\s*/).forEach(function (site) {
              var from = account(site, param, site, module);
              if (from && from !== acc) {
                edge(sel.id, from.id, "found", module);
                edge(from.id, acc.id, "link", module);
              }
            });
            return;
          }
          if (anchor !== sel && normHandle(handle) !== anchor.handle) edge(anchor.id, acc.id, "link", module);
          else edge(sel.id, acc.id, "found", module);
        });

        if (SKIP_FACTS[module]) return;
        var fact = function (type2, value, extra) {
          var v = String(value || "").trim();
          if (!v || v.length > 140) return null;
          if (type2 === "place") v = placeName(v);
          var id = type2 + ":" + (type2 === "place" ? placeKey(v) : v.toLowerCase().replace(/\s+/g, " "));
          var n = node(id, type2, v, extra);
          source(n, module);
          edge(anchor.id, n.id, "fact", module);
          return n;
        };
        if (typeof entry.name === "string" && entry.name.trim()) {
          var nm = fact("name", entry.name);
          if (nm) subjectNames[nm.id] = (subjectNames[nm.id] || 0) + 1;
        }
        if (typeof entry.organization === "string") fact("org", entry.organization);
        else if (Array.isArray(entry.organization)) entry.organization.forEach(function (o) { if (o && o.name) fact("org", o.name); });
        if (typeof entry.location === "string") fact("place", entry.location);
        if (entry.geo && typeof entry.geo === "object" && entry.geo.Latitude !== undefined && entry.geo.Latitude !== "") {
          var g = entry.geo, gname = g.Name || g.Caption || (g.Latitude + ", " + g.Longitude);
          var pl = fact("place", gname, { lat: +g.Latitude, lng: +g.Longitude });
          if (pl && g.Caption && g.Caption !== gname) pl.notes.push(g.Caption);
        }
        ["email", "phone"].forEach(function (t) {
          var val = entry[t];
          if (typeof val !== "string" || !val.trim()) return;
          var tt = selectorType(module, val);
          if (tt !== "email" && tt !== "phone") return;
          var s2 = selector(tt, val, module);
          if (s2 && s2 !== sel) edge(anchor.id, s2.id, "fact", module);
        });
        (Array.isArray(entry.wallet) ? entry.wallet : []).forEach(function (w) {
          if (!w || !w.address) return;
          var s3 = selector("wallet", w.address, module);
          if (s3 && s3 !== sel) edge(anchor.id, s3.id, "fact", module);
        });
        (Array.isArray(entry.photos) ? entry.photos : []).forEach(function (ph) {
          if (ph && safeUrl(ph.picture)) anchor.photos[ph.picture] = module;
        });
        if (typeof entry.url === "string" && safeUrl(entry.url)) anchor.urls[entry.url] = 1;
        if (typeof entry.bio === "string" && entry.bio.trim() && anchor.notes.length < 3) anchor.notes.push(entry.bio.trim());
      });

      // pivots: selectors found here that the orchestrator followed
      var tasks = pick(r, "tasks") || [];
      tasks.forEach(function (t) {
        if (!t || !t.module || t.param === undefined) return;
        var tp = String(t.param);
        if (t.module === "crossref") return;
        var ttype = selectorType(t.module, tp);
        if (!ttype || canonical(ttype, tp) === sel.canon) return;
        var target = selector(ttype, tp, null);
        if (!target) return;
        target.meta.depth = Math.min(target.meta.depth || 9, t.depth || 1);
        var e = edge(anchor.id, target.id, "pivot", module, { via: module });
        if (e) { e.checks[t.module] = 1; e.notes.depth = t.depth || e.notes.depth || ""; e.notes.from = V.label(module); }
      });
    });

    // ---- cross analysis: grades, avatar matches, consensus name ------------
    var xr = crossref && pick(crossref, "raw");
    if (xr && typeof xr === "object") {
      (xr.accounts || []).forEach(function (a) {
        var n = nodes["acc:" + normPlatform(a.platform) + ":" + normHandle(a.handle)];
        if (!n) return;
        n.confidence = a.confidence || n.confidence;
        if (a.underground) n.category = "underground";
        if (a.avatar_match) n.meta.avatar = true;
      });
      (xr.avatar_matches || []).forEach(function (m) {
        var acc = (m.accounts || []).map(function (pair) { return "acc:" + normPlatform(pair[0]) + ":" + normHandle(pair[1]); })
          .filter(function (id) { return nodes[id]; });
        for (var i = 1; i < acc.length; i++) edge(acc[0], acc[i], "avatar", "crossref", { distance: m.distance });
      });
      var names = (xr.identity && xr.identity.name) || [];
      if (names[0] && names[0].value) subjectNames["name:" + String(names[0].value).toLowerCase().replace(/\s+/g, " ")] = 1e6;
    }

    // ---- account grades for accounts crossref did not see ---------------
    Object.keys(nodes).forEach(function (id) {
      var n = nodes[id];
      if ((n.type === "account" || n.type === "signup") && !n.confidence) {
        var srcs = Object.keys(n.sources);
        var hint = n.meta.profileModule && n.sources[n.meta.profileModule] ? "confirmed" : ""; // the platform's own API answered
        n.confidence = grade(srcs.length, hint);
      }
    });

    // ---- subject ----------------------------------------------------------
    var roots = (state.roots || []).map(function (r) {
      var t = selectorType("", r);
      return t ? "sel:" + t + ":" + canonical(t, r) : "";
    }).filter(function (id) { return nodes[id]; });
    if (roots.length) {
      var bestName = Object.keys(subjectNames).sort(function (a, b) { return subjectNames[b] - subjectNames[a]; })[0];
      var subj = node("subject", "subject", bestName && nodes[bestName] ? nodes[bestName].label : "Subject");
      subj.meta.nameNode = bestName || "";
      var picCount = {};
      Object.keys(nodes).forEach(function (id) {
        Object.keys(nodes[id].photos).forEach(function (u) { picCount[u] = (picCount[u] || 0) + 1; });
      });
      Object.keys(picCount).sort(function (a, b) { return picCount[b] - picCount[a]; }).forEach(function (u) { subj.photos[u] = "consensus"; });
      roots.forEach(function (id) { nodes[id].meta.root = true; edge("subject", id, "root", null); });
      if (bestName && nodes[bestName]) {
        // the consensus name becomes the subject itself
        Object.keys(edges).forEach(function (eid) {
          var e = edges[eid];
          if (e.target === bestName) { delete edges[eid]; edge(e.source, "subject", "fact", Object.keys(e.modules)[0]); }
          else if (e.source === bestName) { delete edges[eid]; edge("subject", e.target, e.kind, Object.keys(e.modules)[0]); }
        });
        subj.sources = nodes[bestName].sources;
        delete nodes[bestName];
      }
    }

    // ---- selectors: which modules looked at them -------------------------
    Object.keys(checked).forEach(function (id) { if (nodes[id]) nodes[id].meta.checked = checked[id]; });

    return { nodes: nodes, edges: edges, results: keys.length };
  }

  // ------------------------------------------------------------------
  // View
  // ------------------------------------------------------------------
  var el, cy, model = { nodes: {}, edges: {} }, panelId = "", visible = false;
  var filters = { types: {}, minGrade: "candidate", query: "" };
  ORDER.forEach(function (t) { filters.types[t] = true; });
  var GRADES = ["confirmed", "likely", "candidate"];

  // Account labels repeat the handle only when it differs from the
  // username it hangs off (otherwise 30 nodes would all read "tailmon").
  function labelOf(n, handles) {
    if (n.type === "account" || n.type === "signup") {
      var p = n.display || n.platform;
      return n.type === "signup" || handles[n.handle] ? p : p + " \u00b7 " + n.handle;
    }
    var l = n.label;
    return l.length > 34 ? l.slice(0, 32) + "…" : l;
  }

  // A username checked against hundreds of sites yields hundreds of
  // single-source hits. Past COLLAPSE they fold into one node per username
  // (expandable), so the accounts that matter stay readable.
  var COLLAPSE = 30, expanded = {}, collapsed = {};

  function foldable(m) {
    var links = {};
    Object.keys(m.edges).forEach(function (k) {
      var e = m.edges[k];
      (links[e.source] = links[e.source] || []).push(e.target);
      (links[e.target] = links[e.target] || []).push(e.source);
    });
    var groups = {};
    Object.keys(m.nodes).forEach(function (id) {
      var n = m.nodes[id];
      if (n.type !== "account" || n.confidence !== "candidate" || n.category === "underground") return;
      var nb = links[id] || [];
      if (nb.length !== 1 || !m.nodes[nb[0]] || m.nodes[nb[0]].type !== "username") return;
      (groups[nb[0]] = groups[nb[0]] || []).push(id);
    });
    var out = {};
    Object.keys(groups).forEach(function (sel) {
      if (groups[sel].length > COLLAPSE && !expanded[sel]) out[sel] = groups[sel];
    });
    return out;
  }

  function elementsFor(m) {
    var out = [], handles = {}, hide = {};
    collapsed = foldable(m);
    Object.keys(collapsed).forEach(function (sel) { collapsed[sel].forEach(function (id) { hide[id] = 1; }); });
    Object.keys(m.nodes).forEach(function (id) { if (m.nodes[id].type === "username") handles[m.nodes[id].canon] = 1; });
    Object.keys(m.nodes).forEach(function (id) {
      if (hide[id]) return;
      var n = m.nodes[id], t = TYPES[n.type] || TYPES.account;
      var isAcc = n.type === "account" || n.type === "signup";
      var cat = CATEGORY[n.category] || "#8a939d";
      var b = isAcc ? brand(n.platform, n.display, n.category === "underground" ? "#ff5d7a" : cat) : null;
      var ring = isAcc ? (n.category === "underground" ? "#ff5d7a" : b.color) : t.color;
      out.push({
        group: "nodes",
        data: {
          id: id, type: n.type, label: labelOf(n, handles), size: t.size,
          ring: ring, fill: ring, glyph: b ? b.img : icon(n.type, t.color),
          photo: bestPhoto(n), badge: "",
          grade: n.confidence || "", nsrc: Object.keys(n.sources).length,
          root: n.meta.root ? 1 : 0, under: n.category === "underground" ? 1 : 0,
        },
        classes: [n.type, n.confidence ? "g-" + n.confidence : "", n.meta.root ? "root" : "", n.category === "underground" ? "under" : "", bestPhoto(n) ? "pic" : ""].join(" "),
      });
    });
    Object.keys(m.edges).forEach(function (id) {
      var e = m.edges[id];
      if (!m.nodes[e.source] || !m.nodes[e.target] || hide[e.source] || hide[e.target]) return;
      out.push({
        group: "edges",
        data: { id: id, source: e.source, target: e.target, kind: e.kind, label: edgeLabel(e) },
        classes: e.kind,
      });
    });
    Object.keys(collapsed).forEach(function (sel) {
      var n = collapsed[sel].length;
      out.push({
        group: "nodes",
        data: { id: "more:" + sel, type: "more", label: "+" + n, size: TYPES.more.size, ring: "#3d5866", glyph: icon("more", "#9aa5b1"), grade: "candidate" },
        classes: "more",
      });
      out.push({ group: "edges", data: { id: "e:more:" + sel, source: sel, target: "more:" + sel, kind: "found", label: n + " unconfirmed" }, classes: "found" });
    });
    return out;
  }

  function edgeLabel(e) {
    var mods = Object.keys(e.modules).map(V.label);
    if (e.kind === "avatar") return "same profile picture";
    if (e.kind === "root") return "searched";
    if (e.kind === "pivot") return "followed → " + Object.keys(e.checks).map(V.label).join(", ");
    if (e.kind === "link") return "linked from profile";
    return mods.join(", ");
  }

  var STYLE = [
    { selector: "core", style: { "active-bg-opacity": 0, "selection-box-color": "#4fd2ff", "selection-box-opacity": 0.12 } },
    {
      selector: "node",
      style: {
        width: "data(size)", height: "data(size)", shape: "ellipse",
        "background-color": "data(fill)", "background-opacity": 0.16, "background-image": "data(glyph)",
        "background-width": "54%", "background-height": "54%", "background-clip": "none", "background-image-containment": "over",
        "border-width": 1.5, "border-color": "data(ring)", "border-opacity": 1,
        label: "data(label)", color: "#cfe9f2", "font-family": "Roboto, Segoe UI, sans-serif",
        "font-size": 11, "font-weight": 400, "text-valign": "bottom", "text-halign": "center",
        "text-margin-y": 6, "text-wrap": "wrap", "text-max-width": 140, "line-height": 1.25,
        "text-outline-width": 3, "text-outline-color": "#05090d", "text-outline-opacity": 1,
        "min-zoomed-font-size": 7, "overlay-opacity": 0, "transition-property": "opacity, border-width", "transition-duration": 120,
      },
    },
    { selector: "node.subject", style: { "background-color": "#e4e7eb", "background-opacity": 0.1, "border-width": 2.5, "border-color": "#e4e7eb", "font-size": 13, "font-weight": 600, color: "#e4e7eb", "underlay-color": "#e4e7eb", "underlay-opacity": 0.06, "underlay-padding": 10, "underlay-shape": "ellipse" } },
    { selector: "node.email, node.username, node.phone, node.wallet, node.domain", style: { "font-size": 12, "font-weight": 500, color: "#e4e7eb", "border-width": 2 } },
    { selector: "node.root", style: { "border-width": 3, "underlay-color": "#4fd2ff", "underlay-opacity": 0.08, "underlay-padding": 7, "underlay-shape": "ellipse" } },
    // platform names appear when zoomed in, on hover or when selected
    { selector: "node.account, node.signup", style: { shape: "ellipse", "font-size": 10, color: "#aeb5be", "min-zoomed-font-size": 18, "background-width": "60%", "background-height": "60%" } },
    { selector: "node.signup", style: { color: "#8b939d", "border-width": 1, "background-opacity": 0.1 } },
    { selector: "node.name, node.org, node.place", style: { "min-zoomed-font-size": 15 } },
    { selector: "node.show-label", style: { "min-zoomed-font-size": 0, "z-index": 20 } },
    { selector: "node.g-confirmed", style: { "border-width": 2.5, "border-style": "solid" } },
    { selector: "node.g-likely", style: { "border-width": 1.5, "border-style": "solid" } },
    { selector: "node.g-candidate", style: { "border-width": 1, "border-opacity": 0.55, "background-opacity": 0.1 } },
    { selector: "node.under", style: { "underlay-color": "#ff5d7a", "underlay-opacity": 0.16, "underlay-padding": 5, "underlay-shape": "ellipse" } },
    { selector: "node.more", style: { shape: "ellipse", "background-color": "#8a939d", "background-opacity": 0.08, "border-style": "dashed", "border-width": 1.5, "border-color": "#3d5866", "font-size": 11, color: "#aeb5be" } },
    { selector: "node.name, node.org, node.place", style: { shape: "ellipse", "font-size": 11, color: "#c9ced5" } },
    {
      selector: "edge",
      style: {
        width: 1, "line-color": "#3c6478", "curve-style": "bezier", "target-arrow-shape": "none",
        "overlay-opacity": 0, label: "", "font-family": "Roboto, Segoe UI, sans-serif", "font-size": 9.5,
        color: "#959ca6", "text-background-color": "#05090d", "text-background-opacity": 1,
        "text-background-padding": 2, "text-rotation": "autorotate", "transition-property": "opacity, line-color", "transition-duration": 120,
      },
    },
    { selector: "edge.root", style: { width: 1.6, "line-color": "#3d5866" } },
    { selector: "edge.found", style: { "line-color": "#355a6c" } },
    { selector: "edge.fact", style: { "line-color": "#3f6a7e", "line-style": "solid" } },
    { selector: "edge.link", style: { "line-color": "#3a6a86", "target-arrow-shape": "triangle", "target-arrow-color": "#3a6a86", "arrow-scale": 0.7 } },
    { selector: "edge.pivot", style: { width: 1.5, "line-color": "#4fd2ff", "line-style": "dashed", "line-dash-pattern": [6, 4], "target-arrow-shape": "triangle", "target-arrow-color": "#4fd2ff", "arrow-scale": 0.8, "z-index": 5 } },
    { selector: "edge.avatar", style: { width: 1.6, "line-color": "#ffa94d", "line-style": "dotted", "z-index": 6 } },
    { selector: "edge.show-label, edge:selected", style: { label: "data(label)" } },
    { selector: ".faded", style: { opacity: 0.12, "underlay-opacity": 0 } },
    { selector: "edge.faded", style: { opacity: 0.06 } },
    { selector: "node.hit", style: { "underlay-color": "#e4e7eb", "underlay-opacity": 0.16, "underlay-padding": 8 } },
    { selector: "node:selected", style: { "min-zoomed-font-size": 0,  "border-color": "#e4e7eb", "border-width": 3, "underlay-color": "#4fd2ff", "underlay-opacity": 0.22, "underlay-padding": 8 } },
    { selector: ".hidden", style: { display: "none" } },
  ];

  function layoutOptions(randomize) {
    return {
      name: window.cytoscapeFcose ? "fcose" : "cose",
      quality: "proof", randomize: !!randomize, animate: !randomize, animationDuration: 450,
      fit: true, padding: 48, nodeDimensionsIncludeLabels: false, packComponents: true,
      nodeRepulsion: function (n) { return n.hasClass("signup") ? 2200 : n.hasClass("account") ? 3800 : 8000; },
      idealEdgeLength: function (e) {
        var k = e.data("kind");
        return k === "root" ? 95 : k === "pivot" ? 120 : k === "fact" ? 55 : k === "avatar" ? 90 : 62;
      },
      edgeElasticity: function (e) { return e.data("kind") === "avatar" ? 0.15 : 0.45; },
      gravity: 0.3, gravityRangeCompound: 1.5, numIter: 2500, tile: true,
      tilingPaddingVertical: 14, tilingPaddingHorizontal: 14,
    };
  }

  // ---- DOM ----------------------------------------------------------------
  function mount() {
    if (el) return;
    el = document.createElement("section");
    el.id = "ve-graph";
    el.setAttribute("aria-label", "Relationship graph");
    el.innerHTML =
      '<header class="vg-bar">' +
        '<div class="vg-title"><h1>Relationship graph</h1><p class="vg-counts"></p></div>' +
        '<div class="vg-tools">' +
          '<label class="vg-find"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>' +
          '<input type="search" placeholder="Find in graph" aria-label="Find in graph"></label>' +
          '<select class="vg-grade" aria-label="Account confidence">' +
            '<option value="candidate">All accounts</option><option value="likely">Likely and confirmed</option><option value="confirmed">Confirmed only</option>' +
          "</select>" +
          '<button type="button" class="vg-ib" data-act="fit" title="Fit to screen" aria-label="Fit to screen"><i class="fa-solid fa-expand"></i></button>' +
          '<button type="button" class="vg-ib" data-act="layout" title="Lay out again" aria-label="Lay out again"><i class="fa-solid fa-shuffle"></i></button>' +
          '<button type="button" class="vg-ib" data-act="png" title="Download image (PNG)" aria-label="Download image"><i class="fa-solid fa-image"></i></button>' +
          '<button type="button" class="vg-ib" data-act="pdf" title="PDF report" aria-label="PDF report"><i class="fa-solid fa-file-pdf"></i></button>' +
          '<button type="button" class="vg-ib" data-act="json" title="Download data (JSON)" aria-label="Download data"><i class="fa-solid fa-file-arrow-down"></i></button>' +
        "</div>" +
        '<div class="vg-types" role="group" aria-label="Show node types"></div>' +
      "</header>" +
      '<div class="vg-body"><div class="vg-canvas"></div>' +
        '<div class="vg-empty" hidden><img src="assets/images/logo.png" alt="" width="56" height="56">' +
          "<h2>No investigation yet</h2><p>Search an e-mail, username, phone number or wallet. The graph fills in as each source answers, and follows the leads it finds.</p>" +
          '<button type="button" data-act="search">Start a search</button></div>' +
        '<aside class="vg-panel" hidden></aside>' +
        '<div class="vg-legend"></div>' +
        '<div class="vg-tip" hidden></div>' +
      "</div>";
    document.body.appendChild(el);

    el.querySelector(".vg-find input").addEventListener("input", function (ev) { filters.query = ev.target.value; applyFind(true); });
    el.querySelector(".vg-grade").addEventListener("change", function (ev) { filters.minGrade = ev.target.value; applyFilters(); });
    el.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-act]");
      if (!b) return;
      var act = b.getAttribute("data-act");
      if (act === "fit" && cy) cy.animate({ fit: { eles: cy.elements(":visible"), padding: 48 } }, { duration: 300 });
      else if (act === "layout" && cy) runLayout(true);
      else if (act === "png") exportPng();
      else if (act === "json") exportJson();
      else if (act === "pdf") V.report("pdf");
      else if (act === "search") V.search("");
      else if (act === "type") { var t = b.getAttribute("data-type"); filters.types[t] = !filters.types[t]; applyFilters(); renderChips(); }
      else if (act === "close") selectNode("");
      else if (act === "expand") { expanded[b.getAttribute("data-id")] = true; selectNode(""); safeSync(); }
      else if (act === "goto") selectNode(b.getAttribute("data-id"), true);
      else if (act === "copy") copy(b.getAttribute("data-value"), b);
    });
    window.addEventListener("resize", position);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(position);
      var sb = document.querySelector(".layout-sidebar");
      if (sb) ro.observe(sb);
    }
    renderLegend();
  }

  // Sit exactly over the content area, between sidebar, header and footer.
  function position() {
    if (!el || !visible) return;
    var sb = document.querySelector(".layout-sidebar");
    var left = 0;
    if (sb) {
      var r = sb.getBoundingClientRect();
      if (r.width > 0 && r.right > 0 && r.right < window.innerWidth * 0.6) left = r.right;
    }
    var header = document.querySelector(".layout-header, header.header, vey-header");
    var top = header ? Math.max(0, header.getBoundingClientRect().bottom) : 56;
    var footer = document.querySelector(".layout-footer, footer.footer, vey-footer");
    var fr = footer && footer.getBoundingClientRect();
    var bottom = fr && fr.height && fr.top < window.innerHeight ? Math.max(0, window.innerHeight - fr.top) : 0;
    el.style.left = left + "px";
    el.style.top = (top || 56) + "px";
    el.style.bottom = bottom + "px";
    if (cy) cy.resize();
  }

  function initCy() {
    if (cy) return;
    cy = cytoscape({
      container: el.querySelector(".vg-canvas"),
      style: STYLE, elements: [], minZoom: 0.12, maxZoom: 3.5,
      boxSelectionEnabled: false, textureOnViewport: false, pixelRatio: "auto",
    });
    cy.on("tap", "node", function (ev) { selectNode(ev.target.id()); });
    cy.on("tap", function (ev) { if (ev.target === cy) selectNode(""); });
    cy.on("mouseover", "edge", function (ev) { ev.target.addClass("show-label"); tip(ev, edgeTip(ev.target)); });
    cy.on("mouseout", "edge", function (ev) { ev.target.removeClass("show-label"); tip(null); });
    cy.on("mouseover", "node", function (ev) { ev.target.addClass("show-label"); tip(ev, nodeTip(ev.target)); el.querySelector(".vg-canvas").style.cursor = "pointer"; });
    cy.on("mouseout", "node", function (ev) { ev.target.removeClass("show-label"); tip(null); el.querySelector(".vg-canvas").style.cursor = ""; });
    cy.on("pan zoom", function () { tip(null); });
  }

  // ---- data -> graph ------------------------------------------------------
  var pending = 0, layoutTimer = 0, firstLayout = true;

  function refresh() {
    if (!visible) return;
    clearTimeout(pending);
    pending = setTimeout(safeSync, 250);
  }

  function safeSync() {
    try { sync(); } catch (err) { if (window.console) console.error("graph update failed", err); }
  }

  function sync() {
    model = buildModel(V.state());
    if (!model.results) expanded = {};
    var els = elementsFor(model);
    var empty = !els.length;
    el.querySelector(".vg-empty").hidden = !empty;
    el.querySelector(".vg-canvas").style.visibility = empty ? "hidden" : "";
    var want = {};
    var added = 0;
    cy.batch(function () {
      els.forEach(function (d) {
        want[d.data.id] = 1;
        var cur = cy.getElementById(d.data.id);
        if (cur.length) { cur.data(d.data); cur.classes(d.classes); return; }
        if (d.group === "nodes") {
          // start new nodes next to something they connect to
          var anchor = null;
          for (var k in model.edges) {
            var e = model.edges[k];
            var other = e.source === d.data.id ? e.target : e.target === d.data.id ? e.source : "";
            if (other && cy.getElementById(other).length) { anchor = cy.getElementById(other).position(); break; }
          }
          if (anchor) d.position = { x: anchor.x + (Math.random() - 0.5) * 80, y: anchor.y + (Math.random() - 0.5) * 80 };
        }
        cy.add(d);
        added++;
      });
      cy.elements().forEach(function (x) { if (!want[x.id()]) x.remove(); });
    });
    cy.nodes(".pic").forEach(function (x) {
      var m = model.nodes[x.id()];
      var imgs = [x.data("photo")], w = ["100%"], h = ["100%"], fit = ["cover"], px = ["50%"], py = ["50%"], op = [1];
      if (m && (m.type === "account" || m.type === "signup")) {
        imgs.push(badge(m.platform, m.display, x.data("ring")));
        w.push("44%"); h.push("44%"); fit.push("none"); px.push("118%"); py.push("118%"); op.push(1);
      }
      x.style({
        "background-image": imgs, "background-width": w, "background-height": h, "background-fit": fit,
        "background-position-x": px, "background-position-y": py, "background-image-opacity": op,
        "background-clip": imgs.map(function (_, i) { return i ? "none" : "node"; }),
        "background-image-containment": imgs.map(function (_, i) { return i ? "over" : "inside"; }),
        "bounds-expansion": imgs.length > 1 ? 8 : 0, "background-opacity": 1,
        "background-color": "#05090d",
      });
    });
    cy.nodes().filter(function (x) { return !x.hasClass("pic"); }).removeStyle("background-image background-width background-height background-fit background-position-x background-position-y background-image-opacity background-clip background-image-containment bounds-expansion background-opacity background-color");
    renderCounts();
    renderChips();
    applyFilters(true);
    if (added) {
      clearTimeout(layoutTimer);
      layoutTimer = setTimeout(function () { runLayout(firstLayout); firstLayout = false; }, firstLayout ? 0 : 600);
    }
    if (panelId) renderPanel(panelId);
  }

  var running = null;
  function runLayout(randomize) {
    if (!cy || !cy.nodes(":visible").length) return;
    if (running) try { running.stop(); } catch (e) { /* finished */ }
    var eles = cy.elements().filter(function (x) { return !x.hasClass("hidden") && !(x.isEdge() && (x.source().hasClass("hidden") || x.target().hasClass("hidden"))); });
    running = eles.layout(layoutOptions(randomize || cy.nodes().length < 3));
    running.one("layoutstop", function () { cy.animate({ fit: { eles: eles, padding: 48 } }, { duration: 250 }); });
    running.run();
  }

  function visibleByFilter(n) {
    var t = n.data("type");
    if (t === "more") return filters.types.account !== false && filters.minGrade === "candidate";
    if (t !== "subject" && filters.types[t] === false) return false;
    if (t === "account" && n.data("grade")) {
      if (GRADES.indexOf(n.data("grade")) > GRADES.indexOf(filters.minGrade)) return false;
    }
    return true;
  }

  function applyFilters(quiet) {
    if (!cy) return;
    cy.batch(function () {
      cy.nodes().forEach(function (n) { n.toggleClass("hidden", !visibleByFilter(n)); });
      // drop facts left without a visible neighbour
      cy.nodes(".name, .org, .place").forEach(function (n) {
        if (n.hasClass("hidden")) return;
        var any = n.neighborhood("node").some(function (x) { return !x.hasClass("hidden"); });
        if (!any) n.addClass("hidden");
      });
    });
    applyFind(false);
    // keep positions (the analyst's mental map), just frame what is left
    if (!quiet) {
      var shown = cy.nodes().filter(function (n) { return !n.hasClass("hidden"); });
      if (shown.length) cy.animate({ fit: { eles: shown, padding: 56 } }, { duration: 300 });
    }
  }

  function applyFind(center) {
    if (!cy) return;
    var q = filters.query.trim().toLowerCase();
    cy.nodes().removeClass("hit");
    if (!q) return;
    var hits = cy.nodes(":visible").filter(function (n) {
      var m = model.nodes[n.id()];
      return m && (String(m.label).toLowerCase().indexOf(q) >= 0 || String(m.handle || "").indexOf(q) >= 0 || String(m.platform || "").indexOf(q) >= 0);
    });
    hits.addClass("hit");
    if (center && hits.length) cy.animate({ fit: { eles: hits, padding: 120 } }, { duration: 300 });
  }

  // ---- panel ----------------------------------------------------------------
  function selectNode(id, center) {
    panelId = id;
    var panel = el.querySelector(".vg-panel");
    cy.elements().removeClass("faded");
    cy.nodes().unselect();
    if (!id || (!model.nodes[id] && !cy.getElementById(id).length)) { panel.hidden = true; panelId = ""; return; }
    var n = cy.getElementById(id);
    if (n.length) {
      n.select();
      var hood = n.closedNeighborhood();
      cy.elements().not(hood).addClass("faded");
      if (center) cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 300 });
    }
    renderPanel(id);
    panel.hidden = false;
  }

  function renderMore(id) {
    var sel = id.slice(5), ids = collapsed[sel] || [];
    var byCat = {};
    ids.forEach(function (x) { var c = model.nodes[x].category || "other"; byCat[c] = (byCat[c] || 0) + 1; });
    var h = '<header><span class="vg-glyph" style="--c:#3d5866"><img src="' + icon("more", "#9aa5b1") + '" alt=""></span>' +
      '<div><p class="vg-kind">Unconfirmed accounts</p><h2>' + ids.length + " accounts</h2>" +
      '<p class="vg-sub">for ' + esc(model.nodes[sel] ? model.nodes[sel].label : sel) + ", each reported by one source only</p></div>" +
      '<button type="button" class="vg-x" data-act="close" aria-label="Close">\u00d7</button></header>';
    h += '<p class="vg-note">A matching username on a site is not proof it is the same person. These were folded to keep the graph readable; anything a second source or the cross analysis supports is shown on the graph.</p>';
    h += "<h3>By category</h3><p class=\"vg-tags\">" + Object.keys(byCat).sort(function (a, b) { return byCat[b] - byCat[a]; }).map(function (c) {
      return "<span>" + esc(V.catLabel(c)) + " " + byCat[c] + "</span>";
    }).join("") + "</p>";
    h += '<h3>Sites</h3><ul class="vg-links">' + ids.slice(0, 80).map(function (x) {
      var n = model.nodes[x], u = Object.keys(n.urls).filter(safeUrl)[0];
      var name = esc(n.display || n.platform);
      return "<li>" + (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + name + "</a>" : name) + "</li>";
    }).join("") + (ids.length > 80 ? '<li class="vg-more">' + (ids.length - 80) + " more in the JSON export</li>" : "") + "</ul>";
    h += '<footer class="vg-actions"><button type="button" class="vg-primary" data-act="expand" data-id="' + esc(sel) + '">Show all ' + ids.length + " on the graph</button></footer>";
    el.querySelector(".vg-panel").innerHTML = h;
  }

  function renderPanel(id) {
    if (id.indexOf("more:") === 0) return renderMore(id);
    var n = model.nodes[id];
    var panel = el.querySelector(".vg-panel");
    if (!n) { panel.hidden = true; return; }
    var t = TYPES[n.type] || TYPES.account;
    var title = n.type === "account" || n.type === "signup" ? (n.display || n.platform) : n.label;
    var sub = n.type === "account" ? "@" + n.handle : n.type === "signup" ? "registered with " + n.handle :
      n.meta.root ? "searched by you" : n.meta.depth ? "lead found during the investigation" : "";
    var hp = bestPhoto(n);
    var h = '<header><span class="vg-glyph" style="--c:' + esc(n.type === "account" ? (CATEGORY[n.category] || "#9aa5b1") : t.color) + '">' +
      (hp ? '<img class="vg-photo" src="' + esc(hp) + '" alt="" referrerpolicy="no-referrer">' :
        '<img src="' + (n.type === "account" || n.type === "signup" ? brand(n.platform, n.display, CATEGORY[n.category] || "#8a939d").img : icon(n.type, t.color)) + '" alt="">') + "</span>" +
      '<div><p class="vg-kind">' + esc(n.type === "account" || n.type === "signup" ? t.label + (n.category ? " · " + V.catLabel(n.category) : "") : t.label) + "</p>" +
      "<h2>" + esc(title) + "</h2>" + (sub ? '<p class="vg-sub">' + esc(sub) + "</p>" : "") + "</div>" +
      '<button type="button" class="vg-x" data-act="close" aria-label="Close">×</button></header>';

    var facts = [];
    if (n.confidence) facts.push(["Confidence", '<span class="vg-grade-tag g-' + esc(n.confidence) + '">' + esc(n.confidence) + "</span>"]);
    if (n.meta.root) { /* shown in the header */ }
    else if (n.meta.depth) facts.push(["Origin", "found and followed, " + n.meta.depth + (n.meta.depth === 1 ? " step" : " steps") + " from your search"]);
    if (n.lat !== undefined && !isNaN(n.lat)) facts.push(["Coordinates", esc(n.lat.toFixed(4) + ", " + n.lng.toFixed(4))]);
    if (n.meta.avatar) facts.push(["Picture", "same profile picture as another account"]);
    if (facts.length) h += '<dl class="vg-facts">' + facts.map(function (f) { return "<dt>" + f[0] + "</dt><dd>" + f[1] + "</dd>"; }).join("") + "</dl>";

    var srcs = Object.keys(n.sources);
    if (srcs.length) {
      h += "<h3>Found by " + srcs.length + (srcs.length === 1 ? " source" : " sources") + '</h3><p class="vg-tags">' +
        srcs.map(function (s) { return "<span>" + esc(V.label(s)) + "</span>"; }).join("") + "</p>";
    }
    if (n.meta.checked) {
      var ch = n.meta.checked, none = [], bad = [];
      Object.keys(ch).forEach(function (m) { if (ch[m] === "fail") bad.push(V.label(m)); else if (ch[m] === "empty") none.push(V.label(m)); });
      if (none.length) h += '<p class="vg-note">Nothing found on ' + esc(none.join(", ")) + "</p>";
      if (bad.length) h += '<p class="vg-note vg-bad">Could not check ' + esc(bad.join(", ")) + "</p>";
    }
    if (n.notes.length) h += "<h3>Notes</h3>" + n.notes.slice(0, 3).map(function (x) { return '<p class="vg-bio">' + esc(x.slice(0, 280)) + "</p>"; }).join("");

    var urls = Object.keys(n.urls).filter(safeUrl);
    if (n.lat !== undefined && !isNaN(n.lat)) urls.push("https://www.openstreetmap.org/?mlat=" + n.lat + "&mlon=" + n.lng + "#map=13/" + n.lat + "/" + n.lng);
    if (urls.length) {
      h += "<h3>Links</h3><ul class=\"vg-links\">" + urls.slice(0, 8).map(function (u) {
        return '<li><a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(u.replace(/^https?:\/\//, "").slice(0, 60)) + "</a></li>";
      }).join("") + "</ul>";
    }

    var pics = Object.keys(n.photos).filter(safeUrl);
    if (pics.length) {
      h += "<h3>Profile pictures</h3>";
      pics.slice(0, 3).forEach(function (p) {
        var links = V.reverseLinks(p);
        h += '<div class="vg-pic"><img src="' + esc(p) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add(\'vg-noimg\')"><div><p>Reverse image search</p>' +
          Object.keys(links).map(function (k) { return '<a class="ve-chip" href="' + esc(links[k]) + '" target="_blank" rel="noopener noreferrer">' + esc(k) + "</a>"; }).join("") +
          "</div></div>";
      });
    }

    // neighbours, grouped by type
    var hood = {};
    Object.keys(model.edges).forEach(function (k) {
      var e = model.edges[k];
      var other = e.source === id ? e.target : e.target === id ? e.source : "";
      if (!other || !model.nodes[other]) return;
      (hood[model.nodes[other].type] = hood[model.nodes[other].type] || []).push({ id: other, e: e });
    });
    var groups = ["subject"].concat(ORDER).filter(function (g) { return hood[g]; });
    if (groups.length) {
      h += "<h3>Connected</h3>";
      groups.forEach(function (g) {
        var list = hood[g];
        h += '<p class="vg-group">' + esc((TYPES[g] || TYPES.account).label) + " <b>" + list.length + "</b></p><ul class=\"vg-hood\">" +
          list.slice(0, 12).map(function (x) {
            var o = model.nodes[x.id];
            var name = o.type === "account" ? (o.display || o.platform) + " · " + o.handle : o.type === "signup" ? (o.display || o.platform) : o.label;
            return '<li><button type="button" data-act="goto" data-id="' + esc(x.id) + '"><span>' + esc(name) + "</span><small>" + esc(o.type === "signup" ? "registered" : edgeLabel(x.e)) + "</small></button></li>";
          }).join("") + (list.length > 12 ? '<li class="vg-more">' + (list.length - 12) + " more</li>" : "") + "</ul>";
      });
    }

    // actions
    var term = n.type === "account" ? n.handle : n.type === "signup" ? "" :
      ["email", "username", "phone", "wallet"].indexOf(n.type) >= 0 ? n.label : "";
    var copyVal = n.type === "account" || n.type === "signup" ? n.handle : n.label;
    h += '<footer class="vg-actions">' +
      (term ? '<button type="button" class="vg-primary" data-ve-search="' + esc(term) + '">Investigate ' + esc(term.length > 24 ? term.slice(0, 22) + "…" : term) + "</button>" : "") +
      '<button type="button" data-act="copy" data-value="' + esc(copyVal) + '">Copy</button></footer>';
    panel.innerHTML = h;
  }

  function copy(value, btn) {
    var done = function () { var t = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = t; }, 1200); };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(value).then(done, function () {});
    } catch (e) { /* clipboard blocked */ }
  }

  // ---- tooltip -------------------------------------------------------------------
  function tip(ev, html) {
    var t = el.querySelector(".vg-tip");
    if (!ev || !html) { t.hidden = true; return; }
    t.innerHTML = html;
    t.hidden = false;
    var p = ev.renderedPosition || { x: 0, y: 0 };
    var box = el.querySelector(".vg-body").getBoundingClientRect();
    t.style.left = Math.min(p.x + 14, box.width - t.offsetWidth - 8) + "px";
    t.style.top = Math.max(8, p.y - t.offsetHeight - 10) + "px";
  }
  function edgeTip(e) {
    var m = model.edges[e.id()];
    if (!m) return "";
    var a = model.nodes[m.source], b = model.nodes[m.target];
    var line = esc(edgeLabel(m));
    if (m.kind === "pivot") line = "<b>Lead followed</b><br>" + esc((m.notes.from ? "found by " + m.notes.from + ", " : "") + "checked with " + Object.keys(m.checks).map(V.label).join(", ")) + (m.notes.depth ? "<br>depth " + esc(m.notes.depth) : "");
    else if (m.kind === "avatar") line = "<b>Same profile picture</b><br>perceptual hash distance " + esc(m.notes.distance);
    else if (m.kind === "found" || m.kind === "fact") line = "<b>" + esc(Object.keys(m.modules).map(V.label).join(", ")) + "</b>";
    return '<p class="vg-tip-path">' + esc(short(a)) + " → " + esc(short(b)) + "</p>" + line;
  }
  function nodeTip(n) {
    var m = model.nodes[n.id()];
    if (!m) return "";
    var s = Object.keys(m.sources).length;
    return "<b>" + esc(short(m)) + "</b><br>" + esc((TYPES[m.type] || TYPES.account).label) +
      (m.confidence ? " · " + esc(m.confidence) : "") + (s ? " · " + s + (s === 1 ? " source" : " sources") : "");
  }
  function short(n) {
    if (!n) return "";
    var s = n.type === "account" ? (n.display || n.platform) + " " + n.handle : n.type === "signup" ? (n.display || n.platform) : n.label;
    return s.length > 40 ? s.slice(0, 38) + "…" : s;
  }

  // ---- header bits -------------------------------------------------------------
  function counts() {
    var c = {};
    Object.keys(model.nodes).forEach(function (id) { var t = model.nodes[id].type; c[t] = (c[t] || 0) + 1; });
    return c;
  }
  function renderCounts() {
    var c = counts(), conf = 0;
    Object.keys(model.nodes).forEach(function (id) { var n = model.nodes[id]; if (n.type === "account" && n.confidence === "confirmed") conf++; });
    var parts = [];
    if (c.account) parts.push(c.account + " accounts" + (conf ? ", " + conf + " confirmed" : ""));
    parts.push(model.results + " source results");
    el.querySelector(".vg-counts").textContent = model.results ? parts.join(" \u00b7 ") : "";
  }
  function renderChips() {
    var c = counts();
    el.querySelector(".vg-types").innerHTML = ORDER.filter(function (t) { return c[t]; }).map(function (t) {
      var color = TYPES[t].color;
      return '<button type="button" data-act="type" data-type="' + t + '" aria-pressed="' + (filters.types[t] ? "true" : "false") + '" title="' + esc(TYPES[t].label) + '" aria-label="' + esc(TYPES[t].label) + " " + c[t] + '">' +
        '<img src="' + icon(t, color) + '" alt="">' + "<b>" + c[t] + "</b></button>";
    }).join("");
  }
  function renderLegend() {
    el.querySelector(".vg-legend").innerHTML =
      '<p><i class="lg-conf"></i>confirmed</p><p><i class="lg-cand"></i>unconfirmed</p>' +
      '<p><i class="lg-pivot"></i>lead followed</p><p><i class="lg-avatar"></i>same picture</p>';
  }

  // ---- export --------------------------------------------------------------------
  function download(name, href) {
    var a = document.createElement("a");
    a.href = href; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }
  function fileBase() {
    var r = (V.state().roots || [])[0] || "case";
    return "veiled-eye-graph-" + String(r).replace(/[^a-z0-9@._-]+/gi, "_").slice(0, 40);
  }
  function exportPng() {
    if (!cy || !cy.nodes().length) return;
    download(fileBase() + ".png", cy.png({ full: true, scale: 2, bg: "#070d12", maxWidth: 6000, maxHeight: 6000 }));
  }
  function exportJson() {
    var out = {
      generated: new Date().toISOString(), roots: V.state().roots,
      nodes: Object.keys(model.nodes).map(function (id) {
        var n = model.nodes[id];
        return {
          id: id, type: n.type, label: n.label, platform: n.platform || undefined, handle: n.handle || undefined,
          confidence: n.confidence || undefined, category: n.category || undefined, sources: Object.keys(n.sources),
          urls: Object.keys(n.urls), lat: n.lat, lng: n.lng,
        };
      }),
      edges: Object.keys(model.edges).map(function (id) {
        var e = model.edges[id];
        return { source: e.source, target: e.target, kind: e.kind, modules: Object.keys(e.modules), followed_with: Object.keys(e.checks) };
      }),
    };
    var blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    download(fileBase() + ".json", url);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  // ---- show / hide -----------------------------------------------------------------
  function show() {
    mount();
    visible = true;
    el.hidden = false;
    position();
    var start = function () { initCy(); position(); safeSync(); };
    if (document.fonts && document.fonts.load) {
      Promise.all([
        document.fonts.load("400 11px Roboto"), document.fonts.load("500 13px Roboto"),
        document.fonts.load("400 52px 'Font Awesome 7 Brands'", "\uf09b"), document.fonts.load("900 50px 'Font Awesome 7 Free'", "\uf439"),
      ])
        .then(start, start);
    } else start();
  }
  function hide() {
    visible = false;
    if (el) el.hidden = true;
    tip(null);
  }

  V.subscribe(function () {
    if (visible) refresh();
    else firstLayout = firstLayout || !Object.keys(V.state().results).length;
  });

  window.__veiledGraph = {
    show: show, hide: hide,
    model: function () { return buildModel(V.state()); },
    focus: function (id) { if (cy) selectNode(id, true); },
    cy: function () { return cy; },
  };
})();
