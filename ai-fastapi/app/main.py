from fastapi import FastAPI

app = FastAPI(title="Sona AI")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}
