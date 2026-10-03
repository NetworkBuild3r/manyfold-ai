/* Library Forge duplicates table. INIT-032/SPEC-014. Relative fetches only. */
(function () {
  "use strict";

  var PAGE = 50;
  var meta = null;
  var indexDoc = null;
  var chunks = {};
  var filter = "";
  var sortKey = "shared_bytes";
  var sortDir = -1;
  var page = 0;
  var view = [];
  var open = {};

  function $(id) {
    return document.getElementById(id);
  }

  function pad(n) {
    var s = String(n);
    return ("0000" + s).slice(-4);
  }

  function fmtBytes(n) {
    n = Number(n) || 0;
    var units = ["B", "KiB", "MiB", "GiB", "TiB"];
    var i = 0;
    var x = n;
    while (x >= 1024 && i < units.length - 1) {
      x /= 1024;
      i += 1;
    }
    var num = i === 0 ? String(n) : x.toFixed(2);
    return num + " " + units[i];
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) {
        throw new Error("failed " + url);
      }
      return r.json();
    });
  }

  function chunkUrl(i) {
    return "data/pairs/c" + pad(i) + ".json";
  }

  function loadChunk(i) {
    if (chunks[i]) {
      return Promise.resolve(chunks[i]);
    }
    return getJSON(chunkUrl(i)).then(function (rows) {
      chunks[i] = rows;
      return rows;
    });
  }

  function pairId(pair, chunk, offset) {
    return pair.pack_a + "\0" + pair.pack_b + "\0" + chunk + "\0" + offset;
  }

  function loadIndex() {
    if (indexDoc) {
      return Promise.resolve(indexDoc);
    }
    return getJSON("data/pairs/index.json").then(function (doc) {
      indexDoc = doc;
      return doc;
    });
  }

  function matches(packA, packB, q) {
    if (!q) {
      return true;
    }
    return packA.toLowerCase().indexOf(q) !== -1 || packB.toLowerCase().indexOf(q) !== -1;
  }

  function compare(a, b) {
    var av = a[sortKey];
    var bv = b[sortKey];
    if (typeof av === "string") {
      av = av.toLowerCase();
      bv = String(bv || "").toLowerCase();
      if (av < bv) {
        return -1 * sortDir;
      }
      if (av > bv) {
        return 1 * sortDir;
      }
      return 0;
    }
    av = Number(av) || 0;
    bv = Number(bv) || 0;
    if (av < bv) {
      return -1 * sortDir;
    }
    if (av > bv) {
      return 1 * sortDir;
    }
    return 0;
  }

  function setStatus(text) {
    var el = $("status");
    if (el) {
      el.textContent = text;
    }
  }

  function renderRows() {
    var body = $("rows");
    var start = page * PAGE;
    var slice = view.slice(start, start + PAGE);
    var html = [];
    var i;
    for (i = 0; i < slice.length; i += 1) {
      var p = slice[i];
      var id = pairId(p, p._chunk, p._off);
      html.push("<tr class=\"pair\" data-id=\"" + esc(id) + "\">");
      html.push("<td class=\"path\">" + esc(p.pack_a) + "</td>");
      html.push("<td class=\"path\">" + esc(p.pack_b) + "</td>");
      html.push("<td class=\"num\">" + esc(p.shared_meshes) + "</td>");
      html.push("<td class=\"num\">" + esc(fmtBytes(p.shared_bytes)) + "</td>");
      html.push("<td class=\"num\">" + esc(Number(p.containment_count || 0).toFixed(3)) + "</td>");
      html.push("<td>" + (p.archives_differ ? "yes" : "no") + "</td>");
      html.push("</tr>");
      if (open[id]) {
        html.push("<tr class=\"detail\"><td colspan=\"6\">");
        var shared = p.shared || [];
        if (!shared.length) {
          html.push("<p class=\"note\">No shared STL rows in this pair.</p>");
        } else {
          html.push("<table><thead><tr><th>name</th><th>size</th><th>sha256</th></tr></thead><tbody>");
          var j;
          for (j = 0; j < shared.length; j += 1) {
            var s = shared[j];
            html.push("<tr><td class=\"path\">" + esc(s.name) + "</td>");
            html.push("<td class=\"num\">" + esc(fmtBytes(s.size)) + "</td>");
            html.push("<td class=\"path\">" + esc(s.sha256) + "</td></tr>");
          }
          html.push("</tbody></table>");
        }
        html.push("</td></tr>");
      }
    }
    body.innerHTML = html.join("");
    $("pageinfo").textContent =
      view.length === 0
        ? "0 pairs"
        : start + 1 + "–" + Math.min(start + PAGE, view.length) + " of " + view.length;
    $("prev").disabled = page <= 0;
    $("next").disabled = start + PAGE >= view.length;
  }

  function applyViewFromPairs(pairs) {
    var q = filter;
    var rows = [];
    var i;
    for (i = 0; i < pairs.length; i += 1) {
      var p = pairs[i];
      if (matches(p.pack_a || "", p.pack_b || "", q)) {
        rows.push(p);
      }
    }
    rows.sort(compare);
    view = rows;
    var maxPage = Math.max(0, Math.ceil(view.length / PAGE) - 1);
    if (page > maxPage) {
      page = maxPage;
    }
    renderRows();
  }

  function rebuildFromIndex() {
    return loadIndex().then(function (doc) {
      var q = filter;
      var packs = doc.packs || [];
      var rows = doc.rows || [];
      var needed = {};
      var refs = [];
      var i;
      for (i = 0; i < rows.length; i += 1) {
        var r = rows[i];
        var a = packs[r[0]] || "";
        var b = packs[r[1]] || "";
        if (!matches(a, b, q)) {
          continue;
        }
        needed[r[6]] = true;
        refs.push(r);
      }
      var loads = Object.keys(needed).map(function (k) {
        return loadChunk(Number(k));
      });
      return Promise.all(loads).then(function () {
        var pairs = [];
        for (i = 0; i < refs.length; i += 1) {
          var row = refs[i];
          var chunk = chunks[row[6]] || [];
          var local = row[7];
          var pair = chunk[local];
          if (pair) {
            pair._chunk = row[6];
            pair._off = local;
            pairs.push(pair);
          }
        }
        applyViewFromPairs(pairs);
        setStatus("");
      });
    });
  }

  function firstPage() {
    if (!meta || meta.chunkCount < 1) {
      view = [];
      renderRows();
      setStatus("No pairs in this report.");
      return Promise.resolve();
    }
    if (filter) {
      setStatus("Filtering…");
      return rebuildFromIndex();
    }
    var startChunk = 0;
    var endChunk = Math.min(meta.chunkCount, 1);
    var loads = [];
    var c;
    for (c = startChunk; c < endChunk; c += 1) {
      loads.push(loadChunk(c));
    }
    return Promise.all(loads).then(function () {
      var pairs = [];
      for (c = 0; c < meta.chunkCount; c += 1) {
        if (!chunks[c]) {
          continue;
        }
        var rows = chunks[c];
        var i;
        for (i = 0; i < rows.length; i += 1) {
          rows[i]._chunk = c;
          rows[i]._off = i;
          pairs.push(rows[i]);
        }
      }
      if (!filter && meta.chunkCount > 1 && pairs.length < meta.pairCount) {
        setStatus(
          "Showing the first " +
            pairs.length +
            " pairs. Type in the filter box or use Next to load more."
        );
      } else {
        setStatus("");
      }
      applyViewFromPairs(pairs);
    });
  }

  function loadNextChunkIfNeeded() {
    if (filter) {
      return Promise.resolve();
    }
    var have = 0;
    var c;
    for (c = 0; c < meta.chunkCount; c += 1) {
      if (chunks[c]) {
        have += chunks[c].length;
      }
    }
    if ((page + 1) * PAGE <= have) {
      return Promise.resolve();
    }
    for (c = 0; c < meta.chunkCount; c += 1) {
      if (!chunks[c]) {
        setStatus("Loading…");
        return loadChunk(c).then(function () {
          return firstPage();
        });
      }
    }
    return Promise.resolve();
  }

  function onSort(ev) {
    var th = ev.target.closest("th");
    if (!th || !th.dataset.key) {
      return;
    }
    var key = th.dataset.key;
    if (sortKey === key) {
      sortDir *= -1;
    } else {
      sortKey = key;
      sortDir = key === "pack_a" || key === "pack_b" ? 1 : -1;
    }
    applyViewFromPairs(view);
  }

  function onClick(ev) {
    var tr = ev.target.closest("tr.pair");
    if (!tr) {
      return;
    }
    var id = tr.getAttribute("data-id");
    open[id] = !open[id];
    renderRows();
  }

  function debounce(fn, ms) {
    var t = 0;
    return function () {
      var args = arguments;
      window.clearTimeout(t);
      t = window.setTimeout(function () {
        fn.apply(null, args);
      }, ms);
    };
  }

  function boot() {
    if (!$("rows")) {
      return;
    }
    getJSON("data/pairs/meta.json")
      .then(function (m) {
        meta = m;
        PAGE = m.pageSize || PAGE;
        $("heads").addEventListener("click", onSort);
        $("rows").addEventListener("click", onClick);
        $("prev").addEventListener("click", function () {
          if (page > 0) {
            page -= 1;
            renderRows();
          }
        });
        $("next").addEventListener("click", function () {
          page += 1;
          loadNextChunkIfNeeded().then(function () {
            renderRows();
          });
        });
        $("filter").addEventListener(
          "input",
          debounce(function (ev) {
            filter = String(ev.target.value || "").trim().toLowerCase();
            page = 0;
            firstPage();
          }, 200)
        );
        return firstPage();
      })
      .catch(function (err) {
        setStatus(String(err.message || err));
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
