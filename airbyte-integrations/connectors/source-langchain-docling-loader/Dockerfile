FROM docker.io/airbyte/python-connector-base:4.0.0

RUN apt update && \
    apt -y install \
        git \
    && apt -y autoremove \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

ENV HF_HOME=/tmp/airbyte/.cache

COPY ./sample_files /sample_files
COPY ./scripts/pip_cleaner /usr/local/bin

RUN usermod -d /tmp/airbyte airbyte

# pre download the default model to avoid problems without internet connection
RUN mkdir -p $HF_HOME \
    && pip_cleaner install docling \
    && docling-tools models download -q -o $HF_HOME/docling/models \
    && pip_cleaner uninstall \
    && pip cache purge \
    && chown -R airbyte:airbyte $HF_HOME
