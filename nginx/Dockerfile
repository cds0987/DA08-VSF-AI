# nginx gateway với config NƯỚNG SẴN vào image (build trong CI từ nginx/nginx.conf).
# KHÔNG bind-mount file trên VM nữa -> sửa tay nginx.conf trên VM là VÔ TÁC DỤNG.
# Nguồn chuẩn DUY NHẤT = nginx/nginx.conf trong git -> CI build -> VM pull.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
# KHÔNG `nginx -t` ở build: proxy_pass dùng hostname literal (user-service, ...) ->
# nginx resolve DNS ngay lúc test -> emerg "host not found" trong build container.
# Cú pháp được kiểm khi container start trong compose network (hostname resolve được),
# và smoke test sau deploy bắt lỗi runtime.
