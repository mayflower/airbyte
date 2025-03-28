# Use the Airbyte Python connector base image.
FROM airbyte/python-connector-base:4.0.0

ENV HOME=/airbyte
ENV HF_HOME=/airbyte/.cache
ENV DOCLING_ARTIFACTS_PATH=/airbyte/.cache/docling/models

# Set the working directory inside the container.
WORKDIR /airbyte/integration_code

# Copy only the Poetry project files first for dependency caching.
COPY pyproject.toml poetry.lock* ./

# Install Poetry (if not already available in the base image).
RUN pip install poetry

# Install git to load the modified airbyte-cdk repository
RUN apt update && \
    apt -y install \
        git \
    && apt -y autoremove \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

# Configure Poetry to install dependencies in the container's environment (without creating a virtualenv)
RUN poetry install --no-dev \
    && rm -Rf /airbyte/.cache/pypoetry

RUN usermod -d /airbyte airbyte

# Copy the rest of your connector code into the container.
COPY main.py /airbyte/integration_code/
COPY source_langchain_docling_loader/ /airbyte/integration_code/source_langchain_docling_loader/

ENV AIRBYTE_ENTRYPOINT="python /airbyte/integration_code/main.py"
ENTRYPOINT ["python", "/airbyte/integration_code/main.py"]

# pre download the default model to avoid problems without internet connection
RUN mkdir -p $DOCLING_ARTIFACTS_PATH \
    && docling-tools models download -q -o $DOCLING_ARTIFACTS_PATH \
    && pip cache purge \
    && rm -Rf /airbyte/.cache/pypoetry \
    && chown -R airbyte:airbyte /airbyte

COPY sample_files/examples/* /airbyte/examples/
