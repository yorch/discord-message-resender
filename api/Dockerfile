# syntax=docker/dockerfile:1

FROM node:24-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@11.23.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY tsconfig.json prisma.config.ts ./
COPY prisma ./prisma
COPY src ./src
# prisma.config.ts resolves env("DATABASE_URL") when the CLI loads it. Generate
# never connects, so a placeholder is enough and keeps a real URL out of the image.
ENV DATABASE_URL=postgresql://build:build@localhost:5432/build
RUN pnpm db:generate && pnpm build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN npm install -g pnpm@11.23.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Installed here rather than copied from the build stage: pnpm's node_modules is
# a symlink farm into .pnpm, and Docker COPY dereferences symlinks.
RUN pnpm install --prod --frozen-lockfile
COPY --from=build /app/dist ./dist
COPY prisma ./prisma
COPY prisma.config.ts ./
ENV PATH="/app/node_modules/.bin:$PATH"
USER node
EXPOSE 4000
# prisma stays in dependencies because the CLI runs at container start.
CMD ["sh", "-c", "prisma migrate deploy && node dist/index.js"]
