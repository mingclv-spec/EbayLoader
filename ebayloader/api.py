"""eBay API client wrapping REST calls."""

import time
from typing import Optional, List, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ebayloader.auth import eBayAuth
from ebayloader.config import Config


class eBayAPI:
    """Low-level eBay REST API client with retry + auth handling."""

    def __init__(self, config: Config):
        self.config = config
        self.auth = eBayAuth(config)
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retries)
            self._session.mount("https://", adapter)
        return self._session

    def _headers(self, content_type: str = "application/json") -> dict:
        token = self.auth.get_valid_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": f"EBAY_{self.config.default_country}",
        }

    def _url(self, path: str) -> str:
        return f"{self.config.api_base()}{path}"

    # ── Inventory API ─────────────────────────────────────────────

    def get_or_create_location(self, location_key: str, location_data: dict) -> dict:
        """Ensure a merchant location exists (required for inventory)."""
        url = self._url(f"/sell/inventory/v1/location/{location_key}")
        resp = self.session.put(
            url,
            headers=self._headers(),
            json=location_data,
        )
        if resp.status_code not in (200, 204):
            resp.raise_for_status()
        return resp.json() if resp.text else {}

    def create_offer(self, offer_data: dict) -> dict:
        """Create an eBay offer (listing)."""
        url = self._url("/sell/inventory/v1/offer")
        resp = self.session.post(url, headers=self._headers(), json=offer_data)
        resp.raise_for_status()
        return resp.json()

    def publish_offer(self, offer_id: str) -> dict:
        """Publish a draft offer to make it live on eBay."""
        url = self._url(f"/sell/inventory/v1/offer/{offer_id}/publish")
        resp = self.session.post(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def bulk_create_offer(self, offers: List[dict]) -> List[dict]:
        """Bulk create offers (eBay batch API)."""
        url = self._url("/sell/inventory/v1/bulk_create_offer")
        resp = self.session.post(
            url,
            headers=self._headers(),
            json={"requests": [{"offer": o} for o in offers]},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("responses", [])

    def bulk_publish_offer(self, offer_ids: List[str]) -> List[dict]:
        """Bulk publish offers."""
        url = self._url("/sell/inventory/v1/bulk_publish_offer")
        resp = self.session.post(
            url,
            headers=self._headers(),
            json={"requests": [{"offerId": oid} for oid in offer_ids]},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("responses", [])

    def get_listing_fees(self, offer_ids: List[str]) -> dict:
        """Get listing fees before publishing."""
        url = self._url("/sell/inventory/v1/offer/get_listing_fees")
        # For bulk: use individual calls — eBay lists this as single only
        fees = {}
        for oid in offer_ids:
            resp = self.session.get(
                self._url(f"/sell/inventory/v1/offer/{oid}/listing_fees"),
                headers=self._headers(),
            )
            if resp.ok:
                fees[oid] = resp.json()
        return fees

    # ── Catalog API ───────────────────────────────────────────────

    def search_catalog(self, query: str, limit: int = 5) -> List[dict]:
        """Search eBay catalog for product references."""
        url = self._url("/commerce/catalog/v1/product_summary/search")
        resp = self.session.get(
            url,
            headers=self._headers(),
            params={"q": query, "limit": limit},
        )
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("productSummaries", [])

    # ── Taxonomy API ──────────────────────────────────────────────

    def get_categories(self, top_only: bool = True) -> List[dict]:
        """Get eBay category tree."""
        url = self._url(f"/commerce/taxonomy/v1/category_tree/{self.config.default_country}")
        params = {}
        if top_only:
            params["category_tree_level_limit"] = 2
        resp = self.session.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        tree = resp.json()
        return tree.get("rootCategoryNode", {}).get("childCategoryTreeNodes", [])

    def get_category_aspects(self, category_id: str) -> List[dict]:
        """Get required item specifics for a category."""
        tree_id = self._get_category_tree_id()
        url = self._url(
            f"/commerce/taxonomy/v1/category_tree/{tree_id}"
            f"/get_item_aspects_for_category"
        )
        resp = self.session.get(
            url,
            headers=self._headers(),
            params={"category_id": category_id},
        )
        resp.raise_for_status()
        return resp.json().get("aspects", [])

    def _get_category_tree_id(self) -> str:
        url = self._url(f"/commerce/taxonomy/v1/category_tree/{self.config.default_country}")
        resp = self.session.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json().get("categoryTreeId", "")

    # ── Fulfillment / Orders ──────────────────────────────────────

    def get_orders(self, limit: int = 50) -> List[dict]:
        """Get recent orders."""
        url = self._url("/sell/fulfillment/v1/order")
        resp = self.session.get(
            url, headers=self._headers(), params={"limit": limit}
        )
        resp.raise_for_status()
        return resp.json().get("orders", [])

    # ── Account API ───────────────────────────────────────────────

    def get_policies(self, policy_type: str) -> List[dict]:
        """Get seller policies: 'returnPolicy', 'fulfillmentPolicy', 'paymentPolicy'."""
        url = self._url(f"/sell/account/v1/{policy_type}")
        resp = self.session.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json().get(f"{policy_type}s", [])

    def create_fulfillment_policy(self, policy_data: dict) -> dict:
        url = self._url("/sell/account/v1/fulfillment_policy/")
        resp = self.session.post(url, headers=self._headers(), json=policy_data)
        resp.raise_for_status()
        return resp.json()
