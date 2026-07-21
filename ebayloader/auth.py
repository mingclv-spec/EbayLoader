"""eBay OAuth 2.0 authentication for EbayLoader."""

import json
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, parse_qs

import requests
from rich.console import Console

console = Console()

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
]

SANDBOX_AUTH_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

PROD_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
PROD_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


class eBayAuth:
    """Manages eBay OAuth tokens (Client Credentials + Authorization Code)."""

    def __init__(self, config):
        self.config = config
        self._token: Optional[dict] = None

    @property
    def auth_url(self):
        return SANDBOX_AUTH_URL if self.config.sandbox else PROD_AUTH_URL

    @property
    def token_url(self):
        return SANDBOX_TOKEN_URL if self.config.sandbox else PROD_TOKEN_URL

    # ── Client Credentials Grant (Application Token) ──────────────

    def get_application_token(self) -> str:
        """Get a client_credentials grant token (limited scope)."""
        resp = requests.post(
            self.token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": self._basic_auth(),
            },
            data={"grant_type": "client_credentials", "scope": " ".join(SCOPES)},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"]

    # ── Authorization Code Grant (User Token) ────────────────────

    def _basic_auth(self) -> str:
        import base64
        raw = f"{self.config.app_id}:{self.config.cert_id}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def get_authorization_url(self, state: str = "ebayloader") -> str:
        params = urlencode({
            "client_id": self.config.app_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
        })
        return f"{self.auth_url}?{params}"

    def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        resp = requests.post(
            self.token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": self._basic_auth(),
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
        )
        resp.raise_for_status()
        token = resp.json()
        token["acquired_at"] = int(time.time())
        self._save_token(token)
        self._token = token
        return token

    def refresh_token(self) -> dict:
        """Refresh an expired access token using the refresh token."""
        token = self._load_token()
        if not token or "refresh_token" not in token:
            raise RuntimeError("No refresh token available. Authenticate first.")

        resp = requests.post(
            self.token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": self._basic_auth(),
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
                "scope": " ".join(SCOPES),
            },
        )
        resp.raise_for_status()
        new_token = resp.json()
        new_token["refresh_token"] = token.get("refresh_token", new_token.get("refresh_token"))
        new_token["acquired_at"] = int(time.time())
        self._save_token(new_token)
        self._token = new_token
        return new_token

    def get_valid_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        token = self._load_token()
        if not token:
            raise RuntimeError("Not authenticated. Run `ebay auth login` first.")

        # Check if expired (expires_in is in seconds)
        acquired = token.get("acquired_at", 0)
        expires_in = token.get("expires_in", 7200)
        if time.time() - acquired > expires_in - 60:  # 1 min buffer
            console.print("[yellow]Access token expired — refreshing...[/yellow]")
            token = self.refresh_token()

        return token["access_token"]

    # ── Token Persistence ─────────────────────────────────────────

    def _load_token(self) -> Optional[dict]:
        if self._token:
            return self._token
        path = self.config.token_path
        if path.exists():
            with open(path) as f:
                try:
                    self._token = json.load(f)
                except json.JSONDecodeError:
                    return None
            return self._token
        return None

    def _save_token(self, token: dict):
        path = self.config.token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(token, f, indent=2)
        path.chmod(0o600)

    def is_authenticated(self) -> bool:
        try:
            token = self._load_token()
            return token is not None
        except Exception:
            return False


def login_flow(config):
    """Interactive OAuth login — opens browser, waits for code."""
    auth = eBayAuth(config)
    url = auth.get_authorization_url()

    console.print("\n[bold]🔐 eBay Authorization[/bold]")
    console.print(f"Opening browser for OAuth...\n{url}\n")
    webbrowser.open(url)

    console.print(
        "[yellow]After authorizing, you'll be redirected. "
        "Copy the full URL and paste the `code` parameter value here:[/yellow]"
    )
    code = input("Authorization code: ").strip()
    if not code:
        console.print("[red]No code provided.[/red]")
        return False

    try:
        token = auth.exchange_code(code)
        console.print("[green]✅ Authentication successful! Token saved.[/green]")
        return True
    except requests.HTTPError as e:
        console.print(f"[red]❌ Auth failed: {e}[/red]")
        return False
