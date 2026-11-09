// Phone page: set up Spotify Now Playing, sign in, and show it on the TV.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);

  function say(text, isError) {
    const el = $("sp-message");
    el.textContent = text || "";
    el.classList.toggle("error", Boolean(isError));
  }

  function fill(status) {
    const settings = status.settings;
    $("sp-redirect").textContent = status.redirect_uri;
    $("sp-client-id").value = settings.client_id;
    $("sp-device").value = settings.device_name;
    $("sp-auto").checked = settings.auto_show;
    $("sp-status").textContent = settings.connected
      ? `Connected${settings.account ? ` as ${settings.account}` : ""}. Showing ${settings.device_name}.`
      : settings.client_id ? "Not connected yet: do step 2." : "Not set up yet.";
    $("sp-disconnect").hidden = !settings.connected;
    $("sp-find").hidden = !settings.connected;
  }

  async function call(method, path, body) {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (data.settings) fill(data);
    return { ok: response.ok, data };
  }

  async function save(event) {
    event.preventDefault();
    const result = await call("PUT", "/api/spotify/settings", {
      client_id: $("sp-client-id").value,
      device_name: $("sp-device").value,
      auto_show: $("sp-auto").checked,
    });
    say(result.data.message, !result.ok);
  }

  async function connect() {
    // Open the tab straight away, while the tap still counts, then send it to Spotify.
    const tab = window.open("", "_blank");
    const result = await call("POST", "/api/spotify/connect");
    if (!result.ok) {
      if (tab) tab.close();
      say(result.data.message, true);
      return;
    }
    if (tab) tab.location = result.data.url;
    else window.location = result.data.url;
    say("Agree on Spotify's page, then copy the address you end up on and paste it below.");
  }

  async function finish() {
    const result = await call("POST", "/api/spotify/finish", { address: $("sp-address").value });
    say(result.data.message, !result.ok);
    if (result.ok) $("sp-address").value = "";
  }

  async function findDevices() {
    const result = await call("GET", "/api/spotify/devices");
    if (!result.ok) {
      say(result.data.message, true);
      return;
    }
    const list = $("sp-devices");
    list.textContent = "";
    for (const name of result.data.devices) list.append(new Option(name, name));
    say(result.data.devices.length
      ? `Spotify can see: ${result.data.devices.join(", ")}. Tap the speaker box to pick one.`
      : "Spotify can't see any speakers right now. Play something on the one you want, then try again.");
  }

  async function show() {
    const result = await call("POST", "/api/nowplaying/show");
    say(result.data.message, !result.ok);
  }

  $("sp-form").addEventListener("submit", save);
  $("sp-connect").addEventListener("click", connect);
  $("sp-finish").addEventListener("click", finish);
  $("sp-find").addEventListener("click", findDevices);
  $("sp-show").addEventListener("click", show);
  $("sp-disconnect").addEventListener("click", async () => {
    const result = await call("POST", "/api/spotify/disconnect");
    say(result.data.message, !result.ok);
  });
  fetch("/api/spotify").then((r) => r.json()).then(fill).catch(() => say("Couldn't load the Spotify settings.", true));
})();
