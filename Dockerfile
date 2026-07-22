FROM node:22-bookworm-slim AS motebus-deps

WORKDIR /opt/motebus

COPY app/mcp_ss/package.json app/mcp_ss/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts


FROM python:3.12-slim

WORKDIR /app

# ------------------------------------------------------------
# System dependencies (curl for healthcheck)
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Native MoteChat is Node-based; keep the Python MCP server and bridge runtime
# in the same OCI image without installing any HTTP SmartScreen client.
COPY --from=motebus-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=motebus-deps /opt/motebus/node_modules /opt/motebus/node_modules

# ------------------------------------------------------------
# Python dependencies
# ------------------------------------------------------------
COPY app/requirements.txt /app/requirements.txt

# Install the version-bounded FastMCP runtime and remaining dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# ------------------------------------------------------------
# Application code
# ------------------------------------------------------------
COPY app/main.py /app/main.py
COPY app/mcp_ss /app/mcp_ss

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------
ENV PYTHONPATH=/app
ENV MCP_TRANSPORT=streamable-http
ENV NODE_PATH=/opt/motebus/node_modules

# ------------------------------------------------------------
# Runtime
# ------------------------------------------------------------
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ping || exit 1

# Ensure clean CMD execution
ENTRYPOINT []

# Streamable HTTP is the default Docker mode
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--no-access-log"]
