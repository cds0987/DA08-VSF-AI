import os

# hr-service đọc JWT_SECRET_KEY (Admin API verify) và config loader fail-fast lúc
# import app nếu thiếu. Set 1 secret test cố định TRƯỚC khi bất kỳ test nào import
# app.main -> test chạy độc lập với môi trường (local/CI), không cần export tay.
# setdefault: nếu CI đã export JWT_SECRET_KEY thì tôn trọng giá trị đó.
os.environ.setdefault("JWT_SECRET_KEY", "very-strong-secret-for-testing-only-1234567890")
