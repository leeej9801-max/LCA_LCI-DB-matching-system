# D1: 운영 빌드는 --mode real(.env.real: 데이터셋·세션·작업·샘플·평가는 실제 서버). 그냥 vite build 는 전부 mock 이 된다
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npx vite build --mode real

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
