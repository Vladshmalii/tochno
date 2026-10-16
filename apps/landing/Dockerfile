FROM nginx:1.27-alpine
# адреса кабінету: підставляється замість dev-посилань http://localhost:5173 / :8080
ARG APP_URL=http://localhost:5173
COPY index.html config.js favicon.svg mark.svg /usr/share/nginx/html/
COPY fonts /usr/share/nginx/html/fonts
RUN sed -i "s#http://localhost:5173#${APP_URL}#g; s#http://localhost:8080#${APP_URL}#g" \
      /usr/share/nginx/html/index.html /usr/share/nginx/html/config.js
EXPOSE 80
