import queue
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import gradio as gr
from numpy import dtype, ndarray
from numpy._typing._shape import _AnyShape

from comic_to_audiobook.audio_generator import pcm_bytes_to_numpy_int16, tts_stream_pcm
from comic_to_audiobook.comic_processor import (
    MAX_LATENCY_CHARS,
    SENTENCE_BOUNDARY,
    encode_pdf,
    generate_transcript,
    prepare_content,
)

MODEL_NAME = "gemini/gemini-2.5-pro"


def main(
    file_path: str,
) -> Generator[tuple[None, str | object] | tuple[tuple[int, ndarray[_AnyShape, dtype[Any]]], str | object], Any, None]:
    # Define sentinel to signal the end of TTS input stream and text output stream
    SENTINEL: object = object()

    # Queues to hold streamed chunks of text and audio for both input and outputs
    tts_in: queue.Queue[str | object] = queue.Queue(maxsize=8)  # text chunk to TTS
    audio_out: queue.Queue[bytes | object] = queue.Queue(maxsize=32)  # output audio chunk
    text_out: queue.Queue[str | object] = queue.Queue(maxsize=64)  # text chunk to output text box

    # Prepare the PDF
    file_encoding: str = encode_pdf(pdf_path=Path(file_path))
    base64_url: str = f"data:application/pdf;base64,{file_encoding}"
    file_content_with_prompt: list[dict[str, Any]] = prepare_content(
        prompt="Transcribe the input.", data_url=base64_url
    )

    def vlm_producer() -> None:
        transcript: str = ""
        sentence_buffer: str = ""
        for text_chunk in generate_transcript(
            model_name=MODEL_NAME, file_content_with_prompt=file_content_with_prompt
        ):
            if not text_chunk:
                continue

            transcript += text_chunk

            if text_out.empty():  # only push to the output text box after all existing text has been consumed
                text_out.put(item=transcript)

        sentence_buffer += text_chunk

        while True:
            match = SENTENCE_BOUNDARY.search(string=sentence_buffer)
            should_flush_long_text: bool = len(sentence_buffer) >= MAX_LATENCY_CHARS and not match

            if not match and not should_flush_long_text:
                break

            if match:
                # Found complete sentence
                cut: int = match.end()

                # Cut out complete sentence
                sentence = sentence_buffer[:cut].strip()

                # Keep the remaining in the buffer
                sentence_buffer = sentence_buffer[cut:]
            else:
                # Flush sentence longer than MAX_LATENCY_CHAR
                sentence = sentence_buffer.strip()

                # Clear buffer
                sentence_buffer = ""

            if sentence:  # add to the TTS streaming queue
                tts_in.put(item=sentence)

        # Flush any trailing text
        if sentence_buffer.strip():
            tts_in.put(item=sentence_buffer.strip())

        tts_in.put(item=SENTINEL)
        text_out.put(item=transcript)
        text_out.put(item=SENTINEL)

    # Thread 2: consume sentences -> stream PCM -> audio_out
    def tts_worker() -> None:
        while True:
            item: str | object = tts_in.get()
            if item is SENTINEL:
                break

            for pcm_chunk in tts_stream_pcm(text=item):
                audio_out.put(item=pcm_chunk)

        audio_out.put(item=SENTINEL)

    # Start threads
    threading.Thread(target=vlm_producer, daemon=True).start()
    threading.Thread(target=tts_worker, daemon=True).start()

    # Generator loop: interleave text updates and audio chunks
    latest_text = ""
    text_done = audio_done = False
    last_text_push: float = 0.0

    while not (text_done and audio_done):
        # 1) Prefer pushing text updates frequently
        try:
            txt: str | object = text_out.get(timeout=0.02)
            if txt is SENTINEL:
                text_done = True
            else:
                latest_text: str | object = txt
                now: float = time.time()
                # avoid flooding UI: ~15 fps for text updates
                if now - last_text_push > 1 / 15:
                    last_text_push = now
                    yield None, latest_text
        except queue.Empty:
            pass

        # 2) Push any available audio immediately (can be many per iteration)
        pushed_audio = False
        while True:
            try:
                chunk: bytes | object = audio_out.get_nowait()
            except queue.Empty:
                break
            if chunk is SENTINEL:
                audio_done = True
                break
            pushed_audio = True
            yield pcm_bytes_to_numpy_int16(pcm_bytes=chunk), latest_text

        # Small sleep to yield the event loop if nothing happened
        if not pushed_audio:
            time.sleep(0.005)

    # Ensure the final state is visible
    yield None, latest_text


output_text: gr.Textbox = gr.Textbox(
    label="Comic narration",
    lines=17,  # initial visible rows
    show_copy_button=True,
)
output_audio: gr.Audio = gr.Audio(label="Voice", streaming=True, autoplay=True)

demo: gr.Interface = gr.Interface(
    fn=main, inputs=gr.File(file_types=[".pdf"]), outputs=[output_audio, output_text], title="Comic Narrator"
)

_ = demo.launch(max_file_size="15mb")
