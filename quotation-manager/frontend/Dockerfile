FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_QUOTATION_API_BASE_URL

COPY quotation-manager/frontend/package.json ./
RUN npm install

COPY quotation-manager/frontend .
RUN npm run build

FROM nginx:1.27-alpine

COPY quotation-manager/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
