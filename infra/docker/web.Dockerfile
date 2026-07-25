# Web image for local Compose development (`next dev` with hot reload).
# Production deployment builds a standalone bundle separately; see
# docs/04-system-architecture.md.
FROM node:22-slim

ENV NODE_ENV=development

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/shared-types/package.json packages/shared-types/

RUN npm ci

COPY packages/shared-types packages/shared-types
COPY apps/web apps/web

EXPOSE 3000

CMD ["npm", "run", "dev", "--workspace", "@jip/web"]
