"""Entry point: ``uvicorn main:app --port 8888`` (local) — Vercel uses api/index.py."""

from dotenv import load_dotenv

load_dotenv()

from weathergpt.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
