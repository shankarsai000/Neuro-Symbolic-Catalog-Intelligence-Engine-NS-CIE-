# Stage 1: Build Next.js Application
FROM node:20-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Production Runner
FROM node:20-alpine AS runner

WORKDIR /app

RUN apk add --no-cache curl wget

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

COPY package*.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules

USER node

EXPOSE 3005

CMD ["sh", "-c", "npm start -- -p ${PORT:-3000}"]
