import base64
from enum import Enum
from pathlib import Path
from typing import Any

import litellm
import regex as re
from litellm.types.utils import ModelResponse
from litellm.utils import supports_pdf_input
from pydantic import BaseModel, Field, ValidationError
from regex import Pattern

from comic_to_audiobook.prompts import TRANSCRIPT_PROMPT, VOICE_ASSIGNMENT_PROMPT

MAX_LATENCY_CHARS = 300  # flush early if a sentence runs long
SENTENCE_BOUNDARY: Pattern[str] = re.compile(pattern=r"([.!?…]+[\s\"\')]|\n{2,})")


class VoiceProfileName(str, Enum):
    BELINDA = "belinda.wav"
    CHADWICK = "chadwick.wav"
    EN_MAN = "en_man.wav"
    EN_WOMAN = "en_woman.wav"
    FIFTYSHADES_ANNA = "fiftyshades_anna.wav"
    MABAOGUO = "mabaoguo.wav"
    MABEL = "mabel.wav"
    SHREK_DONKEY = "shrek_donkey.wav"
    SHREK_DONKEY_ES = "shrek_donkey_es.wav"
    SHREK_FIONA = "shrek_fiona.wav"
    SHREK_SHREK = "shrek_shrek.wav"
    VEX = "vex.wav"
    ZH_MAN_SICHUAN = "zh_man_sichuan.wav"
    BROOM_SALESMAN = "broom_salesman.wav"


class VoiceProfile(BaseModel):
    """Structured representation of a single character's assigned voice profile."""

    name: str = Field(..., description="Character name or descriptor as it appears in the comic.")
    voice_profile: VoiceProfileName = Field(
        ..., description="Filename of the selected audio profile, including extension."
    )
    reference_line: str = Field(
        ...,
        min_length=1,
        description="Short in-character line to guide voice cloning for this role.",
    )


class VoiceAssignmentResult(BaseModel):
    characters: list[VoiceProfile]
    narrator: VoiceProfile


class TranscriptLine(BaseModel):
    voice_profile: VoiceProfileName = Field(..., description="Assigned audio profile filename, e.g. belinda.wav")
    speaker: str = Field(..., min_length=1, description="Speaker label for this line (e.g. Narrator, Hero)")
    text: str = Field(..., min_length=1, description="Exact transcript text for this utterance")


class TranscriptResult(BaseModel):
    lines: list[TranscriptLine] = Field(default_factory=list, description="Ordered list of transcript lines")


VOICE_ASSIGNMENT_USER_PROMPT = (
    "Read the attached comic PDF and assign each speaking character (plus the narrator) to an audio profile "
    "using the JSON schema from the system prompt."
)


def _with_pdf_attachment(text: str, data_url: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": text},
        {"type": "file", "file": {"file_data": data_url}},
    ]


def prepare_voice_assignment_content(data_url: str) -> list[dict[str, Any]]:
    """Build the user content payload for the voice-assignment step."""
    return _with_pdf_attachment(text=VOICE_ASSIGNMENT_USER_PROMPT, data_url=data_url)


def prepare_transcript_content(assignment: VoiceAssignmentResult, data_url: str) -> list[dict[str, Any]]:
    """Build the user content payload for the transcript-generation step."""
    assignment_json: str = assignment.model_dump_json(indent=2)
    return [
        {"type": "text", "text": assignment_json},
        {"type": "file", "file": {"file_data": data_url}},
    ]


def encode_pdf(pdf_path: Path) -> str:
    with open(file=pdf_path, mode="rb") as pdf_file:
        return base64.b64encode(s=pdf_file.read()).decode(encoding="utf-8")


def assign_voice_profiles(model_name: str, data_url: str) -> VoiceAssignmentResult:
    """Call the model to assign audio profiles to comic characters and return validated results."""
    if not supports_pdf_input(model=model_name):
        raise ValueError(f"Model {model_name} does not support PDF input")

    file_content_with_prompt = prepare_voice_assignment_content(data_url=data_url)

    response: ModelResponse = litellm.completion(
        model=model_name,
        messages=[
            {"role": "system", "content": VOICE_ASSIGNMENT_PROMPT},
            {"role": "user", "content": file_content_with_prompt},
        ],
        response_format=VoiceAssignmentResult,
        stream=False,
    )

    # Non-streaming responses capture the full payload in the first choice message.
    message = response.choices[0].message if response.choices else None
    if message is None:
        raise ValueError("Voice assignment response did not contain any content.")

    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if not content:
        raise ValueError("Voice assignment response did not contain any content.")

    try:
        assignment = VoiceAssignmentResult.model_validate_json(json_data=content)
    except ValidationError as exc:
        raise ValueError("Unable to parse voice assignment from model response.") from exc

    if assignment.narrator.voice_profile != VoiceProfileName.BROOM_SALESMAN:
        raise ValueError("Narrator must be assigned the broom_salesman.wav profile.")

    if not assignment.characters:
        raise ValueError("No speaking characters were identified in the comic.")

    return assignment


def generate_structured_transcript(
    model_name: str, assignment: VoiceAssignmentResult, data_url: str
) -> TranscriptResult:
    if not supports_pdf_input(model=model_name):
        raise ValueError(f"Model {model_name} does not support PDF input")

    response: ModelResponse = litellm.completion(
        model=model_name,
        messages=[
            {"role": "system", "content": TRANSCRIPT_PROMPT},
            {"role": "user", "content": prepare_transcript_content(assignment=assignment, data_url=data_url)},
        ],
        response_format=TranscriptResult,
        stream=False,
    )

    message = response.choices[0].message if response.choices else None
    if message is None:
        raise ValueError("Transcript response did not contain any content.")

    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if not content:
        raise ValueError("Transcript response did not contain any content.")

    try:
        transcript = TranscriptResult.model_validate_json(json_data=content)
    except ValidationError as exc:
        raise ValueError("Unable to parse transcript from model response.") from exc

    if not transcript.lines:
        raise ValueError("Transcript did not contain any lines.")

    return transcript
