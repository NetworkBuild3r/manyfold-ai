# syntax=devthefuture/dockerfile-x
# Solo image: app + Redis in one container. Uses same base/build/runtime as manyfold.
# Sets REDIS_URL to localhost; entrypoint starts redis-server when REDIS_URL points to 127.0.0.1.
# For DB, provide DATABASE_* env or link a postgres service (e.g. in CI smoke test).

INCLUDE docker/base.dockerfile
INCLUDE docker/build.dockerfile
INCLUDE docker/runtime.dockerfile

## SOLO IMAGE ##########################################

FROM runtime AS manyfold-solo

RUN apk add --no-cache redis

# Solo mode: Redis inside this container; app connects to 127.0.0.1:6379
ENV REDIS_URL=redis://127.0.0.1:6379/0

# Same CMD as standard image; entrypoint will start Redis when REDIS_URL is localhost
CMD ["bundle", "exec", "rails", "server", "-p", "3214", "-b", "[::]"]
