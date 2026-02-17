## RUNTIME STAGE ##########################################

FROM base as runtime

RUN apk add --no-cache \
  file \
  gcompat \
  jemalloc \
  imagemagick \
  imagemagick-jpeg \
  imagemagick-webp \
  imagemagick-heic \
  assimp-dev \
  su-exec \
  wget

# Default non-root user for running the app (UID/GID 1000)
RUN addgroup -g 1000 -S manyfold && adduser -u 1000 -S -G manyfold manyfold

COPY . .
RUN chmod +x bin/docker-entrypoint.sh
COPY --from=build /usr/src/app/vendor/bundle vendor/bundle
COPY --from=build /usr/src/app/public/assets public/assets

# Copy only the dynamic libraries we need from the build image
# It would be better to statically link the gems during build, if we can
COPY --from=build \
  /usr/lib/libmariadb.so.* \
  /usr/lib/libarchive.so.* \
  /usr/lib/libacl.so.*\
  /usr/lib/libexpat.so.* \
  /usr/lib/liblzma.so.* \
  /usr/lib/libzstd.so.* \
  /usr/lib/liblz4.so.* \
  /usr/lib/libbz2.so.* \
  /usr/lib/libpq.so.* \
  /usr/lib

# Set up jemalloc and YJIT for performance
ENV LD_PRELOAD="libjemalloc.so.2"
ENV MALLOC_CONF="dirty_decay_ms:1000,narenas:2,background_thread:true"
ENV RUBY_YJIT_ENABLE="1"

ARG APP_VERSION=unknown
ARG GIT_SHA=main
ARG DOCKER_TAG
ENV APP_VERSION=$APP_VERSION
ENV GIT_SHA=$GIT_SHA
ENV DOCKER_TAG=$DOCKER_TAG

# Runtime environment variables
ENV PORT=3214
ENV RACK_ENV=production
ENV RAILS_ENV=production
ENV NODE_ENV=production
ENV RAILS_SERVE_STATIC_FILES=true
ENV AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
ENV AWS_REQUEST_CHECKSUM_CALCULATION=when_required
ENV PUID=1000
ENV PGID=1000

EXPOSE 3214
ENTRYPOINT ["bin/docker-entrypoint.sh"]
CMD ["bundle", "exec", "rails", "server", "-p", "3214", "-b", "[::]"]
