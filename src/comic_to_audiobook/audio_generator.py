import os
from collections.abc import Generator
from typing import Any

import numpy as np
import openai
from numpy import signedinteger
from numpy._typing._array_like import NDArray
from numpy._typing._nbit_base import _16Bit

BOSON_API_KEY: str | None = os.getenv("BOSON_API_KEY")
MODEL_NAME: str = "higgs-audio-generation-Hackathon"
SAMPLE_RATE: int = 24_000

client = openai.Client(api_key=BOSON_API_KEY, base_url="https://hackathon.boson.ai/v1")


def tts_stream_pcm(text: str) -> Generator[bytes, Any, None]:
    """
    Try true streaming first (if supported by your OpenAI-compatible server),
    otherwise fall back to one-shot PCM and yield it as a single chunk.
    """
    # Attempt true streaming
    try:
        # NOTE: this with_streaming_response API exists for OpenAI's Python SDK.
        # If Boson's gateway exposes it, this will stream bytes incrementally.
        with client.audio.speech.with_streaming_response.create(
            model=MODEL_NAME,
            voice="belinda",
            input=text,
            response_format="pcm",
        ) as resp:
            for b in resp.iter_bytes():
                if b:
                    yield b
            return
    except Exception:
        pass  # fall back to micro-batching

    print("FALLBACK TO SINGLE PCM BLOB")

    # Fallback: single PCM blob
    resp = client.audio.speech.create(model=MODEL_NAME, voice="belinda", input=text, response_format="pcm")
    yield resp.content  # bytes


def pcm_bytes_to_numpy_int16(pcm_bytes: bytes) -> tuple[int, np.ndarray]:
    arr: NDArray[signedinteger[_16Bit]] = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (SAMPLE_RATE, arr)
