// Phone page: send links, show what the TV is doing, and control playback.
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

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await response.json(); } catch (e) { /* empty reply */ }
  return { ok: response.ok, message: data.message || response.statusText };
}

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
  const current = state.current;
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

function connect() {
  const events = new EventSource("/api/events");
  events.addEventListener("state", (e) => render(JSON.parse(e.data)));
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
