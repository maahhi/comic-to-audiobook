# Comic to Audiobook

Turn static comics into narrated experiences. This project ingests a comic PDF, casts bespoke voices for every speaking character, expands the dialogue into an audiobook-grade transcript, and streams synthesized audio through a Gradio UI. It was built for the Higgs Audio Hackathon and demonstrates end-to-end orchestration of Gemini multimodal models with Boson voice synthesis.

## Highlights

- Automated voice casting that maps every character to a curated voice profile and reference line.
- Transcript generation that blends dialogue with expanded narration ready for storytelling.
- Streaming text-to-speech powered by Boson, with fallbacks when a reference voice is unavailable.
- Friendly Gradio front end with live transcript updates and downloadable audio.

## Architecture

1. **Comic ingestion** – the uploaded PDF is base64-encoded and shared with Gemini.
2. **Voice assignment** – `gemini-2.5-flash` selects voice profiles and reference lines using `VOICE_ASSIGNMENT_PROMPT`.
3. **Transcript generation** – `gemini-2.5-pro` produces a structured narration aligned with the assigned voices.
4. **Audio synthesis** – Boson TTS clones the requested voices (or falls back to a default voice) and streams PCM audio to the UI.

All model requests are validated with Pydantic models to catch malformed responses early, and audio is emitted in 24 kHz PCM chunks for smooth playback.

## Prerequisites

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for dependency management
- Boson Hackathon API access and Gemini-compatible API keys

## Installation

```sh
uv sync
```

This creates `.venv/` and installs both runtime and dev dependencies. To skip dev tooling, run `uv sync --no-dev`.

## Configuration

1. Copy the example environment file and populate it with valid credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Set the required variables:
   - `BOSON_API_KEY` – access token for Boson audio generation.
   - `OPENAI_API_KEY` / `OPENAI_API_BASE` – forwarded to LiteLLM for Gemini access (via Boson proxy during the hackathon).

`uv run --env-file .env <command>` ensures the variables are loaded without activating the virtualenv manually.

## Voice Reference Library

The `voices/` directory contains reference WAV files used for cloning character voices. Filenames must match the `VoiceProfileName` enum in `comic_to_audiobook/comic_processor.py`. To add a new voice:

1. Drop the WAV file into `voices/`.
2. Add the filename to `VoiceProfileName` and describe it in `VOICE_ASSIGNMENT_PROMPT`.
3. Provide an example line in the Gradio UI when prompted.

## Running the App

```sh
uv run --env-file .env python -m comic_to_audiobook.app
```

The Gradio interface launches on `http://127.0.0.1:7860/` by default. Upload a comic PDF (up to 10 MB) to trigger:

1. Voice casting summary in the “Voice Profiles” panel.
2. Streaming transcript updates in the “Transcript” panel.
3. Narration playback in the audio component, delivered as PCM chunks.

The final audio can be downloaded from the Gradio UI for offline listening.

## Development Workflow

- Format and lint: `uv run ruff check src tests`
- Run tests: `uv run --env-file .env pytest`
- Full pre-commit suite: `uv run pre-commit run --all-files`

Key modules live under `src/comic_to_audiobook/`:

- `app.py` – Gradio interface and orchestration loop.
- `comic_processor.py` – Gemini prompt payloads, schema validation, and PDF handling.
- `audio_generator.py` – Boson streaming API integration and voice cloning logic.
- `prompts.py` – Prompt templates for voice assignment and transcript generation.
