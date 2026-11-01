# Sandbox image for the Inspect arms.
#
# It only references the image built by `benchmarks/inspect_sandbox/build_image.sh`,
# which carries BOTH runtimes (longrun's source + node v24 + openclaw). Inspect builds
# this file when a task asks for `sandbox=("docker", ".../Dockerfile")`; there is no
# second copy of the payload and no download at trial time.
FROM inspect-arms:latest
WORKDIR /app
