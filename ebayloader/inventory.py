"""Inventory item management — create & manage inventory items via eBay Inventory API."""

from typing import Optional, Dict, Any, List

from ebayloader.api import eBayAPI


class InventoryItem:
    """Represents a single inventory item (SKU-level)."""

    def __init__(self, sku: str, product_data: dict):
        self.sku = sku
        self.product_data = product_data

    def to_api_payload(self) -> dict:
        """Build the Inventory API payload."""
        payload = {
            "sku": self.sku,
            "product": {
                "title": self.product_data.get("title", ""),
                "description": self.product_data.get("description", ""),
                "aspects": self.product_data.get("aspects", {}),
                "brand": self.product_data.get("brand", ""),
                "mpn": self.product_data.get("mpn", ""),
                "imageUrls": self.product_data.get("image_urls", []),
            },
            "condition": self.product_data.get("condition", "NEW"),
            "conditionDescription": self.product_data.get("condition_description", ""),
            "packageWeightAndSize": {
                "dimensions": {
                    "height": self.product_data.get("height", 10),
                    "width": self.product_data.get("width", 10),
                    "length": self.product_data.get("length", 10),
                    "unit": "CENTIMETER",
                },
                "weight": {
                    "value": self.product_data.get("weight", 0.5),
                    "unit": "KILOGRAM",
                },
                "packageType": self.product_data.get("package_type", "MAIL"),
            },
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": self.product_data.get("quantity", 1),
                }
            },
        }
        return payload


class InventoryManager:
    """Manage inventory items via the eBay Inventory API."""

    def __init__(self, api: eBayAPI):
        self.api = api

    def create_or_replace(self, sku: str, item_data: dict) -> dict:
        """Create or replace an inventory item."""
        url = f"{self.api.config.api_base()}/sell/inventory/v1/inventory_item/{sku}"
        session = self.api.session
        resp = session.put(
            url,
            headers=self.api._headers(),
            json=InventoryItem(sku, item_data).to_api_payload(),
        )
        if resp.status_code not in (200, 201, 204):
            resp.raise_for_status()
        return resp.json() if resp.text else {"status": "ok"}

    def bulk_create(self, items: List[dict]) -> List[dict]:
        """Bulk create inventory items."""
        url = f"{self.api.config.api_base()}/sell/inventory/v1/bulk_create_or_replace_inventory_item"
        payload = {
            "requests": [
                {
                    "sku": item.get("sku", ""),
                    "product": {
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "imageUrls": item.get("image_urls", []),
                        "aspects": item.get("aspects", {}),
                        "brand": item.get("brand", ""),
                        "mpn": item.get("mpn", ""),
                    },
                    "condition": item.get("condition", "NEW"),
                    "availability": {
                        "shipToLocationAvailability": {
                            "quantity": item.get("quantity", 1),
                        }
                    },
                }
                for item in items
            ]
        }
        session = self.api.session
        resp = session.post(url, headers=self.api._headers(), json=payload)
        resp.raise_for_status()
        return resp.json().get("responses", [])

    def get_item(self, sku: str) -> Optional[dict]:
        """Get a single inventory item."""
        url = f"{self.api.config.api_base()}/sell/inventory/v1/inventory_item/{sku}"
        resp = self.api.session.get(url, headers=self.api._headers())
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def delete_item(self, sku: str):
        """Delete an inventory item."""
        url = f"{self.api.config.api_base()}/sell/inventory/v1/inventory_item/{sku}"
        resp = self.api.session.delete(url, headers=self.api._headers())
        resp.raise_for_status()
