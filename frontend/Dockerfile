FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY vite.config.ts tsconfig.json tailwind.config.ts postcss.config.js ./
COPY index.html ./
COPY src ./src
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "--port", "3000"]