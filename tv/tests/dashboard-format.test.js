// The dashboard page's formatting (framecast/dashboard/page/format.js), which the TV shows.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const F = require("../../framecast/dashboard/page/format.js");

// Local times, so the tests pass in any time zone.
const now = new Date(2026, 9, 16, 14, 20);

test("clock, date and temperatures", () => {
  assert.equal(F.clockText(new Date(2026, 9, 16, 9, 5)), "09:05");
  assert.equal(F.dateText(now), "Friday 16 October");
  assert.equal(F.tempText(13.6), "14°");
  assert.equal(F.tempText(-0.4), "0°");
  assert.equal(F.tempText(null), "–");
});

test("how long ago a headline was published", () => {
  const minutesAgo = (m) => new Date(now.getTime() - m * 60000).toISOString();
  assert.equal(F.ago(minutesAgo(1), now), "Just now");
  assert.equal(F.ago(minutesAgo(12), now), "12 min ago");
  assert.equal(F.ago(minutesAgo(185), now), "3 hr ago");
  assert.equal(F.ago(minutesAgo(60 * 30), now), "Yesterday");
  assert.equal(F.ago(minutesAgo(60 * 80), now), "3 days ago");
  assert.equal(F.ago(null, now), "");
  assert.equal(F.ago("not a date", now), "");
});

test("kick-off times", () => {
  assert.equal(F.kickoffText(new Date(2026, 9, 16, 19, 45).toISOString(), now), "19:45");
  assert.equal(F.kickoffText(new Date(2026, 9, 17, 15, 0).toISOString(), now), "Tomorrow 15:00");
  assert.equal(F.kickoffText(new Date(2026, 9, 18, 12, 30).toISOString(), now), "Sun 12:30");
  assert.equal(F.kickoffText(null, now), "");
});

test("ticker entries for live, finished, postponed and upcoming matches", () => {
  const base = { home: "Arsenal", away: "Chelsea", kickoff: null };
  assert.deepEqual(F.matchParts(Object.assign({}, base, { state: "in", detail: "67'", home_score: "2", away_score: "1" }), now),
    { lead: "67'", home: "Arsenal", away: "Chelsea", score: "2–1", live: true });
  assert.equal(F.matchParts(Object.assign({}, base, { state: "post", detail: "", home_score: "0", away_score: "0" }), now).lead, "FT");
  const postponed = F.matchParts(Object.assign({}, base, { state: "post", detail: "Postponed", home_score: "", away_score: "" }), now);
  assert.equal(postponed.score, "v");
  assert.equal(postponed.lead, "Postponed");
  const later = Object.assign({}, base, { state: "pre", detail: "", home_score: "", away_score: "", kickoff: new Date(2026, 9, 16, 20, 0).toISOString() });
  assert.equal(F.matchParts(later, now).lead, "20:00");
});

test("traffic line and setup hint", () => {
  assert.equal(F.trafficText({ delay_minutes: 7, state: "slow", miles: 9.4 }), "7 min slower than usual · 9.4 miles");
  assert.equal(F.trafficText({ delay_minutes: 2, state: "ok", miles: 0 }), "Traffic as usual");
  assert.equal(F.needsSetup({ setup: { weather: false } }), true);
  assert.equal(F.needsSetup({ setup: { weather: true } }), false);
  assert.equal(F.needsSetup(null), true);
});

test("bus times, details and badge colours", () => {
  assert.deepEqual(F.busWhen({ live: true, minutes: 5, time: "10:10" }), { text: "5 min", live: true });
  assert.deepEqual(F.busWhen({ live: true, minutes: 0, time: "10:10" }), { text: "Due", live: true });
  assert.deepEqual(F.busWhen({ live: false, minutes: null, time: "10:20" }), { text: "10:20", live: false });
  assert.equal(F.busDetail({ live: true, late: 3, time: "10:10" }), "Due 10:10, 3 min late");
  assert.equal(F.busDetail({ live: true, late: -2, time: "10:10" }), "Due 10:10, 2 min early");
  assert.equal(F.busDetail({ live: true, late: 1, time: "10:10" }), "");
  assert.equal(F.busDetail({ live: false, late: null, time: "10:10" }), "");
  assert.equal(F.routeColour("7"), F.routeColour("7"));
  assert.match(F.routeColour("N7"), /^#[0-9a-f]{6}$/);
});
