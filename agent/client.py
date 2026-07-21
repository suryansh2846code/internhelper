"""Thin HTTP client the local agent uses to talk to the server ('brain')."""
import requests


class ServerClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def login(cls, base_url: str, email: str, password: str) -> "ServerClient":
        base = base_url.rstrip("/")
        r = requests.post(f"{base}/api/auth/login", data={"username": email, "password": password}, timeout=30)
        r.raise_for_status()
        return cls(base, r.json()["access_token"])

    @classmethod
    def with_key(cls, base_url: str, agent_key: str) -> "ServerClient":
        """Use a stored device key (from a previous pairing)."""
        return cls(base_url.rstrip("/"), agent_key)

    @classmethod
    def pair(cls, base_url: str, pair_token: str, device_name: str) -> tuple["ServerClient", str]:
        """Exchange a one-time pairing token for a durable device key."""
        base = base_url.rstrip("/")
        r = requests.post(f"{base}/api/agent/pair", timeout=30,
                          json={"token": pair_token, "device_name": device_name})
        r.raise_for_status()
        key = r.json()["agent_key"]
        return cls(base, key), key

    def heartbeat(self) -> bool:
        """Mark this device online. Returns False on failure (e.g. web-session token)."""
        try:
            r = self.s.post(f"{self.base}/api/agent/heartbeat", timeout=15)
            return r.ok
        except Exception:
            return False

    def claim_job(self) -> dict | None:
        r = self.s.post(f"{self.base}/api/jobs/claim", timeout=30)
        r.raise_for_status()
        return r.json() or None

    def report(self, job_id: int, status: str, result: dict | None = None, error: str = "") -> None:
        self.s.post(f"{self.base}/api/jobs/{job_id}/result", timeout=60,
                    json={"status": status, "result": result or {}, "error": error})

    def download_resume(self, resume_id: int, dest_path: str) -> str:
        r = self.s.get(f"{self.base}/api/resumes/{resume_id}/file", timeout=60)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return dest_path
