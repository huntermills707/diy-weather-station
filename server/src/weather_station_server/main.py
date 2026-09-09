from fastapi import FastAPI

app = FastAPI(title="weather-station-server")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
