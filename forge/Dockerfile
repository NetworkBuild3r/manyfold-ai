FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libarchive13 \
        libarchive-dev \
    && rm -rf /var/lib/apt/lists/*

# Official static 7-Zip (7zz) for the engine's RAR4/Deflate64 fallback (INIT-032/SPEC-006).
# The tarball is verified against a pinned sha256 per architecture before anything is extracted.
ARG TARGETARCH
ARG SEVENZIP_VERSION=2603
ARG SEVENZIP_SHA256_AMD64=dc99eff5008f1ab79bd7084c68513701547a808a89502bf4133683535ab3c695
ARG SEVENZIP_SHA256_ARM64=2389ba20e4d8295e8709c20b6263b69bd1ec4972fe38a04ad7a1badbf595b996
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
        amd64) arch=x64; sha="$SEVENZIP_SHA256_AMD64" ;; \
        arm64) arch=arm64; sha="$SEVENZIP_SHA256_ARM64" ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    url="https://www.7-zip.org/a/7z${SEVENZIP_VERSION}-linux-${arch}.tar.xz"; \
    python - "$url" "$sha" <<'EOF'
import hashlib, io, sys, tarfile, urllib.request
url, want = sys.argv[1], sys.argv[2]
data = urllib.request.urlopen(url, timeout=120).read()
got = hashlib.sha256(data).hexdigest()
if got != want:
    sys.exit(f"7zz tarball sha256 mismatch: {got} != {want}")
with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as t:
    member = t.getmember("7zzs")
    if not member.isreg():
        sys.exit("7zzs is not a regular file")
    with open("/usr/local/bin/7zz", "wb") as out:
        out.write(t.extractfile(member).read())
EOF
RUN chmod 0755 /usr/local/bin/7zz && 7zz i | head -n 3

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 forge
USER forge

ENTRYPOINT ["forge"]
