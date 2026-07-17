## COMMON BASE ##########################################

FROM ruby:3.4.9-alpine3.23 AS base
WORKDIR /usr/src/app

RUN apk add --no-cache \
  tzdata=2026c-r0

RUN gem install bundler -v 2.5.23
RUN bundle config set --local deployment 'true'
RUN bundle config set --local without 'development test'

RUN apk add --no-cache \
  file=5.46-r2 \
  s6-overlay=3.2.0.3-r0 \
  gcompat=1.1.0-r4 \
  jemalloc=5.3.0-r6 \
  imagemagick=7.1.2.24-r0 \
  imagemagick-jpeg=7.1.2.24-r0 \
  imagemagick-webp=7.1.2.24-r0 \
  imagemagick-heic=7.1.2.24-r0 \
  assimp-dev=6.0.4-r0 \
  mesa-egl=25.2.7-r1

# Install latest VTK and OpenCascade from Alpine edge
# Unpinned edge packages — Alpine edge versions drift and break pinned builds.
RUN apk add --no-cache --repository=http://dl-cdn.alpinelinux.org/alpine/edge/community \
  vtk \
  opencascade \
  imath \
  alembic-libs \
  openexr-libopenexr

# Scripts for cross-platform architecture detection
COPY --from=tonistiigi/xx / /

# Install custom f3d package
RUN wget "https://github.com/manyfold3d/f3d-alpine/releases/download/v3.5.0-r0-1/f3d-3.5.0-r0.`xx-info alpine-arch`.apk" -O /tmp/f3d.apk
RUN apk add --no-cache --allow-untrusted /tmp/f3d.apk
RUN rm /tmp/f3d.apk
