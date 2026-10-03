# Dashboard

Local, read-only web dashboard for the stored weather readings: current
conditions, 24 h / 7 day / 30 day charts, rain totals, a wind rose, and
station health. The design, including how stale and unavailable data is
shown, is in [docs/dashboard.md](../docs/dashboard.md).

Plain HTML, CSS, and JavaScript with SVG charts. There is no build step and
no dependencies; edit the files and reload. The server on the Pi serves this
folder at `/` (`http://<pi-address>:8000/`), and the page reads data from the
server's [read API](../docs/read-api.md). It never writes to the database.

To work on it locally, run the server from `server/` (see its README) and
open `http://localhost:8000/`. Point it at a copy of real data with
`WEATHER_STATION_DB_PATH`.
