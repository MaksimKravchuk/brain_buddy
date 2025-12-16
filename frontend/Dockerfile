FROM node:18-alpine AS base

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG VITE_API_BASE_URL=/api
ARG VITE_API_KEY=
ARG VITE_API_KEY_HEADER=X-API-Key

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_API_KEY=$VITE_API_KEY \
    VITE_API_KEY_HEADER=$VITE_API_KEY_HEADER

FROM base AS tests

ENV CI=1

CMD ["npm", "run", "test"]

FROM base AS build

RUN npm run build

FROM nginx:1.25-alpine AS runtime

ENV BACKEND_ORIGIN=http://backend:8000

RUN rm /etc/nginx/conf.d/default.conf
COPY deploy/nginx/default.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
