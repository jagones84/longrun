# Harness2 experiment runtime.
#
# One pinned interpreter for every matched reference/candidate run. The base is
# pinned by digest, not tag, so a rebuild cannot silently change the Python
# version. Only the dependency the harness core actually imports is installed.
#
# Build (context is this directory, so the repo is never sent to the daemon):
#   docker build -f deploy/harness-runtime.Dockerfile -t longrun-h2-runtime:py312 deploy
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

RUN pip install --no-cache-dir PyYAML==6.0.2
