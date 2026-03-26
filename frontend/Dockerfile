# Build stage
FROM node:18-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# VITE_API_URL is injected by Railway as a build arg at image build time
# (Railway passes service variables with matching ARG names automatically)
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}

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

EXPOSE 80

CMD ["/docker-entrypoint.sh"]
