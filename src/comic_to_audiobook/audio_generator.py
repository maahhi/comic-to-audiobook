import logging
import os
from collections.abc import Generator
from typing import Any

import numpy as np
import openai
from numpy import signedinteger
from numpy._typing._array_like import NDArray
from numpy._typing._nbit_base import _16Bit

logger: logging.Logger = logging.getLogger(name=__name__)

BOSON_API_KEY: str | None = os.getenv("BOSON_API_KEY")
MODEL_NAME: str = "higgs-audio-generation-Hackathon"
VOICE: str = "belinda"
SAMPLE_RATE: int = 24_000

client = openai.Client(api_key=BOSON_API_KEY, base_url="https://hackathon.boson.ai/v1")


def tts_stream_pcm(text: str) -> Generator[bytes, Any, None]:
    resp = client.audio.speech.create(model=MODEL_NAME, voice=VOICE, input=text, response_format="pcm")
    yield resp.content  # bytes


def pcm_bytes_to_numpy_int16(pcm_bytes: bytes) -> tuple[int, np.ndarray]:
    arr: NDArray[signedinteger[_16Bit]] = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (SAMPLE_RATE, arr)
