FROM docker.io/airbyte/python-connector-base:4.0.0

RUN apt update && \
    apt -y install \
        git \
    && apt -y autoremove \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/airbyte
ENV HF_HOME=/airbyte/.cache
ENV DOCLING_ARTIFACTS_PATH=/airbyte/.cache/docling/models

WORKDIR /airbyte

COPY ./sample_files /airbyte/
COPY ./scripts/pip_cleaner /usr/local/bin
COPY pyproject.toml poetry.lock ./main.py ./source_langchain_docling_loader /airbyte/integration_code/

RUN chown -R airbyte:airbyte .

WORKDIR /airbyte/integration_code

RUN pip install --upgrade pip \
    && pip install poetry \
    && poetry install --no-dev \
    && rm pyproject.toml poetry.lock \
    && pip cache purge

RUN usermod -d /airbyte airbyte

# pre download the default model to avoid problems without internet connection
RUN mkdir -p $HF_HOME \
    && docling-tools models download -q -o $DOCLING_ARTIFACTS_PATH \
    && pip cache purge \
    && chown -R airbyte:airbyte $HF_HOME
