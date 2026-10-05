# Dashboard design

The local dashboard (JAE-21) shows current conditions, history, and station
health on any device on the home network. The server on the Pi serves it at
`http://<pi-address>:8000/`. Code: [`dashboard/`](../dashboard). Data:
[read API](read-api.md).

It is plain HTML, CSS, and JavaScript with SVG charts: no build step, no
libraries, nothing loaded from the internet. Grafana (port 3000) stays
available for ad-hoc digging. The dashboard is the everyday view.

## Layout

One page, top to bottom:

1. **Header**: the title and a status line, for example "Updated 2 min ago
   · 4:16 PM", with a coloured dot (green fresh, amber stale, red server
   unreachable).
2. **Banner** (only when something is wrong): stale data, no readings yet,
   or server unreachable.
3. **Current conditions**: five cards.
   - **Temperature**, with dew point, and the heat index in warm weather
     (26.7 °C and up).
   - **Humidity**.
   - **Pressure**: sea level when the altitude is set, with station
     pressure underneath. Otherwise station pressure, labelled
     "altitude not set".
   - **Rain today**, with the last hour, the last 24 hours, and this month.
   - **Wind**: the average, gust, and direction as a compass needle and a
     label ("from WNW (293°)"). The needle points into the wind, like the
     vane.
4. **History**: a 24 h / 7 days / 30 days switch, then charts of
   temperature (average line, min-max band when points are averages),
   humidity, station pressure, wind (average and gust), rain per interval,
   and a wind rose for the same period. A note above the charts says what
   one point is ("one five-minute reading" or "averages 2 h of readings").
   Touching or hovering a chart shows the time and values of the nearest
   point.
5. **Station health**: the last reading time and age, readings in the last
   24 hours out of 288, reboots in the last 24 hours, uptime, station clock
   sync, WiFi signal (good ≥ -60 dBm, fair ≥ -70 dBm, weak below), BME280
   status, readings with [data-quality flags](data-quality.md) in the last
   24 hours, the last reboot (lifetime boot number and reset reason), the
   upload queue (readings dropped because it was full), and the last reading
   ID. The reboot and queue rows appear once the station runs M4 firmware.

On a phone the cards sit two per row (wind full width) and the charts stack
in one column. On a wide screen the cards fit one row and the charts two
columns.

## Units

A switch in the header picks **°F · mph** or **°C · km/h** for temperature
(including dew point and heat index) and wind speed, everywhere on the page.
It defaults to °F · mph in a US English browser and °C · km/h elsewhere, and
the browser remembers the choice. Rain stays in mm and pressure in hPa. The
API is always metric; the dashboard converts for display, and wind rose
speed classes are rounded to whole mph (2, 10, 20, 30 km/h become 1, 6, 12,
19 mph).

## Timestamps

- All times show in the **viewer's** time zone and locale (12- or 24-hour).
- The status line gives the age of the latest reading **and** its clock time.
  The health section repeats it with the weekday.
- Chart tooltips show the date and time of the point. For averaged points
  they also show how many readings went into it.
- Rain "today" and "this month" use the **server's** time zone
  ([read-api.md](read-api.md#rain-totals)). When the viewer's zone differs,
  the rain card says which zone the days follow.

## Unavailable and stale data

The rule: never show a made-up number, and always say why something is
missing.

| Situation | What the dashboard shows |
| --------- | ------------------------ |
| Latest reading older than 11 min (`stale`) | Amber status "No new reading for 25 min", an amber banner naming the time of the last reading and noting that the station sends up to 24 hours of queued readings when it reconnects, and the card values greyed. The values stay visible: they are the last known conditions. |
| No readings at all | "No readings yet" status and banner; every card shows "—". |
| Server unreachable | Red status "Server unreachable" and a banner with the error. The last data received stays on screen, and the page keeps retrying every minute. |
| Value flagged by a [data-quality rule](data-quality.md) | The card keeps the value (it is what the station sent) with an amber "Suspect: outside plausible range" or "Suspect: unchanged for 2 h". Derived values that use it show "—". Charts leave it out, and the tooltip says how many flagged readings a point left out. The wind rose lists flagged readings under the rose. |
| BME280 `error` or `implausible` | Temperature, humidity, and pressure show "—" with "Sensor not responding" or "Sensor reading out of range". Derived values show "—". Health shows the sensor status in red or amber. |
| Wind vane unknown | No compass needle; "direction unknown (vane)". |
| Calm (average below 2 km/h) | No needle; "calm". In still air the vane only holds its last position. |
| Altitude not configured | Station pressure instead of sea level, labelled "altitude not set". |
| Missing readings in history | The chart line breaks ([gap rule](read-api.md#get-apiseries)). A sensor fault breaks only that sensor's line. |
| No data in a chart's range | "No data in this period". The rain chart says "No rain in this period". |
| Wind rose with only calm or unknown readings | A message saying so; the calm and unknown counts are always listed under the rose. |
| Health warnings | Amber for: stale, fewer than 95 % of expected readings, a reboot, unsynced clock, weak WiFi, flagged readings, a last reboot caused by a watchdog, panic, or brownout, and dropped queue readings. Red for a BME280 error. |

## Refresh

Current conditions reload every minute; history every five minutes, and
whenever the range changes. The selected range is kept in the address
(`?range=7d`), so a bookmark or reload keeps it. `?station=<id>` picks
another station.

## Mobile

- Layout tested at 320, 390, and 1280 px wide, in light and dark mode, with
  no horizontal scrolling.
- The range buttons are at least 44 px tall (the usual minimum touch target).
- Charts redraw to their container width, so they never overflow. A
  horizontal drag on a chart moves the tooltip, and vertical drags still
  scroll the page.
- Light and dark colours follow the device setting.
