from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_weather_agent

app = FastAPI(title="WeatherGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    location: str = ""


class ChatResponse(BaseModel):
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # run_weather_agent is synchronous (LLM + HTTP calls). Wrapping it with
    # run_in_threadpool prevents it from blocking FastAPI's async event loop.
    response = await run_in_threadpool(run_weather_agent, request.message, request.location)
    return ChatResponse(response=response)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
