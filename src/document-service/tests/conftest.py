import os

# common.py nay nạp Settings lúc import (để đối chiếu allow_list với manifest
# rag-worker), nên JWT_SECRET_KEY phải có TRƯỚC khi pytest collect bất kỳ test
# nào import app.*. Đặt ở conftest (chạy sớm nhất) thay vì rải setdefault từng file.
os.environ.setdefault("JWT_SECRET_KEY", "test-document-service-secret")
