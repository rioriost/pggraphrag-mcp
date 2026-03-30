FROM postgres:17-bookworm

ARG PGVECTOR_VERSION=v0.8.0
ARG APACHE_AGE_VERSION=PG17

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bison \
        build-essential \
        ca-certificates \
        clang \
        curl \
        flex \
        git \
        libreadline-dev \
        pkg-config \
        postgresql-server-dev-17 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/build

RUN git clone --branch "${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git \
    && make -C pgvector \
    && make -C pgvector install

RUN git clone --branch "${APACHE_AGE_VERSION}" --depth 1 https://github.com/apache/age.git \
    && make -C age PG_CONFIG=/usr/lib/postgresql/17/bin/pg_config install

RUN mkdir -p /docker-entrypoint-initdb.d

WORKDIR /

RUN rm -rf /tmp/build

LABEL org.opencontainers.image.title="pggraphrag-db" \
      org.opencontainers.image.description="Repository-owned PostgreSQL 17 image with pgvector and Apache AGE extensions" \
      org.opencontainers.image.source="https://github.com/apache/age" \
      org.opencontainers.image.licenses="Apache-2.0"
