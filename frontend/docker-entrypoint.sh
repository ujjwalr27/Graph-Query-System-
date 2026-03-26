#!/bin/sh
# Substitute environment variables into nginx config at container start
# BACKEND_URL: full URL of backend Railway service (e.g. https://dodgeai-backend.railway.app)
# PORT: assigned by Railway (defaults to 80 locally)

export PORT=${PORT:-80}
export BACKEND_URL=${BACKEND_URL:-http://backend:8000}

envsubst '${PORT} ${BACKEND_URL}' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "nginx config:"
cat /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
