// Phone page: send links, show what the TV is doing, control playback and keep saved channels.
"use strict";

const $ = (id) => document.getElementById(id);
const STATE_TEXT = {
  idle: "Waiting",
  loading: "Loading…",
  buffering: "Buffering…",
  playing: "Playing",
  paused: "Paused",
  ended: "Finished",
  stopped: "Stopped",
  error: "Couldn't play it",
};

function formatTime(ms) {
  if (ms == null || !isFinite(ms) || ms < 0) return "";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function showMessage(text, isError) {
  const el = $("message");
  el.textContent = text || "";
  el.classList.toggle("error", Boolean(isError));
}

async function api(method, path, body, contentType) {
  const raw = body instanceof Blob;
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": raw ? contentType || body.type : "application/json", Accept: "application/json" },
    body: raw ? body : JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await response.json(); } catch (e) { /* empty reply */ }
  return { ok: response.ok, message: data.message || response.statusText, data };
}

const post = (path, body) => api("POST", path, body);

let current = null; // what's on the TV, for "Save as a channel"
let channels = [];

async function sendLink(url) {
  $("send-button").disabled = true;
  showMessage("Looking for the video…");
  try {
    const result = await post("/api/send", { url });
    showMessage(result.message, !result.ok);
    if (result.ok) $("url").value = "";
  } catch (e) {
    showMessage("Couldn't reach the home server.", true);
  } finally {
    $("send-button").disabled = false;
  }
}

function render(state) {
  const pill = $("tv-pill");
  pill.textContent = state.tv_connected ? "TV app open" : "TV app closed";
  pill.classList.toggle("on", state.tv_connected);

  const tv = state.tv || {};
  current = state.current;
  const showNow = Boolean(current) && !["idle", "stopped"].includes(tv.state || "idle");
  $("now").hidden = !showNow && !(current && state.pending);
  if (current) {
    $("now-title").textContent = current.title;
    let text = STATE_TEXT[tv.state] || tv.state || "";
    if (state.pending && tv.command_id !== current.id) text = "Waiting for the TV app…";
    if (tv.state === "error" && tv.message) text = `${STATE_TEXT.error}: ${tv.message}`;
    const times = current.is_live ? "Live" : [formatTime(tv.position), formatTime(tv.duration)].filter(Boolean).join(" / ");
    if (times && ["playing", "paused", "buffering"].includes(tv.state)) text += ` · ${times}`;
    $("now-state").textContent = text;
    $("now-state").classList.toggle("error", tv.state === "error");
    const pct = tv.duration > 0 && !current.is_live ? Math.min(100, (100 * (tv.position || 0)) / tv.duration) : 0;
    $("now-bar").style.width = `${pct}%`;
    $("toggle-button").textContent = tv.state === "paused" ? "Play" : "Pause";
    $("save-current").hidden = Boolean(current.channel_id);
  }

  const recent = state.recent || [];
  $("recent-section").hidden = recent.length === 0;
  const list = $("recent");
  list.textContent = "";
  for (const item of recent) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.title;
    const small = document.createElement("small");
    small.textContent = item.page_url;
    button.appendChild(small);
    button.addEventListener("click", () => sendLink(item.page_url));
    li.appendChild(button);
    list.appendChild(li);
  }
}

// Saved channels -----------------------------------------------------------------

function logoUrl(channel) {
  return `/api/channels/${encodeURIComponent(channel.id)}/logo?v=${channel.logo_version}`;
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

function host(url) {
  try { return new URL(url).hostname; } catch (e) { return url; }
}

function smallButton(label, onClick, extraClass) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (extraClass) button.className = extraClass;
  button.addEventListener("click", onClick);
  return button;
}

function renderChannels(list) {
  channels = list;
  $("channels-empty").hidden = channels.length > 0;
  const ul = $("channels");
  ul.textContent = "";
  channels.forEach((channel, index) => {
    const li = document.createElement("li");
    let logo;
    if (channel.has_logo) {
      logo = document.createElement("img");
      logo.src = logoUrl(channel);
      logo.alt = "";
    } else {
      logo = document.createElement("div");
      logo.textContent = initials(channel.name);
    }
    logo.className = "channel-logo";
    const text = document.createElement("div");
    text.className = "channel-text";
    const name = document.createElement("b");
    name.textContent = channel.name;
    const small = document.createElement("small");
    small.textContent = host(channel.url);
    text.append(name, small);
    const buttons = document.createElement("div");
    buttons.className = "channel-buttons";
    buttons.append(
      smallButton("Play", () => playChannel(channel)),
      smallButton("Edit", () => openChannelForm(channel), "secondary"),
    );
    const up = smallButton("↑", () => moveChannel(channel, -1), "secondary arrow");
    const down = smallButton("↓", () => moveChannel(channel, 1), "secondary arrow");
    up.disabled = index === 0;
    down.disabled = index === channels.length - 1;
    up.setAttribute("aria-label", `Move ${channel.name} up`);
    down.setAttribute("aria-label", `Move ${channel.name} down`);
    buttons.append(up, down);
    li.append(logo, text, buttons);
    ul.appendChild(li);
  });
}

async function playChannel(channel) {
  showMessage(`Finding ${channel.name}…`);
  const result = await post(`/api/channels/${encodeURIComponent(channel.id)}/play`);
  showMessage(result.message, !result.ok);
}

async function moveChannel(channel, step) {
  const result = await post(`/api/channels/${encodeURIComponent(channel.id)}/move`, { step });
  if (!result.ok) showMessage(result.message, true);
}

function openChannelForm(channel, preset) {
  const form = $("channel-form");
  form.hidden = false;
  $("channel-id").value = channel ? channel.id : "";
  $("channel-name").value = channel ? channel.name : (preset && preset.name) || "";
  $("channel-url").value = channel ? channel.url : (preset && preset.url) || "";
  $("channel-logo").value = "";
  const preview = $("logo-preview");
  preview.hidden = !(channel && channel.has_logo);
  if (channel && channel.has_logo) preview.src = logoUrl(channel);
  $("remove-logo").hidden = !(channel && channel.has_logo);
  $("channel-delete").hidden = !channel;
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  $("channel-name").focus();
}

function closeChannelForm() {
  $("channel-form").hidden = true;
}

/** Shrink a picture to at most 400 pixels across before uploading; logos don't need more. */
async function shrinkImage(file, max = 400) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    });
    const scale = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    return blob || file;
  } catch (e) {
    return file; // let the hub judge it
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function saveChannel(event) {
  event.preventDefault();
  const id = $("channel-id").value;
  const body = { name: $("channel-name").value, url: $("channel-url").value };
  const result = id
    ? await api("PATCH", `/api/channels/${encodeURIComponent(id)}`, body)
    : await post("/api/channels", body);
  if (!result.ok) {
    showMessage(result.message, true);
    return;
  }
  const file = $("channel-logo").files[0];
  if (file) {
    const logo = await shrinkImage(file);
    const upload = await api("PUT", `/api/channels/${encodeURIComponent(result.data.id)}/logo`, logo);
    if (!upload.ok) {
      showMessage(`Saved ${result.data.name}, but the logo didn't work: ${upload.message}`, true);
      closeChannelForm();
      return;
    }
  }
  showMessage(`Saved ${result.data.name}. It's on the TV's channel list.`);
  closeChannelForm();
}

async function deleteChannel() {
  const id = $("channel-id").value;
  const channel = channels.find((c) => c.id === id);
  if (!channel || !window.confirm(`Delete ${channel.name}?`)) return;
  const result = await api("DELETE", `/api/channels/${encodeURIComponent(id)}`);
  if (!result.ok) showMessage(result.message, true);
  else showMessage(`Deleted ${channel.name}.`);
  closeChannelForm();
}

async function removeLogo() {
  const id = $("channel-id").value;
  const result = await api("DELETE", `/api/channels/${encodeURIComponent(id)}/logo`);
  if (!result.ok) showMessage(result.message, true);
  $("logo-preview").hidden = true;
  $("remove-logo").hidden = true;
}

function connect() {
  const events = new EventSource("/api/events");
  events.addEventListener("state", (e) => render(JSON.parse(e.data)));
  events.addEventListener("channels", (e) => renderChannels(JSON.parse(e.data).channels || []));
  events.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    showMessage(m.text, m.level === "error");
  });
  events.onerror = () => {
    $("tv-pill").textContent = "Reconnecting…";
    $("tv-pill").classList.remove("on");
  };
}

function init() {
  const origin = window.location.origin;
  document.querySelectorAll(".hub-send").forEach((el) => { el.textContent = `${origin}/api/send`; });
  document.querySelectorAll(".hub-send-text").forEach((el) => { el.textContent = `${origin}/api/send?reply=text`; });

  const params = new URLSearchParams(window.location.search);
  if (params.get("url")) $("url").value = params.get("url");

  $("send-form").addEventListener("submit", (e) => {
    e.preventDefault();
    sendLink($("url").value.trim());
  });
  $("test-button").addEventListener("click", async () => {
    showMessage("Sending a test video…");
    const result = await post("/api/test");
    showMessage(result.message, !result.ok);
  });
  $("add-channel").addEventListener("click", () => openChannelForm(null));
  $("save-current").addEventListener("click", () => {
    if (current) openChannelForm(null, { name: current.title, url: current.page_url });
  });
  $("channel-form").addEventListener("submit", saveChannel);
  $("channel-cancel").addEventListener("click", closeChannelForm);
  $("channel-delete").addEventListener("click", deleteChannel);
  $("remove-logo").addEventListener("click", removeLogo);
  $("channel-logo").addEventListener("change", () => {
    const file = $("channel-logo").files[0];
    if (!file) return;
    const preview = $("logo-preview");
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });
  document.querySelectorAll(".controls button").forEach((button) => {
    button.addEventListener("click", async () => {
      const body = { action: button.dataset.action };
      if (button.dataset.seconds) body.seconds = Number(button.dataset.seconds);
      const result = await post("/api/control", body);
      if (!result.ok) showMessage(result.message, true);
    });
  });
  connect();
}

init();
