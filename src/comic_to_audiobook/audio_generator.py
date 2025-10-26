import logging
import os
from collections.abc import Generator
from typing import Any
from difflib import get_close_matches

import numpy as np
import openai
from numpy import signedinteger
from numpy._typing._array_like import NDArray
from numpy._typing._nbit_base import _16Bit

import regex as re
import base64
def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode("utf-8")

logger: logging.Logger = logging.getLogger(name=__name__)

BOSON_API_KEY: str | None = os.getenv("BOSON_API_KEY")
MODEL_NAME: str = "higgs-audio-generation-Hackathon"
VOICE: str = "belinda"
SAMPLE_RATE: int = 24_000

client = openai.Client(api_key=BOSON_API_KEY, base_url="https://hackathon.boson.ai/v1")


def find_closest_voice_file(voice_ref: str, voices_dir: str) -> str:
    """
    Find the closest matching voice file if the exact match doesn't exist.
    
    Args:
        voice_ref: The reference voice name to search for
        voices_dir: Directory containing voice files
        
    Returns:
        Path to the closest matching voice file
    """
    expected_path = os.path.join(voices_dir, f"{voice_ref}.wav")
    
    # If the exact file exists, return it
    if os.path.exists(expected_path):
        return expected_path
    
    # Otherwise, find the closest match
    logger.warning(f"Voice file '{voice_ref}.wav' not found. Searching for closest match...")
    
    # Get all .wav files in the voices directory
    if not os.path.exists(voices_dir):
        logger.error(f"Voices directory not found: {voices_dir}")
        return expected_path
    
    voice_files = [f for f in os.listdir(voices_dir) if f.endswith('.wav')]
    voice_names = [os.path.splitext(f)[0] for f in voice_files]
    
    # Find the closest match using difflib
    matches = get_close_matches(voice_ref, voice_names, n=1, cutoff=0.3)
    
    if matches:
        closest_voice = matches[0]
        closest_path = os.path.join(voices_dir, f"{closest_voice}.wav")
        logger.info(f"Using closest match: '{closest_voice}.wav' (original: '{voice_ref}.wav')")
        return closest_path
    else:
        logger.error(f"No close match found for '{voice_ref}'. Available voices: {voice_names}")
        return expected_path


def tts_stream_pcm(text: str) -> Generator[bytes, Any, None]:
    orgtxt = str(text)
    text = text.strip()
    text = text.replace("####", "").strip()
    left, right = text.split(":")
    voice_ref = left.strip("[] ").strip(".wav")   # removes brackets and spaces
    line = right.strip()               # removes spaces
    print("----------------------" ,voice_ref, line)
    
    # Get the voices directory path
    voices_dir = os.path.join(os.path.dirname(__file__), "..", "..", "voices")
    # Check if file exists and find closest match if not
    voice_ref_path = find_closest_voice_file(voice_ref, voices_dir)
    #resp = client.audio.speech.create(model=MODEL_NAME, voice=voice_ref, input=line, response_format="pcm")
    resp = client.chat.completions.create(
        model="higgs-audio-generation-Hackathon",
        messages=[
            {"role": "user", "content": line},
            {
                "role": "assistant",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": b64(voice_ref_path), "format": "wav"}
                }],
            }
        ],
        modalities=["text", "audio"],
        max_completion_tokens=4096,
        temperature=1.0,
        top_p=0.95,
        stream=False,
        stop=["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
        extra_body={"top_k": 50},
    )
    yield resp.content  # bytes
    #yield resp.content  # bytes


def pcm_bytes_to_numpy_int16(pcm_bytes: bytes) -> tuple[int, np.ndarray]:
    arr: NDArray[signedinteger[_16Bit]] = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (SAMPLE_RATE, arr)
