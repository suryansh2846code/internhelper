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
