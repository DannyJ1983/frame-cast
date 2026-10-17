// Weather icons shared by the dashboard and the departures board, drawn on a 64x64 grid.
// Static markup only: callers put data into the page as text, never as markup.
// Runs on the 2019 TV's Chromium 63 too.
(function (root) {
  "use strict";

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

  /** An <svg> for a weather icon name, such as "rain"; unknown names get a cloud. */
  function svg(name) {
    return '<svg viewBox="0 0 64 64" aria-hidden="true">' + (ICONS[name] || ICONS.cloud) + "</svg>";
  }

  root.DashboardIcons = { svg: svg };
})(window);
