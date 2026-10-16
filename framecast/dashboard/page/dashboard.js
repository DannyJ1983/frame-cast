// The dashboard page: polls the home server and draws the cards, the clock and the sports ticker.
// Runs on the 2019 TV's Chromium 63 (inside the TV app), as well as on phones and laptops.
(function () {
  "use strict";
  var F = window.DashboardFormat;
  var REFRESH_MS = 30000;
  var TICKER_REMS_PER_SECOND = 4.5;
  var $ = function (id) { return document.getElementById(id); };
  var pageVersion = null;
  var tickerKey = "";

  // Weather icons, drawn on a 64x64 grid. Static markup only; all data goes in as text.
  var SUN_RAYS = '<g stroke="#ffc94d" stroke-width="4" stroke-linecap="round"><path d="M32 6v7M32 51v7M6 32h7M51 32h7M13.6 13.6l5 5M45.4 45.4l5 5M13.6 50.4l5-5M45.4 18.6l5-5"/></g>';
  var SMALL_SUN = '<circle cx="22" cy="22" r="9" fill="#ffc94d"/><g stroke="#ffc94d" stroke-width="3.5" stroke-linecap="round"><path d="M22 4v5M4 22h5M9.3 9.3l3.5 3.5M34.7 9.3l-3.5 3.5"/></g>';
  var SMALL_MOON = '<path d="M28 6a14 14 0 1 0 10 22A12 12 0 0 1 28 6z" fill="#dce4f0"/>';
  var CLOUD = '<path d="M18 52h30a11 11 0 0 0 1-22 15 15 0 0 0-29-3 12 12 0 0 0-2 25z" fill="#cfd8e3"/>';
  var CLOUD_LOW = '<path d="M24 56h26a10 10 0 0 0 1-20 13 13 0 0 0-25-3 10.5 10.5 0 0 0-2 23z" fill="#cfd8e3"/>';
  var CLOUD_HIGH = '<path d="M18 42h30a11 11 0 0 0 1-22 15 15 0 0 0-29-3 12 12 0 0 0-2 25z" fill="#cfd8e3"/>';
  var DROPS = '<g stroke="#6fb6ff" stroke-width="3.5" stroke-linecap="round"><path d="M23 49l-3 7M33 49l-3 7M43 49l-3 7"/></g>';
  var ICONS = {
    clear: '<circle cx="32" cy="32" r="12" fill="#ffc94d"/>' + SUN_RAYS,
    "clear-night": '<path d="M40 8a24 24 0 1 0 16 38A20 20 0 0 1 40 8z" fill="#dce4f0"/>',
    partly: SMALL_SUN + CLOUD_LOW,
    "partly-night": SMALL_MOON + CLOUD_LOW,
    cloud: CLOUD,
    fog: '<g stroke="#aeb9c7" stroke-width="4" stroke-linecap="round"><path d="M12 22h40M8 32h48M14 42h36M20 52h24"/></g>',
    drizzle: CLOUD_HIGH + '<g fill="#6fb6ff"><circle cx="23" cy="52" r="2.5"/><circle cx="33" cy="56" r="2.5"/><circle cx="43" cy="52" r="2.5"/></g>',
    rain: CLOUD_HIGH + DROPS,
    showers: '<circle cx="46" cy="16" r="8" fill="#ffc94d"/>' + CLOUD_HIGH + DROPS,
    snow: CLOUD_HIGH + '<g fill="#ffffff"><circle cx="22" cy="52" r="3"/><circle cx="32" cy="57" r="3"/><circle cx="42" cy="52" r="3"/></g>',
    thunder: CLOUD_HIGH + '<path d="M35 40l-9 13h7l-4 10 12-15h-7l4-8z" fill="#ffc94d"/>',
  };

  function iconSvg(name) {
    return '<svg viewBox="0 0 64 64" aria-hidden="true">' + (ICONS[name] || ICONS.cloud) + "</svg>";
  }

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function note(name, card) {
    var el = document.querySelector('[data-note="' + name + '"]');
    if (el) el.textContent = card && card.error ? card.error : "";
  }

  // Clock -------------------------------------------------------------------------

  function tick() {
    var now = new Date();
    var time = F.clockText(now);
    if ($("time").textContent !== time) {
      $("time").textContent = time;
      $("date").textContent = F.dateText(now);
    }
  }

  // Cards -------------------------------------------------------------------------

  function renderWeather(card, place) {
    var data = card ? card.data : null;
    $("weather").hidden = !card;
    $("now").hidden = !data;
    note("weather", card);
    if (!data) return;
    var now = data.now;
    $("now-icon").innerHTML = iconSvg(now.icon);
    $("now-temp").textContent = F.tempText(now.temp);
    $("now-desc").textContent = now.text + (typeof now.feels === "number" ? " · feels like " + F.tempText(now.feels) : "");
    $("now-place").textContent = place || "";
    $("weather-place").textContent = place || "";

    var today = data.today;
    var range = $("today-range");
    clear(range);
    if (today) {
      range.appendChild(document.createTextNode(F.tempText(today.high) + " "));
      range.appendChild(make("span", "low", "/ " + F.tempText(today.low)));
      $("today-text").textContent = today.text;
      $("today-rain").textContent = typeof today.rain_chance === "number" ? today.rain_chance + "% chance of rain" : "";
      $("today-rain").className = today.rain_chance >= 40 ? "rain" : "";
      $("today-sun").textContent = today.sunrise ? "Sunrise " + today.sunrise + " · sunset " + today.sunset : "";
    }
    $("today-wind").textContent = typeof now.wind_mph === "number" ? "Wind " + now.wind_mph + " mph" : "";

    var hours = $("hours");
    clear(hours);
    (data.hours || []).forEach(function (hour) {
      var slot = make("div", "hour");
      slot.appendChild(make("div", "hour-time", hour.time));
      var pic = make("div", "hour-icon");
      pic.innerHTML = iconSvg(hour.icon);
      slot.appendChild(pic);
      slot.appendChild(make("div", "hour-temp", F.tempText(hour.temp)));
      slot.appendChild(make("div", "hour-rain", hour.rain_chance >= 20 ? hour.rain_chance + "%" : ""));
      hours.appendChild(slot);
    });

    var days = $("days");
    clear(days);
    (data.days || []).forEach(function (day) {
      var li = make("li", "day");
      li.appendChild(make("span", "day-name", F.dayName(day.date)));
      var pic = make("span", "day-icon");
      pic.innerHTML = iconSvg(day.icon);
      li.appendChild(pic);
      li.appendChild(make("span", "day-text", day.text));
      li.appendChild(make("span", "day-rain", day.rain_chance >= 20 ? day.rain_chance + "%" : ""));
      var range = make("span", "day-range", F.tempText(day.high) + " ");
      range.appendChild(make("span", "low", F.tempText(day.low)));
      li.appendChild(range);
      days.appendChild(li);
    });
  }

  function renderTrains(card, rowLimit) {
    var data = card ? card.data : null;
    $("trains").hidden = !card;
    note("trains", card);
    var body = $("departures");
    clear(body);
    if (!data) {
      $("trains-empty").hidden = true;
      $("trains-message").hidden = true;
      return;
    }
    $("trains-station").textContent = data.station + (data.to ? " to " + data.to : "");
    data.services.slice(0, rowLimit).forEach(function (service) {
      var row = make("tr", service.state === "cancelled" ? "cancelled" : "");
      row.appendChild(make("td", "dep-time", service.time));
      var dest = make("td", "dep-dest");
      dest.appendChild(make("div", "dep-name", service.destination));
      var detail = F.trainDetail(service);
      if (detail) dest.appendChild(make("small", "", detail));
      row.appendChild(dest);
      row.appendChild(make("td", "dep-status " + service.state, service.status));
      body.appendChild(row);
    });
    $("trains-empty").hidden = data.services.length > 0;
    var message = data.messages && data.messages[0];
    $("trains-message").hidden = !message;
    $("trains-message").textContent = message || "";
  }

  function renderBuses(card, rowLimit) {
    var data = card ? card.data : null;
    $("buses").hidden = !card;
    note("buses", card);
    var body = $("bus-rows");
    clear(body);
    var preparing = Boolean(data && data.preparing);
    $("buses-preparing").hidden = !preparing;
    $("buses-preparing").textContent = preparing ? data.message : "";
    var services = data && !preparing ? data.services : [];
    $("buses-stop").textContent = data && data.stop ? data.stop : "";
    services.slice(0, rowLimit).forEach(function (bus) {
      var row = make("tr");
      var route = make("td", "bus-route");
      var badge = make("span", "route-badge", bus.route);
      badge.style.backgroundColor = F.routeColour(bus.route);
      route.appendChild(badge);
      row.appendChild(route);
      var dest = make("td", "bus-dest");
      dest.appendChild(make("div", "dep-name", bus.destination));
      var detail = F.busDetail(bus);
      if (detail) dest.appendChild(make("small", "", detail));
      row.appendChild(dest);
      var when = F.busWhen(bus);
      var cell = make("td", "bus-when" + (when.live ? " live" : ""));
      if (when.live) cell.appendChild(make("span", "live-mark"));
      cell.appendChild(document.createTextNode(when.text));
      row.appendChild(cell);
      body.appendChild(row);
    });
    $("buses-empty").hidden = !data || preparing || services.length > 0;
    $("buses-legend").hidden = !services.some(function (bus) { return bus.live; });
    $("buses-note").textContent = data && data.note ? data.note : "";
  }

  function renderTraffic(card, label) {
    var data = card ? card.data : null;
    $("traffic").hidden = !card;
    note("traffic", card);
    $("traffic-title").textContent = label ? "Drive to " + label : "Drive";
    if (!data) {
      $("drive-minutes").textContent = "";
      $("drive-text").textContent = "";
      return;
    }
    $("drive-minutes").textContent = data.minutes + " min";
    $("drive-minutes").className = "drive-minutes " + data.state;
    $("drive-text").textContent = F.trafficText(data);
  }

  function renderNews(card, now) {
    var data = card ? card.data : null;
    $("news").hidden = !card;
    note("news", card);
    var list = $("headlines");
    clear(list);
    if (!data) return;
    $("news-source").textContent = data.source || "";
    data.headlines.forEach(function (item) {
      var li = make("li");
      li.appendChild(make("div", "headline", item.title));
      var age = F.ago(item.published, now);
      if (age) li.appendChild(make("div", "headline-age", age));
      list.appendChild(li);
    });
  }

  // Sports ticker -----------------------------------------------------------------

  function tickItems(data, now) {
    var items = [];
    var league = null;
    (data.matches || []).forEach(function (match) {
      var item = make("span", "tick" + (match.state === "in" ? " live" : "") + (match.favourite ? " favourite" : ""));
      if (match.league !== league) {
        league = match.league;
        item.appendChild(make("span", "tick-league", league));
      }
      var parts = F.matchParts(match, now);
      if (parts.lead) item.appendChild(make("span", "tick-lead", parts.lead));
      var teams = make("span", "tick-teams");
      teams.appendChild(document.createTextNode(parts.home));
      teams.appendChild(make("span", "tick-score", parts.score));
      teams.appendChild(document.createTextNode(parts.away));
      item.appendChild(teams);
      items.push(item);
    });
    if (!items.length) {
      (data.headlines || []).forEach(function (headline) {
        items.push(make("span", "tick", headline.title));
      });
    }
    return items;
  }

  function renderSport(card, now) {
    var data = card ? card.data : null;
    $("sport").hidden = !card || !data;
    if (!data) return;
    var live = (data.matches || []).some(function (m) { return m.state === "in"; });
    $("ticker-label").textContent = live ? "Live" : "Sport";
    $("ticker-label").className = "ticker-label" + (live ? " live" : "");
    var items = tickItems(data, now);
    var key = items.map(function (item) { return item.textContent; }).join("|");
    if (key === tickerKey) return; // unchanged: leave the scrolling alone
    tickerKey = key;
    var track = $("ticker-track");
    track.className = "ticker-track";
    clear(track);
    items.forEach(function (item) { track.appendChild(item); });
    var width = track.scrollWidth;
    if (width <= $("ticker-window").clientWidth) return;
    // Two copies, scrolled by half, loop without a jump.
    items.forEach(function (item) { track.appendChild(item.cloneNode(true)); });
    var rem = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
    track.style.animationDuration = Math.round(width / (rem * TICKER_REMS_PER_SECOND)) + "s";
    track.className = "ticker-track moving";
  }

  // Layout ------------------------------------------------------------------------

  function layoutColumns() {
    var columns = document.querySelectorAll(".column");
    for (var i = 0; i < columns.length; i++) {
      var shown = columns[i].querySelectorAll(".card:not([hidden])");
      columns[i].hidden = shown.length === 0;
      columns[i].classList.toggle("shared", columns[i].getAttribute("data-column") === "middle" && shown.length > 1);
      var cards = columns[i].querySelectorAll(".card");
      for (var j = 0; j < cards.length; j++) cards[j].classList.toggle("grow", cards[j] === shown[shown.length - 1]);
    }
  }

  /** Drop rows from the end of a list until its card shows them all (on screens where cards share the height). */
  function fit(card, list) {
    if (card.hidden) return;
    while (list.children.length > 1 && card.scrollHeight > card.clientHeight + 1) {
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
    var now = new Date();
    $("setup").hidden = !F.needsSetup(snapshot);
    $("setup-address").textContent = window.location.protocol + "//" + window.location.host;
    renderWeather(cards.weather, snapshot.place);
    renderTraffic(cards.traffic, snapshot.traffic_label);
    renderTrains(cards.trains, 8);
    renderBuses(cards.buses, 8);
    renderNews(cards.news, now);
    renderSport(cards.sport, now);
    layoutColumns();
    fit($("trains"), $("departures"));
    fit($("buses"), $("bus-rows"));
    fit($("news"), $("headlines"));
    fit($("weather"), $("days"));
  }

  function load() {
    fetch("/api/dashboard", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error(response.statusText);
        return response.json();
      })
      .then(render)
      .catch(function () {
        $("offline").hidden = false;
      });
  }

  // Inside the TV app, keys pressed while this page has focus are handed to the app.
  if (window.parent !== window) {
    document.addEventListener("keydown", function (event) {
      window.parent.postMessage({ frameCastKey: event.keyCode }, "*");
      event.preventDefault();
    });
  }

  tick();
  setInterval(tick, 1000);
  load();
  setInterval(load, REFRESH_MS);
  window.Dashboard = { render: render, load: load };
})();
