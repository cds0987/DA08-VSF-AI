from types import SimpleNamespace

from app.infrastructure.storage.gcs_client import GCSClient


class _Blob:
    def __init__(self, *, needs_iam: bool) -> None:
        self._needs_iam = needs_iam
        self.calls: list[dict] = []

    def generate_signed_url(self, **kwargs):
        self.calls.append(kwargs)
        # Local-key path is attempted first (no signer kwargs). On keyless ADC the
        # underlying SDK raises AttributeError because there is no private key.
        if self._needs_iam and "access_token" not in kwargs:
            raise AttributeError("you need a private key to sign credentials")
        return "https://signed.example/object"


def _client(bucket: str = "b") -> GCSClient:
    return GCSClient(SimpleNamespace(gcs_bucket=bucket, gcp_project_id="p"))


def test_sign_url_uses_local_key_when_available():
    blob = _Blob(needs_iam=False)
    url = _client()._sign_url(blob, 300)
    assert url == "https://signed.example/object"
    assert len(blob.calls) == 1
    assert "access_token" not in blob.calls[0]


def test_sign_url_falls_back_to_iam_signblob_when_keyless(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client, "_iam_signer", lambda: ("vsf-storage@p.iam.gserviceaccount.com", "tok")
    )
    blob = _Blob(needs_iam=True)
    url = client._sign_url(blob, 300)
    assert url == "https://signed.example/object"
    # First attempt without IAM (raises), second with IAM signBlob params.
    assert len(blob.calls) == 2
    assert blob.calls[1]["service_account_email"] == "vsf-storage@p.iam.gserviceaccount.com"
    assert blob.calls[1]["access_token"] == "tok"
