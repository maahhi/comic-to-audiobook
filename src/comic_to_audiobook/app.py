from collections.abc import Generator
from pathlib import Path
from typing import Any

import gradio as gr

from comic_to_audiobook.utils import encode_pdf, generate_transcript, prepare_content

MODEL_NAME = "gemini/gemini-2.5-pro"


def main(file_path: str) -> Generator[str, Any, None]:
    file_encoding: str = encode_pdf(pdf_path=Path(file_path))
    base64_url: str = f"data:application/pdf;base64,{file_encoding}"
    file_content_with_prompt: list[dict[str, Any]] = prepare_content(
        prompt="Transcribe the input.", data_url=base64_url
    )
    transcript: str = ""
    for chunk in generate_transcript(model_name=MODEL_NAME, file_content_with_prompt=file_content_with_prompt):
        if not chunk:
            continue

        transcript += chunk
        yield transcript

    # make sure the final text is kept when the generator finishes
    yield transcript


output_box: gr.Textbox = gr.Textbox(
    label="Comic narration",
    lines=20,  # initial visible rows
    show_copy_button=True,
)

demo: gr.Interface = gr.Interface(
    fn=main, inputs=gr.File(file_types=[".pdf"]), outputs=output_box, title="Comic Narrator"
)

if __name__ == "__main__":
    _ = demo.launch(max_file_size="5mb")
