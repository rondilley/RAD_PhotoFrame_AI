/* RAD Frame shell. Polls /v1/now, swaps the fragment when the version changes,
   runs the clock from the host time (the frame has no clock battery).
   Chromium 106: no build step, no framework. */
(function () {
  "use strict";
  var view = document.getElementById("view");
  var mark = document.getElementById("mark");
  var shown = null;
  var shownName = null;
  var offsetMs = 0;
  var tzMin = 0;
  var errors = 0;
  var shellVersion = null;
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  /* A Date whose UTC fields are the host local time. */
  function hostLocal() { return new Date(Date.now() + offsetMs + tzMin * 60000); }

  function tick() {
    var d = hostLocal();
    var els = view.querySelectorAll("[data-clock]");
    for (var i = 0; i < els.length; i++) {
      var f = els[i].getAttribute("data-clock");
      var t = "";
      if (f === "hm") t = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
      else if (f === "s") t = pad(d.getUTCSeconds());
      else if (f === "date") t = DAYS[d.getUTCDay()] + ", " + MONTHS[d.getUTCMonth()] + " " + d.getUTCDate();
      else if (f === "year") t = String(d.getUTCFullYear());
      if (els[i].textContent !== t) els[i].textContent = t;
    }
    var ages = view.querySelectorAll("[data-since]");
    for (var j = 0; j < ages.length; j++) {
      var s = Math.max(0, Math.round((Date.now() + offsetMs) / 1000 - Number(ages[j].getAttribute("data-since"))));
      ages[j].textContent = s < 60 ? s + "s" : Math.floor(s / 60) + "m";
    }
  }

  function setMark(text) {
    mark.textContent = text || "";
    mark.style.display = text ? "block" : "none";
  }

  function swap(html, name) {
    var fresh = name !== shownName;
    if (fresh) view.classList.add("fade");
    view.innerHTML = html;
    tick();
    if (fresh) {
      void view.offsetWidth;
      view.classList.remove("fade");
    }
    shownName = name;
  }

  function poll() {
    var next = 10;
    fetch("/v1/now?shown=" + encodeURIComponent(shown || ""), { cache: "no-store" })
      .then(function (r) {
        if (r.status === 403) throw new Error("not authorized");
        if (!r.ok) throw new Error("host error " + r.status);
        return r.json();
      })
      .then(function (j) {
        errors = 0;
        setMark("");
        if (shellVersion === null) shellVersion = j.shell;
        else if (j.shell !== shellVersion) { location.reload(); return null; }
        offsetMs = j.host_ms - Date.now();
        tzMin = j.tz_offset_min;
        next = j.poll_s || 10;
        document.getElementById("stage").style.transform = "translate(" + j.shift.x + "px," + j.shift.y + "px)";
        if (j.version === shown) return null;
        return fetch("/v1/fragment/" + j.version).then(function (r) {
          if (r.status === 404) { next = 1; return null; }
          if (!r.ok) throw new Error("host error " + r.status);
          return r.text().then(function (html) {
            swap(html, j.dashboard);
            shown = j.version;
          });
        });
      })
      .catch(function (e) {
        errors++;
        if (String(e.message).indexOf("not authorized") >= 0) setMark("Not authorized");
        else if (errors >= 3) setMark("Host offline · last data shown");
      })
      .then(function () { setTimeout(poll, Math.max(1, next) * 1000); });
  }

  setInterval(tick, 1000);
  poll();
})();
