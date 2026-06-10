# syntax=docker/dockerfile:1
# nginx gateway với config NƯỚNG SẴN vào image (build trong CI từ nginx/nginx.conf).
# KHÔNG bind-mount file trên VM nữa -> sửa tay nginx.conf trên VM là VÔ TÁC DỤNG.
# Nguồn chuẩn DUY NHẤT = nginx/nginx.conf trong git -> CI build -> VM pull.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Fail-fast: build hỏng nếu config sai cú pháp.
RUN nginx -t -c /etc/nginx/nginx.conf
