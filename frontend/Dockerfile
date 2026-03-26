# Build stage
FROM node:18-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

RUN npm run build

# Production stage – serve with nginx
FROM nginx:alpine

# Install gettext for envsubst
RUN apk add --no-cache gettext

# nginx template (variables substituted at container startup)
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Startup script: substitute env vars into nginx config, then start nginx
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE ${PORT:-80}

CMD ["/docker-entrypoint.sh"]
