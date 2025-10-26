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

from comic_to_audiobook.comic_processor import TranscriptLine, VoiceAssignmentResult

logger: logging.Logger = logging.getLogger(name=__name__)

BOSON_API_KEY: str | None = os.getenv("BOSON_API_KEY")
AUDIO_MODEL_NAME: str = "higgs-audio-generation-Hackathon"
SAMPLE_RATE: int = 24_000
REFERENCE_AUDIO_DIR: Path = Path("ref-audio")

_client = openai.Client(api_key=BOSON_API_KEY, base_url="https://hackathon.boson.ai/v1")


@dataclass(frozen=True)
class ReferenceVoice:
    profile: str
    tag: str
    wav_path: Path
    transcript: str


def pcm_bytes_to_numpy_int16(pcm_bytes: bytes) -> tuple[int, np.ndarray]:
    arr: NDArray[signedinteger[_16Bit]] = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (SAMPLE_RATE, arr)


def _basic_tts_stream(text: str) -> Generator[bytes, None, None]:
    """Fallback speech synthesis using a single Boson preset voice."""
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


_VOICE_REFERENCE_CONFIG: dict[str, dict[str, str]] = {
    "belinda.wav": {
        "file": "belinda.wav",
        "tag": "BELINDA",
        "transcript": "[BELINDA] Bright and lively, I'm ready to narrate your story with energy.",
    },
    "chadwick.wav": {
        "file": "chadwick.wav",
        "tag": "CHADWICK",
        "transcript": "[CHADWICK] Gruff and monstrous, I bring the shadows to life.",
    },
    "en_man.wav": {
        "file": "en_man.wav",
        "tag": "EN_MAN",
        "transcript": "[EN_MAN] Confident and composed, I speak with steady resolve.",
    },
    "en_woman.wav": {
        "file": "en_woman.wav",
        "tag": "EN_WOMAN",
        "transcript": "[EN_WOMAN] Clear and assured, my words carry the news with poise.",
    },
    "mabel.wav": {
        "file": "mabel.wav",
        "tag": "MABEL",
        "transcript": "[MABEL] With a crisp British lilt, I add charm to every line.",
    },
    "vex.wav": {
        "file": "vex.wav",
        "tag": "VEX",
        "transcript": "[VEX] Raspy and insistent, I poke and prod every conversation.",
    },
    "zh_man_sichuan.wav": {
        "file": "zh_man_sichuan.wav",
        "tag": "ZH_MAN_SICHUAN",
        "transcript": "[ZH_MAN_SICHUAN] Animated and bright, my Sichuan accent stands out.",
    },
    "broom_saleman.wav": {
        "file": "broom_salesman.wav",
        "tag": "NARRATOR",
        "transcript": "[NARRATOR] Steady and warm, I guide listeners through each scene.",
    },
}


def _load_reference_voice(profile: str, generated_line: str | None) -> ReferenceVoice | None:
    config = _VOICE_REFERENCE_CONFIG.get(profile.lower())
    if not config:
        return None

    wav_path = REFERENCE_AUDIO_DIR / config["file"]
    if not wav_path.exists():
        logger.warning("Reference WAV not found for profile %s at %s", profile, wav_path)
        return None

    transcript_text = (generated_line or "").strip() or config.get("transcript", "")
    if not transcript_text:
        transcript_text = f"[{config['tag']}]"

    return ReferenceVoice(
        profile=profile,
        tag=config["tag"],
        wav_path=wav_path,
        transcript=transcript_text,
    )


def _encode_audio_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def synthesize_structured_transcript(
    transcript_lines: Iterable[TranscriptLine],
    assignment: VoiceAssignmentResult,
) -> Generator[bytes, None, None]:
    lines: list[TranscriptLine] = list(transcript_lines)
    if not lines:
        return

    reference_lines: dict[str, str] = {
        assignment.narrator.voice_profile.value: assignment.narrator.reference_line
    }
    for character in assignment.characters:
        profile_value = character.voice_profile.value
        reference_lines.setdefault(profile_value, character.reference_line)

    unique_profiles = {line.voice_profile.value for line in lines}
    references: dict[str, ReferenceVoice] = {}
    missing_profiles: set[str] = set()

    for profile in unique_profiles:
        ref = _load_reference_voice(profile, reference_lines.get(profile))
        if ref:
            references[profile] = ref
        else:
            missing_profiles.add(profile)

    combined_text_lines: list[str] = []
    for line in lines:
        speaker_prefix = f"{line.speaker}: " if line.speaker else ""
        combined_text_lines.append(f"[{line.voice_profile.value}] {speaker_prefix}{line.text}")
    fallback_text = "\n".join(combined_text_lines)

    if missing_profiles:
        logger.warning(
            "Falling back to default TTS for profiles lacking reference audio: %s",
            ", ".join(sorted(missing_profiles)),
        )
        yield from _basic_tts_stream(text=fallback_text)
        return

    tag_list = ", ".join(f"[{ref.tag}]" for ref in references.values())
    system_prompt = (
        "You are an AI assistant designed to convert text into speech.\n"
        "If the user's message includes one of the tags "
        f"{tag_list}, do not read out the tag. "
        "Instead, generate speech for the tagged text using the matching voice.\n"
        "If no tag is provided, select a suitable voice on your own.\n\n"
        "<|scene_desc_start|>\nAudio is recorded from a quiet room.\n<|scene_desc_end|>"
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for reference in references.values():
        messages.append({"role": "user", "content": reference.transcript})
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": _encode_audio_file(reference.wav_path),
                            "format": "wav",
                        },
                    }
                ],
            }
        )

    final_script_lines: list[str] = []
    for line in lines:
        ref = references[line.voice_profile.value]
        speaker_prefix = f"{line.speaker}: " if line.speaker else ""
        final_script_lines.append(f"[{ref.tag}] {speaker_prefix}{line.text}")
    final_script = "\n".join(final_script_lines)

    messages.append({"role": "user", "content": final_script})

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
