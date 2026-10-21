# frontend-vite/Dockerfile

# Stage 1: Build the React app
FROM node:20-alpine AS build
ARG VITE_API_URL=https://bluepace-ats-11.onrender.com
ENV VITE_API_URL=$VITE_API_URL
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]