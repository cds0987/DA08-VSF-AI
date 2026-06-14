#!/usr/bin/env python3
"""Đẩy secret lên GitHub Actions Secrets qua REST API (sealed-box libsodium).

Dùng MỘT lần để di cư secret -> GitHub là nguồn duy nhất. KHÔNG commit giá trị.
Đọc PAT từ env GH_PAT, đọc KEY=VALUE từ file (mặc định /tmp/vsf_secrets.env).
Chỉ in TÊN key + status, không bao giờ in value.

  GH_PAT=xxx python scripts/set_github_secrets.py [secrets_file]

Sau khi xong: revoke PAT + xoá file tạm.
"""
import os
import sys
from base64 import b64encode

import requests
from nacl import encoding, public

REPO = os.environ.get("GH_REPO", "cds0987/DA08-VSF-AI")
PAT = os.environ.get("GH_PAT", "").strip()
SECRETS_FILE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vsf_secrets.env"

if not PAT:
    sys.exit("ERROR: thiếu env GH_PAT")

API = f"https://api.github.com/repos/{REPO}"
H = {
    "Authorization": f"Bearer {PAT}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def encrypt(pub_key_b64: str, value: str) -> str:
    pk = public.PublicKey(pub_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode())
    return b64encode(sealed).decode()


def load(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def main() -> None:
    r = requests.get(f"{API}/actions/secrets/public-key", headers=H, timeout=30)
    r.raise_for_status()
    pk = r.json()
    key_id, pub_b64 = pk["key_id"], pk["key"]

    secrets = load(SECRETS_FILE)
    print(f"repo={REPO}  secrets_to_set={len(secrets)}")
    ok = 0
    for name, value in secrets.items():
        if not value:
            print(f"  SKIP {name} (empty)")
            continue
        body = {"encrypted_value": encrypt(pub_b64, value), "key_id": key_id}
        resp = requests.put(
            f"{API}/actions/secrets/{name}", headers=H, json=body, timeout=30
        )
        status = "created" if resp.status_code == 201 else (
            "updated" if resp.status_code == 204 else f"FAIL {resp.status_code}"
        )
        print(f"  {name}: {status}")
        if resp.status_code in (201, 204):
            ok += 1
        else:
            print(f"    -> {resp.text[:200]}")
    print(f"done: {ok}/{len(secrets)} set")


if __name__ == "__main__":
    main()
