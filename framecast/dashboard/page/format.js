// Pure formatting for the dashboard page: no DOM, so Node can test it.
// Runs on the 2019 TV's Chromium 63: no optional chaining, no ?? and no ES modules.
(function (root, factory) {
  var format = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = format;
  else root.DashboardFormat = format;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  /** "14:05" in the device's own time. */
  function clockText(date) {
    return pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  /** "Friday 16 October". */
  function dateText(date) {
    return DAYS[date.getDay()] + " " + date.getDate() + " " + MONTHS[date.getMonth()];
  }

  /** "14°", or a dash when there's no number. */
  function tempText(value) {
    return typeof value === "number" && isFinite(value) ? Math.round(value) + "°" : "–";
  }

  function parse(iso) {
    if (!iso) return null;
    var date = new Date(iso);
    return isNaN(date.getTime()) ? null : date;
  }

  /** How long ago a headline was published: "Just now", "12 min ago", "3 hr ago", "2 days ago"; "" if unknown. */
  function ago(iso, now) {
    var date = parse(iso);
    if (!date) return "";
    var minutes = Math.floor((now.getTime() - date.getTime()) / 60000);
    if (minutes < 2) return "Just now";
    if (minutes < 60) return minutes + " min ago";
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + " hr ago";
    var days = Math.floor(hours / 24);
    return days === 1 ? "Yesterday" : days + " days ago";
  }

  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  /** A kick-off time: "15:00" today, "Tomorrow 15:00", or "Sat 15:00". */
  function kickoffText(iso, now) {
    var date = parse(iso);
    if (!date) return "";
    var time = clockText(date);
    if (sameDay(date, now)) return time;
    var tomorrow = new Date(now.getTime() + 86400000);
    if (sameDay(date, tomorrow)) return "Tomorrow " + time;
    return DAYS[date.getDay()].slice(0, 3) + " " + time;
  }

  /** What the ticker shows for a match: { lead, home, away, score } where score is "2–1" or "v". */
  function matchParts(match, now) {
    var played = match.home_score !== "" && match.away_score !== "";
    var lead;
    if (match.state === "pre") lead = kickoffText(match.kickoff, now);
    else lead = match.detail || (match.state === "post" ? "FT" : "Live");
    return {
      lead: lead,
      home: match.home,
      away: match.away,
      score: played ? match.home_score + "–" + match.away_score : "v",
      live: match.state === "in",
    };
  }

  /** The line under the drive time. */
  function trafficText(route) {
    var miles = route.miles ? " · " + route.miles + " miles" : "";
    if (route.delay_minutes > 0 && route.state !== "ok") {
      return route.delay_minutes + " min slower than usual" + miles;
    }
    return "Traffic as usual" + miles;
  }

  /** Whether the snapshot's setup leaves the location unset, so the page should explain how to set it up. */
  function needsSetup(snapshot) {
    return !(snapshot && snapshot.setup && snapshot.setup.weather);
  }

  return {
    clockText: clockText,
    dateText: dateText,
    tempText: tempText,
    ago: ago,
    kickoffText: kickoffText,
    matchParts: matchParts,
    trafficText: trafficText,
    needsSetup: needsSetup,
  };
});
