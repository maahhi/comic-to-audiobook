import base64
from collections.abc import Generator
from pathlib import Path
from typing import Any, Literal

import litellm
import regex as re
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.types.utils import ModelResponse
from litellm.utils import supports_pdf_input
from regex import Pattern

from comic_to_audiobook.prompts import SYSTEM_PROMPT

MAX_LATENCY_CHARS = 300  # flush early if a sentence runs long
#SENTENCE_BOUNDARY: Pattern[str] = re.compile(pattern=r"([.!?…]+[\s\"\')]|\n{2,})")
SENTENCE_BOUNDARY: re.Pattern[str] = re.compile(r"(####)")


def prepare_content(prompt: str, data_url: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": prompt},
        {"type": "file", "file": {"file_data": data_url}},
    ]


def encode_pdf(pdf_path: Path) -> str:
    with open(file=pdf_path, mode="rb") as pdf_file:
        return base64.b64encode(s=pdf_file.read()).decode(encoding="utf-8")


def generate_transcript(
    model_name: str, file_content_with_prompt: list[dict[str, Any]]
) -> Generator[str | Literal[""], Any, None]:
    if not supports_pdf_input(model=model_name):
        raise ValueError(f"Model {model_name} does not support PDF input")

    response: ModelResponse | CustomStreamWrapper = litellm.completion(
        model=model_name,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": file_content_with_prompt}],
        stream=True,
    )
    for part in response:
        yield part.choices[0].delta.content or ""
