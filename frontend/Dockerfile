# Frontend image: Next.js dev/standalone.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

# Default to dev server; compose overrides as needed.
CMD ["npm", "run", "dev"]
