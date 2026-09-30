FROM ghcr.io/presenton/presenton@sha256:ddf0d1f26397764856acdf94489dbbae5a2c0644a280723fd80bc7a80de338ba
USER root
COPY fastapi /app/servers/fastapi
COPY nextjs /app/servers/nextjs
COPY templates /app/templates
COPY LICENSE NOTICE /app/
COPY nginx.conf /app/nginx.conf
COPY nginx.conf /etc/nginx/nginx.conf
ENV CAN_CHANGE_KEYS=false DISABLE_AUTH=false DISABLE_IMAGE_GENERATION=true \
    DISABLE_ANONYMOUS_TRACKING=true PRESENTON_COMMUNITY_ENABLED=false \
    NEXT_PUBLIC_URL=http://127.0.0.1:3000/presenton NEXT_TELEMETRY_DISABLED=1
