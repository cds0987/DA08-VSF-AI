import os

# user-service config loader raise nếu JWT_SECRET_KEY là giá trị mặc định yếu.
# Set trước khi bất kỳ module nào import app → test chạy độc lập với môi trường.
# setdefault: không override nếu CI đã export một giá trị thật.
os.environ.setdefault("JWT_SECRET_KEY", "test-user-service-secret-for-pytest-only")
