// Phone page: set up the TV's dashboard, and show it on the TV.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let saved = null; // the settings as the home server last sent them

  function say(text, isError) {
    const el = $("dash-message");
    el.textContent = text || "";
    el.classList.toggle("error", Boolean(isError));
  }

  function keyField(id, forgetId, has) {
    $(id).value = "";
    $(id).placeholder = has ? "Saved. Type a new key to replace it." : "Paste your key here";
    $(forgetId).hidden = !has;
  }

  function fill(settings, options) {
    saved = settings;
    $("dash-place").value = settings.place;
    $("dash-place-found").textContent = settings.place_name ? `Found: ${settings.place_name}` : "";
    $("dash-station").value = settings.station;
    $("dash-station-to").value = settings.station_to;
    $("dash-traffic-to").value = settings.traffic_to;
    $("dash-traffic-label").value = settings.traffic_label;
    $("dash-traffic-found").textContent = settings.traffic_to_name ? `Found: ${settings.traffic_to_name}` : "";
    keyField("dash-rail-key", "dash-rail-forget", settings.has_rail_key);
    keyField("dash-traffic-key", "dash-traffic-forget", settings.has_traffic_key);
    keyField("dash-bus-key", "dash-bus-forget", settings.has_bus_key);
    $("dash-bus-stops").value = settings.bus_stops;
    $("dash-bus-lines").value = settings.bus_lines;
    if (options) {
      const select = $("dash-news");
      select.textContent = "";
      for (const feed of [...options.news, { id: "custom", name: "Another feed…" }]) {
        select.append(new Option(feed.name, feed.id));
      }
      const regions = $("dash-bus-region");
      regions.textContent = "";
      for (const region of [{ id: "auto", name: "Work it out from my postcode" }, ...options.bus_regions]) {
        regions.append(new Option(region.name, region.id));
      }
      const leagues = $("dash-leagues");
      leagues.textContent = "";
      for (const league of options.leagues) {
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.value = league.id;
        label.append(box, league.name);
        leagues.append(label);
      }
    }
    $("dash-bus-region").value = settings.bus_region;
    $("dash-news").value = settings.news;
    $("dash-news-url").value = settings.news_url;
    $("dash-news-url").hidden = settings.news !== "custom";
    for (const box of $("dash-leagues").querySelectorAll("input")) {
      box.checked = settings.leagues.includes(box.value);
    }
    $("dash-teams").value = settings.teams;
  }

  async function put(body) {
    const response = await fetch("/api/dashboard/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok && data.settings) fill(data.settings);
    say(data.message || response.statusText, !response.ok);
    return response.ok;
  }

  async function save(event) {
    event.preventDefault();
    const body = {
      place: $("dash-place").value,
      station: $("dash-station").value,
      station_to: $("dash-station-to").value,
      bus_stops: $("dash-bus-stops").value,
      bus_lines: $("dash-bus-lines").value,
      bus_region: $("dash-bus-region").value,
      traffic_to: $("dash-traffic-to").value,
      traffic_label: $("dash-traffic-label").value,
      news: $("dash-news").value,
      news_url: $("dash-news-url").value,
      leagues: [...$("dash-leagues").querySelectorAll("input:checked")].map((box) => box.value),
      teams: $("dash-teams").value,
    };
    // An empty key box means "keep the saved key".
    if ($("dash-rail-key").value.trim()) body.rail_key = $("dash-rail-key").value;
    if ($("dash-traffic-key").value.trim()) body.traffic_key = $("dash-traffic-key").value;
    if ($("dash-bus-key").value.trim()) body.bus_key = $("dash-bus-key").value;
    $("dash-save").disabled = true;
    say("Saving…");
    try {
      await put(body);
    } catch (e) {
      say("Couldn't reach the home server.", true);
    } finally {
      $("dash-save").disabled = false;
    }
  }

  async function show() {
    try {
      const response = await fetch("/api/dashboard/show", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      say(data.message || response.statusText, !response.ok);
    } catch (e) {
      say("Couldn't reach the home server.", true);
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/dashboard/settings");
      const data = await response.json();
      fill(data.settings, data.options);
    } catch (e) {
      say("Couldn't load the dashboard settings.", true);
    }
  }

  $("dash-form").addEventListener("submit", save);
  $("dash-show").addEventListener("click", show);
  $("dash-news").addEventListener("change", () => {
    $("dash-news-url").hidden = $("dash-news").value !== "custom";
  });
  $("dash-rail-forget").addEventListener("click", () => put({ rail_key: "" }));
  $("dash-traffic-forget").addEventListener("click", () => put({ traffic_key: "" }));
  $("dash-bus-forget").addEventListener("click", () => put({ bus_key: "" }));
  load();
})();
