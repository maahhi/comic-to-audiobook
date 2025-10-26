import logging
import sys
from collections.abc import Generator
from pathlib import Path
from textwrap import fill
from typing import Any

import gradio as gr
from gradio_pdf import PDF
from numpy import dtype, ndarray
from numpy._typing._shape import _AnyShape

from comic_to_audiobook.audio_generator import pcm_bytes_to_numpy_int16, synthesize_structured_transcript
from comic_to_audiobook.comic_processor import (
    TranscriptResult,
    VoiceAssignmentResult,
    assign_voice_profiles,
    encode_pdf,
    generate_structured_transcript,
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
logger: logging.Logger = logging.getLogger(name=__name__)

TRANSCRIPT_GENERATION_MODEL = "gemini/gemini-2.5-pro"
VOICE_ASSIGNMENT_MODEL = "gemini/gemini-2.5-flash"


def format_voice_assignments(assignment: VoiceAssignmentResult, width: int | None = None) -> str:
    """Minimal, tidy output for a monospace textbox."""
    rows = [(assignment.narrator.name, assignment.narrator.voice_profile.value, assignment.narrator.reference_line)]
    rows += [(c.name, c.voice_profile.value, c.reference_line) for c in assignment.characters]

    lines = ["Voice assignments:"]
    for name, voice, ref in rows:
        lines.append(f"• {name} — [{voice}]")
        if width:
            # Soft-wrap the reference under a short label; textbox keeps it neat.
            lines.append(fill(text=ref, width=width, initial_indent="  Ref: ", subsequent_indent="       "))
        else:
            lines.append(f"  Ref: {ref}")
        lines.append("")  # blank line between entries

    return "\n".join(lines).rstrip()


def format_transcript_lines(result: TranscriptResult) -> str:
    formatted: list[str] = []
    for line in result.lines:
        speaker_prefix = f"{line.speaker}: " if line.speaker else ""
        formatted.append(f"[{line.voice_profile.value}] {speaker_prefix}{line.text}")
    return "\n".join(formatted)


def main(
    file_path: str,
    cached_state: dict[str, Any] | None,
) -> Generator[
    tuple[
        tuple[int, ndarray[_AnyShape, dtype[Any]]] | None,
        str | object,
        str,
        dict[str, Any],
    ],
    Any,
    None,
]:
    state_payload: dict[str, Any] = {"assignment": None, "transcript": None}
    if isinstance(cached_state, dict):
        state_payload.update({k: cached_state.get(k) for k in ("assignment", "transcript") if k in cached_state})

    # Prepare the PDF once for both model calls
    file_encoding: str = encode_pdf(pdf_path=Path(file_path))
    base64_url: str = f"data:application/pdf;base64,{file_encoding}"

    # Step 1: assign voice profiles
    try:
        voice_assignment: VoiceAssignmentResult = assign_voice_profiles(
            model_name=VOICE_ASSIGNMENT_MODEL, data_url=base64_url
        )
    except ValueError as exc:
        error_message = f"Voice profile extraction failed: {exc}"
        logger.warning(error_message)
        yield None, error_message, error_message, state_payload
        return
    except Exception:  # pragma: no cover - defensive guardrail
        logger.exception("Unexpected error while assigning voice profiles.")
        fallback_message = "Voice profile extraction encountered an unexpected error. Please try again."
        yield None, fallback_message, fallback_message, state_payload
        return

    assignment_display: str = format_voice_assignments(assignment=voice_assignment)
    assignment_data: dict[str, Any] = voice_assignment.model_dump(mode="json")
    state_payload["assignment"] = assignment_data

    # Let the UI show the cast while we generate the transcript
    yield None, "Generating transcript...", assignment_display, state_payload

    # Step 2: generate structured transcript
    try:
        transcript_result: TranscriptResult = generate_structured_transcript(
            model_name=TRANSCRIPT_GENERATION_MODEL,
            assignment=voice_assignment,
            data_url=base64_url,
        )
    except ValueError as exc:
        error_message = f"Transcript generation failed: {exc}"
        logger.warning(error_message)
        yield None, error_message, assignment_display, state_payload
        return
    except Exception:  # pragma: no cover - defensive guardrail
        logger.exception("Unexpected error while generating transcript.")
        fallback_message = "Transcript generation encountered an unexpected error. Please try again."
        yield None, fallback_message, assignment_display, state_payload
        return

    state_payload["transcript"] = transcript_result.model_dump(mode="json")

    transcript_text: str = format_transcript_lines(result=transcript_result)
    if not transcript_text.strip():
        empty_message = "Transcript was empty. Unable to produce audio."
        yield None, empty_message, assignment_display, state_payload
        return

    # Show the transcript in the UI
    yield None, transcript_text, assignment_display, state_payload

    # Step 3: synthesize audio using the structured transcript
    try:
        for pcm_chunk in synthesize_structured_transcript(transcript_result.lines, voice_assignment):
            if not pcm_chunk:
                continue
            yield pcm_bytes_to_numpy_int16(pcm_bytes=pcm_chunk), transcript_text, assignment_display, state_payload
    except Exception as exc:  # pragma: no cover - defensive guardrail
        logger.exception("TTS generation failed.")
        failure_message = f"Audio synthesis failed: {exc}"
        yield None, transcript_text + f"\n\n{failure_message}", assignment_display, state_payload


output_text: gr.Textbox = gr.Textbox(
    label="Transcript",
    lines=17,
    show_copy_button=True,
)
output_audio: gr.Audio = gr.Audio(label="Narration", streaming=True, autoplay=True)
voice_profiles_box: gr.Textbox = gr.Textbox(
    label="Voice Profiles",
    lines=5,
    show_copy_button=True,
)
workflow_state: gr.State = gr.State()

demo: gr.Interface = gr.Interface(
    fn=main,
    inputs=[PDF(label="Comic (.pdf)"), workflow_state],
    outputs=[output_audio, output_text, voice_profiles_box, workflow_state],
    title="Comic Book Narrator",
)

_ = demo.launch(max_file_size="10mb")
