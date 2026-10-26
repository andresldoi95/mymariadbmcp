FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libmariadb-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY docker/integration ./docker/integration

RUN python -m pip install --no-cache-dir ".[dev]"

CMD ["python", "-m", "pytest", "-m", "integration", "-ra"]
