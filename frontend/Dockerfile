FROM node:24-alpine AS build
WORKDIR /app

# Optional extra root CAs (*.crt in frontend/certs, git-ignored) for machines behind TLS interception.
COPY certs/ /tmp/extra-certs/
RUN find /tmp/extra-certs -name '*.crt' -exec cat {} + > /tmp/extra-ca.pem
ENV NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# nginx renders templates/*.template with the container environment at start.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
