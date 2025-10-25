# Higgs Audio Hackathon

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for dependency management and virtualenv creation

## Setup

Install project dependencies into a managed virtual environment:

```sh
uv sync
```

By default this creates `.venv/` in the project root and installs both runtime and development dependencies defined in `pyproject.toml`. To install only the main dependencies, run `uv sync --no-dev`.

## Environment Variables

Copy the example environment file and fill in the required secrets or configuration:

- **macOS / Linux**

  ```sh
  cp .env.example .env
  ```

- **Windows (PowerShell)**

  ```powershell
  Copy-Item .env.example .env
  ```

Edit `.env` with your own values. When a command depends on these variables, include `--env-file .env` so `uv` loads them automatically.

## Common Commands

- `uv pip list` — confirm the environment and installed packages.
- `uv run --env-file .env pytest` — execute the test suite.
- `uv run pre-commit run --all-files` — apply formatting and lint checks.

Use `uv run --env-file .env <cmd>` to execute any tool within the managed environment without manual activation.
