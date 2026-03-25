# --- 构建阶段 ---
FROM node:18-alpine as build-stage
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# --- 运行阶段 ---
FROM nginx:stable-alpine

# 安装 envsubst (alpine 默认自带 gettext 包包含此工具)
# 拷贝编译好的前端文件
COPY --from=build-stage /app/dist /usr/share/nginx/html

# 拷贝模板文件 (注意文件名)
COPY ./nginx.conf.template /etc/nginx/templates/default.conf.template

# Nginx 官方镜像会自动将 /etc/nginx/templates/*.template 
# 通过 envsubst 处理后输出到 /etc/nginx/conf.d/default.conf
# 只要我们在 docker-compose 中传入环境变量即可

EXPOSE 80