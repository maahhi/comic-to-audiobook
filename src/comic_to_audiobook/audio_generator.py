import base64
import logging
import os
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import openai
from numpy import signedinteger
from numpy._typing._array_like import NDArray
from numpy._typing._nbit_base import _16Bit

from comic_to_audiobook.comic_processor import TranscriptLine, VoiceAssignmentResult, VoiceProfile

logger: logging.Logger = logging.getLogger(name=__name__)

BOSON_API_KEY: str | None = os.getenv("BOSON_API_KEY")
AUDIO_MODEL_NAME: str = "higgs-audio-generation-Hackathon"
SAMPLE_RATE: int = 24_000
REFERENCE_AUDIO_DIR: Path = Path("voices")

_client = openai.Client(api_key=BOSON_API_KEY, base_url="https://hackathon.boson.ai/v1")


@dataclass(frozen=True)
class ReferenceVoice:
    profile: str
    tag: str
    transcript: str
    audio_b64: str


def pcm_bytes_to_numpy_int16(pcm_bytes: bytes) -> tuple[int, np.ndarray]:
    arr: NDArray[signedinteger[_16Bit]] = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (SAMPLE_RATE, arr)


def _basic_tts_stream(text: str) -> Generator[bytes, None, None]:
    """Fallback speech synthesis using a single preset voice."""
    with _client.audio.speech.with_streaming_response.create(
        model=AUDIO_MODEL_NAME,
        voice="belinda",
        input=text,
        response_format="pcm",
    ) as stream:
        buffer = bytearray()
        for chunk in stream.iter_bytes(chunk_size=4096):
            buffer.extend(chunk)
            cutoff = len(buffer) // 2 * 2
            if cutoff:
                yield bytes(buffer[:cutoff])
                del buffer[:cutoff]
        if buffer:
            yield bytes(buffer)


def _encode_audio_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _load_reference_voice(assignment_entry: VoiceProfile | None, index: int) -> ReferenceVoice | None:
    if assignment_entry is None:
        return None

    profile = assignment_entry.voice_profile.value

    wav_path = REFERENCE_AUDIO_DIR / profile
    if not wav_path.exists():
        logger.warning("Reference WAV not found for profile %s at %s", profile, wav_path)
        return None

    tag = f"SPEAKER{index}"

    transcript_text = assignment_entry.reference_line.strip() if assignment_entry.reference_line else ""
    if not transcript_text:
        transcript_text = f"[{tag}] I speak with steady resolve."

    return ReferenceVoice(
        profile=profile,
        tag=tag,
        transcript=transcript_text,
        audio_b64=_encode_audio_file(wav_path),
    )


def _voice_system_prompt(tag: str) -> str:
    return (
        "You are an AI assistant designed to convert text into speech.\n"
        f"When the user's message includes the tag [{tag}], do not read the tag aloud. "
        "Instead, generate speech for the tagged text using the same style as the provided reference audio.\n"
        "If no tag is present, choose an appropriate voice.\n\n"
        "<|scene_desc_start|>\nAudio is recorded from a quiet room.\n<|scene_desc_end|>"
    )


def synthesize_structured_transcript(
    transcript_lines: Iterable[TranscriptLine],
    assignment: VoiceAssignmentResult,
) -> Generator[bytes, None, None]:
    lines: list[TranscriptLine] = list(transcript_lines)
    if not lines:
        return

    assignment_map: dict[str, VoiceProfile] = {
        assignment.narrator.voice_profile.value: assignment.narrator,
        **{character.voice_profile.value: character for character in assignment.characters},
    }

    reference_cache: dict[str, ReferenceVoice | None] = {}
    for index, profile in enumerate({line.voice_profile.value for line in lines}):
        reference_cache[profile] = _load_reference_voice(assignment_map.get(profile), index)

    for line in lines:
        profile = line.voice_profile.value
        reference_voice = reference_cache.get(profile)

        if reference_voice is None:
            logger.info("Falling back to default TTS for profile %s", profile)
            fallback_text = f"{line.text}"
            yield from _basic_tts_stream(text=fallback_text)
            continue

        final_message = f"[{reference_voice.tag}] {line.text}"
        messages: list[dict] = [
            {"role": "system", "content": _voice_system_prompt(reference_voice.tag)},
            {"role": "user", "content": reference_voice.transcript},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": reference_voice.audio_b64,
                            "format": "wav",
                        },
                    }
                ],
            },
            {"role": "user", "content": final_message},
        ]

        logger.info("Generating audio for: %s", final_message)
        stream = _client.chat.completions.create(
            model=AUDIO_MODEL_NAME,
            messages=messages,
            modalities=["text", "audio"],
            audio={"format": "pcm16"},
            stream=True,
            max_completion_tokens=4096,
            temperature=1.0,
            top_p=0.95,
            extra_body={"top_k": 50},
            stop=["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
        )

        for chunk in stream:
            delta = getattr(chunk.choices[0], "delta", None)
            audio = getattr(delta, "audio", None) if delta else None
            if not audio:
                continue

            audio_data = audio.get("data")
            if not audio_data:
                continue

            yield base64.b64decode(audio_data)
