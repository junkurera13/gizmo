FROM ghcr.io/memodb-io/memobase@sha256:956c47deeb5b2c3b98a680ebf64e3b3fd82aec0f3ec9c0c3bc7f97a6e04615d3

COPY config.yaml /app/config.yaml
COPY scripts /app/gizmo_scripts

# Upstream prints the full configuration and database URLs at startup.
# Keep credentials out of provider logs before installing runtime secrets.
RUN sed -i '/LOG.info(f"Database URL:/d; /LOG.info(f"Redis URL:/d' /app/memobase_server/connectors.py \
    && sed -i 's/LOG.info(f"{overwrite_config}")/LOG.info("Configuration loaded; secrets omitted")/' /app/memobase_server/env.py
