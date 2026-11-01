#!/usr/bin/env bash
# Build `inspect-arms:latest` — the sandbox image that carries BOTH harnesses.
#
# Why one image: an Inspect eval gives every arm the same container and the same
# model (via `sandbox_agent_bridge`), so the only difference left is the harness.
# Payload baked at build time = no download/mount at trial time:
#
#   /opt/oc/node            node v24 (openclaw requires >=24.22.1 <25)
#   /opt/oc/openclaw        the openclaw package
#   /opt/longrun            longrun server.py + src + config + the two turn drivers
#
# The committed `Dockerfile` next to this script only derives from the image this
# script produces; it holds no payload of its own.
#
# Usage:  bash benchmarks/inspect_sandbox/build_image.sh
set -euo pipefail

REPO=/home/jagones/Repositories/longrun
SRC=$REPO/benchmarks/inspect_sandbox
NODE=/home/jagones/.nvm/versions/node/v24.22.1/bin/node
OC=/home/jagones/.local/node/lib/node_modules/openclaw
CTX=/tmp/inspect-arms-ctx
IMG=inspect-arms:latest

for p in "$NODE" "$OC" "$REPO/server.py" "$REPO/src" "$REPO/config" \
         "$SRC/longrun_turn.sh" "$SRC/openclaw_turn.sh"; do
  [ -e "$p" ] || { echo "missing payload: $p" >&2; exit 2; }
done

rm -rf "$CTX"
mkdir -p "$CTX"

echo "[1/4] packing payload into $CTX"
tar -C "$(dirname "$NODE")" -cf "$CTX/node.tar" node
tar -C "$(dirname "$OC")" -cf "$CTX/openclaw.tar" openclaw
tar -C "$REPO" -cf "$CTX/longrun.tar" server.py src config requirements.txt
cp "$SRC/longrun_turn.sh" "$SRC/openclaw_turn.sh" "$CTX/"
ls -lh "$CTX"

cat > "$CTX/Dockerfile.build" <<'DOCKER'
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
# python3 = longrun core (stdlib + PyYAML); git/curl/jq/unzip = what agent tools
# shell out to inside a task container; libstdc++6 = the node binary's own dep.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-yaml libstdc++6 ca-certificates curl git jq unzip tar procps file \
 && rm -rf /var/lib/apt/lists/*
COPY node.tar openclaw.tar longrun.tar /tmp/payload/
RUN mkdir -p /opt/oc /opt/longrun \
 && tar -C /opt/oc -xf /tmp/payload/node.tar \
 && tar -C /opt/oc -xf /tmp/payload/openclaw.tar \
 && tar -C /opt/longrun -xf /tmp/payload/longrun.tar \
 && rm -rf /tmp/payload
COPY longrun_turn.sh openclaw_turn.sh /opt/longrun/
RUN chmod +x /opt/longrun/longrun_turn.sh /opt/longrun/openclaw_turn.sh
WORKDIR /app
DOCKER

echo "[2/4] docker build -t $IMG"
docker build -t "$IMG" -f "$CTX/Dockerfile.build" "$CTX"

echo "[3/4] smoke test"
docker run --rm "$IMG" bash -lc '
  set -e
  python3 -c "import yaml, sys; print(\"python\", sys.version.split()[0], \"yaml\", yaml.__version__)"
  /opt/oc/node --version
  test -f /opt/longrun/server.py
  test -x /opt/longrun/longrun_turn.sh
  test -x /opt/longrun/openclaw_turn.sh
  test -f /opt/oc/openclaw/openclaw.mjs
  echo "turn drivers + runtimes present"
'

echo "[4/4] done: $IMG"
docker images "$IMG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'
