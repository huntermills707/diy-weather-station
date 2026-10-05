"use strict";
// Weather station dashboard (docs/dashboard.md). Reads the server's read API
// (docs/read-api.md). Plain JavaScript and SVG: no build step, no libraries.

const PARAMS = new URLSearchParams(location.search);
const STATION = PARAMS.get("station") || "station-1";
const RANGES = { "24h": 24 * 3600e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };
const CURRENT_EVERY_MS = 60e3;
const HISTORY_EVERY_MS = 5 * 60e3;
// The NWS heat index only means something in warm weather (80 °F and up).
const HEAT_INDEX_FROM_C = 26.7;
// Same calm limit as the server's wind rose (docs/read-api.md).
const CALM_KMH = 2;
// The API is metric; the dashboard converts temperature and wind speed for
// display. Rain stays in mm and pressure in hPa.
const UNIT_SYSTEMS = {
  us: {
    temp: { unit: "°F", convert: (c) => (c * 9) / 5 + 32 },
    speed: { unit: "mph", convert: (kmh) => kmh / 1.609344 },
  },
  metric: {
    temp: { unit: "°C", convert: (c) => c },
    speed: { unit: "km/h", convert: (kmh) => kmh },
  },
};
const SVG_NS = "http://www.w3.org/2000/svg";

function savedUnits() {
  try {
    const saved = localStorage.getItem("units");
    if (UNIT_SYSTEMS[saved]) return saved;
  } catch {
    // Storage blocked: fall back to the browser's locale.
  }
  return navigator.language === "en-US" ? "us" : "metric";
}

const state = {
  units: savedUnits(),
  range: RANGES[PARAMS.get("range")] ? PARAMS.get("range") : "24h",
  current: null, series: null, rose: null, historyRequest: 0 };

// ---- Formatting ------------------------------------------------------------

const fmtTime = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const fmtDayTime = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});
const fmtDateTime = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const fmtDate = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const fmtWeekday = new Intl.DateTimeFormat(undefined, { weekday: "short" });
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

function fixed(value, digits) {
  return value == null ? "—" : value.toFixed(digits);
}

// Convert a metric value of a quantity ("temp" or "speed") to the chosen units.
function convert(quantity, value) {
  return value == null ? null : UNIT_SYSTEMS[state.units][quantity].convert(value);
}

function unitOf(quantity) {
  return UNIT_SYSTEMS[state.units][quantity].unit;
}

function duration(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const minutes = seconds / 60;
  if (minutes < 90) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "style") Object.assign(node.style, value);
    else node.setAttribute(name, value);
  }
  if (text != null) node.textContent = text;
  return node;
}

function plural(n, word) {
  return n === 1 ? word : `${word}s`;
}

function field(name) {
  return document.querySelector(`[data-field="${name}"]`);
}

// A big number with a unit, or a dash with the reason it is unavailable.
function setValue(name, value, digits, unit) {
  const node = field(name);
  node.classList.toggle("unavailable", value == null);
  node.replaceChildren(value == null ? "—" : value.toFixed(digits));
  if (value != null) {
    const small = document.createElement("small");
    small.textContent = unit;
    node.append(small);
  }
}

function setText(name, text) {
  field(name).textContent = text;
}

// ---- Data ------------------------------------------------------------------

async function getJson(path, params = {}) {
  const query = new URLSearchParams({ station: STATION, ...params });
  const response = await fetch(`${path}?${query}`, { cache: "no-store" });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail;
    } catch {
      // Keep the status text.
    }
    throw new Error(`${response.status} ${typeof detail === "string" ? detail : ""}`.trim());
  }
  return response.json();
}

async function loadCurrent() {
  try {
    state.current = await getJson("/api/current");
    renderCurrent(state.current);
  } catch (error) {
    showOffline(error);
  }
}

async function loadHistory() {
  const request = ++state.historyRequest;
  const end = new Date();
  const start = new Date(end - RANGES[state.range]);
  const params = { start: start.toISOString(), end: end.toISOString() };
  try {
    const [series, rose] = await Promise.all([
      getJson("/api/series", params),
      getJson("/api/wind", params),
    ]);
    // A newer range selection may have finished first.
    if (request !== state.historyRequest) return;
    state.series = series;
    state.rose = rose;
    renderHistory();
  } catch (error) {
    showOffline(error);
  }
}

function showOffline(error) {
  const status = document.getElementById("status");
  status.className = "status error";
  status.textContent = "Server unreachable";
  const banner = document.getElementById("banner");
  banner.hidden = false;
  banner.className = "banner error";
  banner.textContent =
    `Can't reach the weather station server (${error.message}). ` +
    "Showing the last data received; retrying every minute.";
}

// ---- Current conditions ----------------------------------------------------

function renderCurrent(data) {
  const reading = data.reading;
  const health = data.health;
  const status = document.getElementById("status");
  const banner = document.getElementById("banner");
  document.body.classList.toggle("stale-data", Boolean(health && health.stale));
  banner.hidden = true;
  banner.className = "banner";

  if (!reading) {
    status.className = "status stale";
    status.textContent = "No readings yet";
    banner.hidden = false;
    banner.textContent = `The server has no readings from ${STATION} yet.`;
    for (const name of ["temp", "humidity", "pressure", "wind", "rain"]) {
      setValue(name, null);
      setText(`${name}-detail`, "");
    }
    field("wind-arrow").style.display = "none";
    document.getElementById("health").replaceChildren();
    return;
  }

  const received = new Date(reading.received_at);
  if (health.stale) {
    status.className = "status stale";
    status.textContent = `No new reading for ${duration(health.age_s)}`;
    banner.hidden = false;
    banner.textContent =
      `No reading since ${fmtDayTime.format(received)}. The station or its WiFi may be down; ` +
      "the values below are from that last reading. The station keeps up to 24 hours of " +
      "readings while offline and sends them when it reconnects.";
  } else {
    status.className = "status ok";
    status.textContent = `Updated ${duration(health.age_s)} ago · ${fmtTime.format(received)}`;
  }

  renderConditions(data);
  renderHealth(data);
}

// Why a field of the latest reading is suspect (docs/data-quality.md), or null.
function suspectReason(reading, prefix) {
  const flag = reading.quality.find((f) => f.startsWith(prefix));
  if (!flag) return null;
  return flag.endsWith("_stuck") ? "Suspect: unchanged for 2 h" : "Suspect: outside plausible range";
}

// Shows a suspect warning in place of a card's detail line; returns whether it did.
function markSuspect(name, reason) {
  field(`${name}-detail`).classList.toggle("warn", Boolean(reason));
  if (reason) setText(`${name}-detail`, reason);
  return Boolean(reason);
}

function renderConditions(data) {
  const r = data.reading;
  const d = data.derived;
  const sensorReason = {
    implausible: "Sensor reading out of range",
    error: "Sensor not responding",
  }[r.bme280];

  const tempUnit = unitOf("temp");
  setValue("temp", convert("temp", r.temp_c), 1, tempUnit);
  if (sensorReason) {
    setText("temp-detail", sensorReason);
  } else {
    const parts = [];
    if (r.temp_c >= HEAT_INDEX_FROM_C && d.heat_index_c != null) {
      parts.push(`Heat index ${fixed(convert("temp", d.heat_index_c), 1)} ${tempUnit}`);
    }
    parts.push(`Dew point ${fixed(convert("temp", d.dew_point_c), 1)} ${tempUnit}`);
    setText("temp-detail", parts.join(" · "));
  }

  setValue("humidity", r.rh_pct, 0, "%");
  setText("humidity-detail", sensorReason || "Relative humidity");

  if (d.sea_level_hpa != null) {
    setValue("pressure", d.sea_level_hpa, 1, "hPa");
    setText("pressure-detail", `Sea level · station ${fixed(r.press_hpa, 1)} hPa`);
  } else {
    setValue("pressure", r.press_hpa, 1, "hPa");
    setText(
      "pressure-detail",
      sensorReason ||
        (d.altitude_m == null ? "Station pressure (altitude not set)" : "Station pressure"),
    );
  }

  const speedUnit = unitOf("speed");
  setValue("wind", convert("speed", r.wind_avg_kmh), 1, speedUnit);
  const arrow = field("wind-arrow");
  const parts = [`Gust ${fixed(convert("speed", r.wind_peak_kmh), 1)} ${speedUnit}`];
  if (r.wind_avg_kmh < CALM_KMH) {
    // In still air the vane just keeps its last position.
    parts.push("calm");
    arrow.style.display = "none";
  } else if (r.wind_dir_deg == null) {
    parts.push("direction unknown (vane)");
    arrow.style.display = "none";
  } else {
    parts.push(`from ${r.wind_dir_label} (${Math.round(r.wind_dir_deg)}°)`);
    arrow.style.display = "";
    // The arrow points into the wind, like the vane.
    arrow.setAttribute("transform", `rotate(${r.wind_dir_deg})`);
  }
  setText("wind-detail", parts.join(" · "));

  // Flagged values stay visible: they are what the station sent.
  markSuspect("temp", suspectReason(r, "temp_"));
  markSuspect("humidity", suspectReason(r, "rh_"));
  markSuspect("pressure", suspectReason(r, "press_"));
  markSuspect("wind", suspectReason(r, "wind_") || suspectReason(r, "gust_"));

  setRain(data);
}

function setRain(data) {
  const rain = data.rain;
  setValue("rain", rain.today_mm, 1, "mm");
  // Non-breaking spaces keep each total on one line when the text wraps.
  let detail = [
    ["Last hour", rain.last_hour_mm],
    ["24 h", rain.last_24h_mm],
    ["this month", rain.month_mm],
  ]
    .map(([label, mm]) => `${label.replaceAll(" ", "\u00a0")}\u00a0${fixed(mm, 1)}\u00a0mm`)
    .join(" · ");
  if (data.timezone !== browserZone) detail += ` (days in ${data.timezone})`;
  setText("rain-detail", detail);
}

function renderHealth(data) {
  const r = data.reading;
  const h = data.health;
  const share = h.readings_24h / h.expected_24h;
  const reboots = Math.max(0, h.boots_24h - 1);
  let signal = "—";
  let signalClass = "";
  if (h.rssi_dbm != null) {
    const quality = h.rssi_dbm >= -60 ? "good" : h.rssi_dbm >= -70 ? "fair" : "weak";
    signal = `${h.rssi_dbm} dBm (${quality})`;
    if (quality === "weak") signalClass = "warn";
  }
  const sensor = { ok: ["OK", ""], implausible: ["Out of range", "warn"], error: ["Not responding", "bad"] };
  const items = [
    [
      "Last reading",
      `${fmtDayTime.format(new Date(r.received_at))} (${duration(h.age_s)} ago)`,
      h.stale ? "warn" : "",
    ],
    [
      "Readings, last 24 h",
      `${h.readings_24h} of ${h.expected_24h} (${Math.min(100, share * 100).toFixed(0)}%)`,
      share < 0.95 ? "warn" : "",
    ],
    ["Reboots, last 24 h", String(reboots), reboots > 0 ? "warn" : ""],
    ["Uptime", duration(h.uptime_s), ""],
    [
      "Station clock",
      h.clock_synced
        ? `NTP synced (received ${fixed(h.clock_offset_s, 1)} s after)`
        : "Not synced: times are server receive times",
      h.clock_synced ? "" : "warn",
    ],
    ["WiFi signal", signal, signalClass],
    ["BME280 sensor", ...sensor[h.bme280]],
    [
      "Data quality, last 24 h",
      h.flagged_24h ? `${h.flagged_24h} ${plural(h.flagged_24h, "reading")} flagged` : "None flagged",
      h.flagged_24h ? "warn" : "",
    ],
  ];
  // Reboot and queue telemetry: absent from firmware before M4.
  if (r.boot_count != null) {
    const crash = ["task_watchdog", "int_watchdog", "watchdog", "panic", "brownout"];
    items.push([
      "Last reboot",
      `#${r.boot_count} (${r.reset_reason.replaceAll("_", " ")})`,
      crash.includes(r.reset_reason) ? "warn" : "",
    ]);
  }
  if (r.queue_dropped != null) {
    items.push([
      "Upload queue",
      r.queue_dropped
        ? `${r.queue_dropped} ${plural(r.queue_dropped, "reading")} dropped (queue full)`
        : "Nothing dropped",
      r.queue_dropped ? "warn" : "",
    ]);
  }
  items.push(["Last reading ID", r.reading_id, ""]);
  const list = document.getElementById("health");
  list.replaceChildren(
    ...items.map(([label, value, cls]) => {
      const row = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      if (cls) dd.className = cls;
      row.append(dt, dd);
      return row;
    }),
  );
}

// ---- History charts --------------------------------------------------------

const CHARTS = {
  temp: {
    lines: [{ key: "temp_c", color: "var(--temp)", label: "Average" }],
    band: { min: "temp_min_c", max: "temp_max_c", color: "var(--band)", label: "Min–max" },
    quantity: "temp",
    digits: 1,
  },
  humidity: {
    lines: [{ key: "rh_pct", color: "var(--humidity)", label: "Humidity" }],
    unit: "%",
    digits: 0,
  },
  pressure: {
    lines: [{ key: "press_hpa", color: "var(--pressure)", label: "Pressure" }],
    unit: "hPa",
    digits: 1,
  },
  wind: {
    lines: [
      { key: "wind_avg_kmh", color: "var(--wind)", label: "Average" },
      { key: "wind_peak_kmh", color: "var(--gust)", label: "Gust" },
    ],
    quantity: "speed",
    digits: 1,
    fromZero: true,
    legend: true,
  },
  rain: {
    bars: { key: "rain_mm", color: "var(--rain)", label: "Rain" },
    unit: "mm",
    digits: 2,
    fromZero: true,
  },
};

function renderHistory() {
  const series = state.series;
  if (!series) return;
  const minutes = series.bucket_s / 60;
  document.getElementById("history-note").textContent =
    minutes <= 5
      ? "Each point is one five-minute reading. Breaks in a line are missing readings."
      : `Each point averages ${minutes >= 60 ? `${minutes / 60} h` : `${minutes} min`} of readings ` +
        "(highest gust, total rain). Breaks in a line are periods without readings.";
  const points = series.points.map((p) => {
    const point = { ...p, t: Date.parse(p.time) };
    for (const key of ["temp_c", "temp_min_c", "temp_max_c"]) point[key] = convert("temp", p[key]);
    for (const key of ["wind_avg_kmh", "wind_peak_kmh"]) point[key] = convert("speed", p[key]);
    return point;
  });
  const start = Date.parse(series.start);
  const end = Date.parse(series.end);
  for (const [name, spec] of Object.entries(CHARTS)) {
    const plot = document.querySelector(`[data-chart="${name}"] .plot`);
    drawChart(plot, spec, points, start, end, series.bucket_s);
  }
  drawRose(document.querySelector('[data-chart="rose"] .plot'), state.rose);
}

function niceStep(rough) {
  const power = 10 ** Math.floor(Math.log10(rough));
  for (const m of [1, 2, 5, 10]) if (m * power >= rough) return m * power;
  return 10 * power;
}

function timeTicks(start, end) {
  const ticks = [];
  const span = end - start;
  const t = new Date(start);
  if (span <= 2 * 86400e3) {
    t.setMinutes(0, 0, 0);
    while (t < start || t.getHours() % 6) t.setHours(t.getHours() + 1);
    for (; t <= end; t.setHours(t.getHours() + 6)) {
      ticks.push([t.getTime(), fmtTime.format(t)]);
    }
  } else {
    const every = span <= 10 * 86400e3 ? 1 : 7;
    t.setHours(24, 0, 0, 0);
    for (let i = 0; t <= end; i++, t.setDate(t.getDate() + 1)) {
      if (i % every === 0) {
        ticks.push([t.getTime(), (every === 1 ? fmtWeekday : fmtDate).format(t)]);
      }
    }
  }
  return ticks;
}

// Split points into runs of non-null values; a null (gap marker or missing
// sensor value) ends a run.
function runs(points, key) {
  const result = [];
  let run = [];
  for (const p of points) {
    if (p[key] == null) {
      if (run.length) result.push(run);
      run = [];
    } else {
      run.push(p);
    }
  }
  if (run.length) result.push(run);
  return result;
}

function emptyMessage(plot, text) {
  const note = document.createElement("div");
  note.className = "empty";
  note.textContent = text;
  plot.append(note);
}

function drawChart(plot, spec, points, start, end, bucketS) {
  plot.replaceChildren();
  const legendOld = plot.parentElement.querySelector(".legend");
  if (legendOld) legendOld.remove();

  const keys = spec.bars ? [spec.bars.key] : spec.lines.map((l) => l.key);
  const showBand = spec.band && bucketS > 300;
  if (showBand) keys.push(spec.band.min, spec.band.max);
  const values = points.flatMap((p) => keys.map((k) => p[k])).filter((v) => v != null);
  if (!values.length) {
    emptyMessage(plot, "No data in this period");
    return;
  }

  const width = plot.clientWidth;
  const height = plot.clientHeight;
  const m = { left: 42, right: 8, top: 8, bottom: 22 };
  const w = width - m.left - m.right;
  const h = height - m.top - m.bottom;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (spec.fromZero) lo = 0;
  if (hi - lo < 1e-9) {
    hi += 1;
    if (!spec.fromZero) lo -= 1;
  }
  const step = niceStep((hi - lo) / 4);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const x = (t) => m.left + ((t - start) / (end - start)) * w;
  const y = (v) => m.top + h - ((v - lo) / (hi - lo)) * h;

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.setAttribute("aria-label", `${plot.parentElement.querySelector("figcaption").textContent} chart`);
  const axis = el("g", { class: "axis" });
  const stepDigits = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
  for (let v = lo; v <= hi + step / 2; v += step) {
    axis.append(el("line", { x1: m.left, x2: m.left + w, y1: y(v), y2: y(v) }));
    axis.append(
      el("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end" }, v.toFixed(stepDigits)),
    );
  }
  for (const [t, label] of timeTicks(start, end)) {
    axis.append(el("line", { x1: x(t), x2: x(t), y1: m.top, y2: m.top + h }));
    axis.append(el("text", { x: x(t), y: height - 6, "text-anchor": "middle" }, label));
  }
  svg.append(axis);

  if (showBand) {
    for (const run of runs(points, spec.band.max)) {
      const top = run.map((p) => `${x(p.t)},${y(p[spec.band.max])}`);
      const bottom = [...run].reverse().map((p) => `${x(p.t)},${y(p[spec.band.min])}`);
      svg.append(el("polygon", { points: [...top, ...bottom].join(" "), style: { fill: spec.band.color } }));
    }
  }

  if (spec.bars) {
    const barWidth = Math.max(1.5, (bucketS * 1000 * w) / (end - start) - 1);
    let total = 0;
    for (const p of points) {
      const v = p[spec.bars.key];
      if (!v) continue;
      total += v;
      svg.append(
        el("rect", {
          x: x(p.t) - barWidth / 2,
          y: y(v),
          width: barWidth,
          height: y(0) - y(v),
          style: { fill: spec.bars.color },
        }),
      );
    }
    if (total === 0) emptyMessage(plot, "No rain in this period");
  } else {
    for (const line of spec.lines) {
      for (const run of runs(points, line.key)) {
        const style = { fill: "none", stroke: line.color, strokeWidth: "2", strokeLinejoin: "round" };
        if (run.length === 1) {
          const p = run[0];
          svg.append(el("circle", { cx: x(p.t), cy: y(p[line.key]), r: 2, style: { fill: line.color } }));
        } else {
          const d = run.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p[line.key]).toFixed(1)}`);
          svg.append(el("path", { d: d.join(""), style }));
        }
      }
    }
  }

  const cursor = el("line", { class: "cursor", y1: m.top, y2: m.top + h, visibility: "hidden" });
  svg.append(cursor);
  plot.append(svg);
  attachTooltip(plot, svg, cursor, spec, points.filter((p) => p.n > 0), x, bucketS);

  const legendItems = [];
  if (spec.legend) legendItems.push(...spec.lines);
  if (showBand) legendItems.push(spec.lines[0], spec.band);
  if (legendItems.length) {
    const legend = document.createElement("ul");
    legend.className = "legend";
    for (const item of legendItems) {
      const li = document.createElement("li");
      const swatch = document.createElement("i");
      swatch.style.background = item.color;
      li.append(swatch, item.label);
      legend.append(li);
    }
    plot.after(legend);
  }
}

function attachTooltip(plot, svg, cursor, spec, points, x, bucketS) {
  const tooltip = document.getElementById("tooltip");
  if (!points.length) return;
  const items = spec.bars ? [spec.bars] : [...spec.lines];
  if (spec.band && bucketS > 300) {
    items.push({ key: spec.band.min, label: "Min" }, { key: spec.band.max, label: "Max" });
  }
  const show = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * svg.viewBox.baseVal.width;
    let best = points[0];
    for (const p of points) if (Math.abs(x(p.t) - px) < Math.abs(x(best.t) - px)) best = p;
    cursor.setAttribute("x1", x(best.t));
    cursor.setAttribute("x2", x(best.t));
    cursor.setAttribute("visibility", "visible");
    const when = new Date(best.t);
    const lines = [bucketS > 300 ? `${fmtDateTime.format(when)} (avg of ${best.n})` : fmtDateTime.format(when)];
    const unit = spec.quantity ? unitOf(spec.quantity) : spec.unit;
    for (const item of items) lines.push(`${item.label}: ${fixed(best[item.key], spec.digits)} ${unit}`);
    if (best.flagged) lines.push(`${best.flagged} flagged ${plural(best.flagged, "reading")} left out`);
    tooltip.textContent = lines.join("\n");
    tooltip.hidden = false;
    const left = Math.min(event.clientX + 12, window.innerWidth - tooltip.offsetWidth - 8);
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, event.clientY - tooltip.offsetHeight - 12)}px`;
  };
  const hide = () => {
    tooltip.hidden = true;
    cursor.setAttribute("visibility", "hidden");
  };
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("pointercancel", hide);
}

// ---- Wind rose -------------------------------------------------------------

const ROSE_COLORS = ["var(--rose-1)", "var(--rose-2)", "var(--rose-3)", "var(--rose-4)"];

function polar(r, deg) {
  const a = (deg * Math.PI) / 180;
  return `${(r * Math.sin(a)).toFixed(2)},${(-r * Math.cos(a)).toFixed(2)}`;
}

function wedge(r0, r1, a0, a1) {
  if (r0 === 0) return `M0,0 L${polar(r1, a0)} A${r1},${r1} 0 0 1 ${polar(r1, a1)} Z`;
  return (
    `M${polar(r0, a0)} L${polar(r1, a0)} A${r1},${r1} 0 0 1 ${polar(r1, a1)} ` +
    `L${polar(r0, a1)} A${r0},${r0} 0 0 0 ${polar(r0, a0)} Z`
  );
}

function drawRose(plot, rose) {
  plot.replaceChildren();
  const figure = plot.parentElement;
  const old = figure.querySelector(".legend");
  if (old) old.remove();
  const detail = document.getElementById("rose-detail");
  const pct = (n) => (rose.total ? `${Math.round((100 * n) / rose.total)}%` : "0%");
  detail.textContent =
    `${rose.total} readings · calm (below ${speedText(rose.calm_below_kmh)}) ${rose.calm} ` +
    `(${pct(rose.calm)})` +
    ` · direction unknown ${rose.unknown} (${pct(rose.unknown)})` +
    (rose.flagged ? ` · flagged ${rose.flagged} (${pct(rose.flagged)})` : "");

  const totals = rose.sectors.map((s) => s.counts.reduce((a, b) => a + b, 0));
  const most = Math.max(...totals);
  if (most === 0) {
    emptyMessage(
      plot,
      rose.total ? "All readings in this period were calm or had no direction" : "No data in this period",
    );
    return;
  }

  const size = Math.min(plot.clientWidth, plot.clientHeight);
  const radius = size / 2 - 20;
  const svg = el("svg", {
    viewBox: `${-plot.clientWidth / 2} ${-plot.clientHeight / 2} ${plot.clientWidth} ${plot.clientHeight}`,
    role: "img",
    "aria-label": "Wind rose",
  });
  const axis = el("g", { class: "axis" });
  for (const share of [0.5, 1]) {
    axis.append(el("circle", { r: radius * share, style: { fill: "none", stroke: "var(--grid)" } }));
    // Ring labels sit on the north-east diagonal, clear of the N label.
    const [lx, ly] = polar(radius * share, 45).split(",");
    axis.append(
      el("text", { x: Number(lx) + 3, y: ly }, `${Math.round((100 * most * share) / rose.total)}%`),
    );
  }
  for (const [label, deg] of [["N", 0], ["E", 90], ["S", 180], ["W", 270]]) {
    const [px, py] = polar(radius + 12, deg).split(",");
    axis.append(el("text", { x: px, y: Number(py) + 4, "text-anchor": "middle" }, label));
  }
  svg.append(axis);

  rose.sectors.forEach((sector, i) => {
    let cumulative = 0;
    const a0 = sector.direction_deg - 10;
    const a1 = sector.direction_deg + 10;
    sector.counts.forEach((count, cls) => {
      if (!count) return;
      const r0 = (radius * cumulative) / most;
      cumulative += count;
      const r1 = (radius * cumulative) / most;
      const path = el("path", { d: wedge(r0, r1, a0, a1), style: { fill: ROSE_COLORS[cls] } });
      const title = `${sector.label}, ${speedLabel(rose, cls)}: ${count} readings`;
      path.append(el("title", {}, `${title} (${sector.label} in all: ${pct(totals[i])})`));
      svg.append(path);
    });
  });
  plot.append(svg);

  const legend = document.createElement("ul");
  legend.className = "legend";
  rose.speed_classes_kmh.forEach((_, cls) => {
    const li = document.createElement("li");
    const swatch = document.createElement("i");
    swatch.style.background = ROSE_COLORS[cls];
    li.append(swatch, speedLabel(rose, cls));
    legend.append(li);
  });
  plot.after(legend);
}

function speedLabel(rose, cls) {
  const edges = rose.speed_classes_kmh;
  const low = speedText(edges[cls], false);
  return cls + 1 < edges.length ? `${low}–${speedText(edges[cls + 1])}` : `${low}+ ${unitOf("speed")}`;
}

// A km/h speed class edge in the chosen units, rounded to a whole number.
function speedText(kmh, withUnit = true) {
  const value = Math.round(convert("speed", kmh));
  return withUnit ? `${value} ${unitOf("speed")}` : String(value);
}

function selectUnits(units) {
  state.units = units;
  try {
    localStorage.setItem("units", units);
  } catch {
    // Not remembered; the choice still applies to this page.
  }
  for (const button of document.querySelectorAll("[data-units]")) {
    button.setAttribute("aria-pressed", String(button.dataset.units === units));
  }
  for (const span of document.querySelectorAll("[data-unit]")) {
    span.textContent = unitOf(span.dataset.unit);
  }
  if (state.current) renderCurrent(state.current);
  renderHistory();
}

// ---- Start -----------------------------------------------------------------

function selectRange(range) {
  state.range = range;
  for (const button of document.querySelectorAll("[data-range]")) {
    button.setAttribute("aria-pressed", String(button.dataset.range === range));
  }
  // Keep the range in the address, so it survives a reload or a bookmark.
  PARAMS.set("range", range);
  history.replaceState(null, "", `?${PARAMS}`);
  loadHistory();
}

function start() {
  document.getElementById("grafana-link").href = `${location.protocol}//${location.hostname}:3000/`;
  for (const button of document.querySelectorAll("[data-range]")) {
    button.addEventListener("click", () => selectRange(button.dataset.range));
  }
  for (const button of document.querySelectorAll("[data-units]")) {
    button.addEventListener("click", () => selectUnits(button.dataset.units));
  }
  selectUnits(state.units);
  let frame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(renderHistory);
  }).observe(document.querySelector(".charts"));

  loadCurrent();
  selectRange(state.range);
  setInterval(loadCurrent, CURRENT_EVERY_MS);
  setInterval(loadHistory, HISTORY_EVERY_MS);
}

start();
