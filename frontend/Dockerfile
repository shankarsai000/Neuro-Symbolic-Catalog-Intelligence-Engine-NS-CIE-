FROM node:20-alpine

WORKDIR /app

RUN apk add --no-cache curl wget

ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0

COPY package*.json ./
COPY .next ./.next
COPY public ./public
COPY node_modules ./node_modules

USER node

EXPOSE 3000

CMD ["npm", "start"]
