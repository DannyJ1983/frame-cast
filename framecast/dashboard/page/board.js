// The departures board: the next buses and trains, the time and the weather, in large type.
// Made for a tablet or an Amazon Echo Show by the door; it polls the home server like the dashboard.
(function () {
  "use strict";
  var F = window.DashboardFormat;
  var iconSvg = window.DashboardIcons.svg;
  var REFRESH_MS = 30000;
  var CARDS = "buses,trains,weather";
  var $ = function (id) { return document.getElementById(id); };
  var pageVersion = null;

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function tick() {
    var now = new Date();
    var time = F.clockText(now);
    if ($("time").textContent !== time) {
      $("time").textContent = time;
      $("date").textContent = F.dateText(now);
    }
  }

  function renderNow(card) {
    var data = card ? card.data : null;
    $("now").hidden = !data;
    if (!data) return;
    $("now-icon").innerHTML = iconSvg(data.now.icon);
    $("now-temp").textContent = F.tempText(data.now.temp);
    $("now-desc").textContent = data.now.text;
  }

  function row(className, lead, destination, detail, when) {
    var li = make("li", "row " + className);
    li.appendChild(lead);
    var what = make("span", "what");
    what.appendChild(make("span", "dest", destination));
    if (detail) what.appendChild(make("small", "", detail));
    li.appendChild(what);
    li.appendChild(when);
    return li;
  }

  function renderBuses(card) {
    var data = card ? card.data : null;
    $("buses").hidden = !card;
    var list = $("bus-list");
    clear(list);
    var preparing = Boolean(data && data.preparing);
    $("buses-preparing").hidden = !preparing;
    $("buses-preparing").textContent = preparing ? data.message : "";
    $("buses-stop").textContent = data && data.stop ? data.stop : "";
    var services = data && !preparing ? data.services : [];
    services.forEach(function (bus) {
      var badge = make("span", "badge", bus.route);
      badge.style.backgroundColor = F.routeColour(bus.route);
      var timing = F.busWhen(bus);
      var when = make("span", "when" + (timing.live ? " live" : ""));
      if (timing.live) when.appendChild(make("span", "live-mark"));
      when.appendChild(document.createTextNode(timing.text));
      list.appendChild(row("bus", badge, bus.destination, F.busDetail(bus), when));
    });
    $("buses-empty").hidden = !data || preparing || services.length > 0;
    $("buses-note").textContent = (card && card.error) || (data && data.note) || "";
  }

  function renderTrains(card) {
    var data = card ? card.data : null;
    $("trains").hidden = !card;
    var list = $("train-list");
    clear(list);
    $("trains-station").textContent = data ? data.station + (data.to ? " to " + data.to : "") : "";
    var services = data ? data.services : [];
    services.forEach(function (train) {
      var when = make("span", "when " + train.state, train.status);
      list.appendChild(row("train" + (train.state === "cancelled" ? " cancelled" : ""),
        make("span", "clock", train.time), train.destination, F.trainDetail(train), when));
    });
    $("trains-empty").hidden = !data || services.length > 0;
    $("trains-note").textContent = (card && card.error) || (data && data.messages && data.messages[0]) || "";
  }

  /** Drop rows from the end of a list until all that's left fits. */
  function fit(list) {
    while (list.children.length > 1 && list.scrollHeight > list.clientHeight + 1) {
      list.removeChild(list.lastChild);
    }
  }

  function render(snapshot) {
    $("offline").hidden = true;
    if (pageVersion && snapshot.page_version && snapshot.page_version !== pageVersion) {
      window.location.reload(); // the home server was updated
      return;
    }
    pageVersion = snapshot.page_version;
    var cards = snapshot.cards || {};
    renderNow(cards.weather);
    renderBuses(cards.buses);
    renderTrains(cards.trains);
    $("setup").hidden = Boolean(cards.buses || cards.trains);
    $("setup-address").textContent = window.location.protocol + "//" + window.location.host;
    fit($("bus-list"));
    fit($("train-list"));
  }

  function load() {
    fetch("/api/dashboard?cards=" + CARDS, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error(response.statusText);
        return response.json();
      })
      .then(render)
      .catch(function () {
        $("offline").hidden = false;
      });
  }

  // Keeping it on screen ------------------------------------------------------------------
  // The Echo Show's Silk browser goes back to the home screen after a few minutes unless
  // something is playing. A silent sound, looped and restarted each minute, counts as
  // playing (the approach of the Keep Silk Open project). Browsers only allow sound after
  // a tap, hence the button.

  var audio = null;
  var awake = false;

  function le(value, bytes) {
    var text = "";
    for (var i = 0; i < bytes; i++) text += String.fromCharCode((value >> (8 * i)) & 255);
    return text;
  }

  /** One second of silence as a WAV: 8 kHz, 8-bit, mono. */
  function silentWav() {
    var rate = 8000;
    var header = "RIFF" + le(36 + rate, 4) + "WAVEfmt " + le(16, 4) + le(1, 2) + le(1, 2) +
      le(rate, 4) + le(rate, 4) + le(1, 2) + le(8, 2) + "data" + le(rate, 4);
    return "data:audio/wav;base64," + window.btoa(header + new Array(rate + 1).join(String.fromCharCode(128)));
  }

  function keepAwake() {
    if (!audio) {
      audio = new Audio(silentWav());
      audio.loop = true;
    }
    var started = audio.play();
    var done = function () {
      awake = true;
      $("keep-awake").hidden = true;
    };
    if (started && started.then) {
      started.then(done, function () {
        $("keep-awake").textContent = "That didn't work. Tap again to keep this on screen";
      });
    } else {
      done();
    }
    if (navigator.wakeLock && navigator.wakeLock.request) {
      navigator.wakeLock.request("screen").then(null, function () {});
    }
  }

  setInterval(function () {
    if (!awake || !audio) return;
    audio.currentTime = 0;
    var again = audio.play();
    if (again && again.then) again.then(null, function () {});
  }, 60000);

  var askToKeepAwake = /Silk/.test(navigator.userAgent) || /[?&]keepawake=1/.test(window.location.search);
  $("keep-awake").hidden = !askToKeepAwake;
  $("keep-awake").addEventListener("click", keepAwake);

  tick();
  setInterval(tick, 1000);
  load();
  setInterval(load, REFRESH_MS);
  window.Board = { render: render, load: load, awake: function () { return awake; } };
})();
