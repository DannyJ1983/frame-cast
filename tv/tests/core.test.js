// Run with: node --test tv/tests/*.test.js (pytest runs it too)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../js/core.js");

test("normaliseHubUrl adds scheme and default port", () => {
  assert.equal(core.normaliseHubUrl("192.168.1.20"), "http://192.168.1.20:8090");
  assert.equal(core.normaliseHubUrl(" 192.168.1.20:9000/ "), "http://192.168.1.20:9000");
  assert.equal(core.normaliseHubUrl("HTTP://pi.local:8090/api"), "http://pi.local:8090");
  assert.equal(core.normaliseHubUrl("https://hub.example"), "https://hub.example:8090");
  assert.equal(core.normaliseHubUrl(""), "");
});

test("pickHubUrl prefers saved, then configured, then the page's own hub", () => {
  const page = { protocol: "http:", host: "192.168.1.5:8090" };
  assert.equal(core.pickHubUrl("10.0.0.2", "10.0.0.3", page), "http://10.0.0.2:8090");
  assert.equal(core.pickHubUrl("", "10.0.0.3", page), "http://10.0.0.3:8090");
  assert.equal(core.pickHubUrl("", "", page), "http://192.168.1.5:8090");
  assert.equal(core.pickHubUrl("", "", { protocol: "file:", host: "" }), "");
});

test("streamUrl makes relay paths absolute", () => {
  assert.equal(core.streamUrl({ url: "/p/a/b/c/master.m3u8?x=1" }, "http://hub:8090/"), "http://hub:8090/p/a/b/c/master.m3u8?x=1");
  assert.equal(core.streamUrl({ url: "https://cdn/x.m3u8" }, "http://hub:8090"), "https://cdn/x.m3u8");
});

test("formatTime", () => {
  assert.equal(core.formatTime(0), "0:00");
  assert.equal(core.formatTime(65000), "1:05");
  assert.equal(core.formatTime(3723000), "1:02:03");
  assert.equal(core.formatTime(-1), "");
  assert.equal(core.formatTime(NaN), "");
  assert.equal(core.formatTime(undefined), "");
});

test("describePlayerError handles codes, exceptions and unknowns", () => {
  assert.match(core.describePlayerError("PLAYER_ERROR_CONNECTION_FAILED"), /Couldn't connect/);
  assert.match(core.describePlayerError({ name: "PLAYER_ERROR_NOT_SUPPORTED_FORMAT" }), /can't play this video format/);
  assert.match(core.describePlayerError({ name: "Weird", message: "boom" }), /\(boom\)/);
  assert.equal(core.describePlayerError(null), "The TV's player hit an error.");
});

test("keyAction per screen", () => {
  assert.equal(core.keyAction("idle", "Enter"), "settings");
  assert.equal(core.keyAction("idle", "Return"), "exit");
  assert.equal(core.keyAction("playing", "Enter"), "toggle");
  assert.equal(core.keyAction("playing", "MediaPlayPause"), "toggle");
  assert.equal(core.keyAction("playing", "Left"), "seek-back");
  assert.equal(core.keyAction("playing", "MediaFastForward"), "seek-forward");
  assert.equal(core.keyAction("playing", "Return"), "stop");
  assert.equal(core.keyAction("loading", "MediaStop"), "stop");
  assert.equal(core.keyAction("error", "Enter"), "dismiss");
  assert.equal(core.keyAction("settings", "Down"), "move-focus");
  assert.equal(core.keyAction("settings", "Return"), "cancel");
  assert.equal(core.keyAction("idle", "Left"), "");
});

test("keyName uses TV codes then browser fallbacks", () => {
  assert.equal(core.keyName(10009), "Return");
  assert.equal(core.keyName(27), "Return");
  assert.equal(core.keyName(32), "MediaPlayPause");
  assert.equal(core.keyName(999, { MediaPlayPause: 999 }), "MediaPlayPause");
  assert.equal(core.keyName(12345), "");
});
