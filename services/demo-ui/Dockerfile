FROM node:20-slim AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM node:20-slim

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=8501

COPY package*.json ./
RUN npm ci --omit=dev

COPY server.js ./
COPY --from=build /app/dist ./dist

EXPOSE 8501

CMD ["npm", "start"]
