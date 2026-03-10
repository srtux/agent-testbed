# Use a specialized uv image for building
FROM ghcr.io/astral-sh/uv:0.5.4-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy the entire root directory to handle workspace dependencies
COPY . .

# Sync the project (installs all dependencies including workspace members)
RUN uv pip install --system keyrings.google-artifactregistry-auth && rm -f uv.lock && uv sync --no-dev --no-editable --index-url https://pypi.org/simple

# Final image
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Ensure the app code is present
COPY . .

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental

# The CMD should point to the entrypoint of the specific service
CMD ["uvicorn", "agents.WeatherSpecialist.main:app", "--host", "0.0.0.0", "--port", "8080"]
