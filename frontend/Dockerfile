# Imagen de la consola oficial. Dos etapas: se construye con Node y se sirve con
# nginx, que es lo que hay que poner delante de una aplicación de una sola
# página — no un servidor de desarrollo.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# La configuración del cliente se genera AL ARRANCAR a partir del entorno, no se
# compila: cambiar la dirección del gateway o el nombre del producto no puede
# exigir reconstruir la imagen.
COPY entrada.sh /docker-entrypoint.d/40-config.sh
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chmod +x /docker-entrypoint.d/40-config.sh
EXPOSE 80
