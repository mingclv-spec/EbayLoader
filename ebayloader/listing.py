"""Listing management — create offers and publish listings to eBay."""

import csv
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from ebayloader.api import eBayAPI
from ebayloader.inventory import InventoryManager
from ebayloader.photo import PictureService, batch_resize

console = Console()

OFFER_DEFAULTS = {
    "availableQuantity": 1,
    "listingDescription": "",
    "listingPolicies": {
        "fulfillmentPolicyId": "",
        "paymentPolicyId": "",
        "returnPolicyId": "",
    },
    "pricingSummary": {"price": {"value": "0.00", "currency": "AUD"}},
}


def load_batch_csv(path: Path) -> List[dict]:
    """Load products from CSV. Required columns: sku, title, price, quantity, photo_paths

    Optional: description, condition, brand, mpn, category_id, aspects (JSON string)
    """
    items = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row.get("sku", "").strip()
            if not sku:
                continue

            photo_paths = row.get("photo_paths", "").strip()
            item = {
                "sku": sku,
                "title": row.get("title", "").strip(),
                "description": row.get("description", "").strip(),
                "price": float(row.get("price", 0)),
                "quantity": int(row.get("quantity", 1)),
                "condition": row.get("condition", "NEW").strip(),
                "brand": row.get("brand", "").strip(),
                "mpn": row.get("mpn", "").strip(),
                "category_id": row.get("category_id", "").strip(),
                "photo_paths": [p.strip() for p in photo_paths.split(";") if p.strip()],
                "aspects": {},
            }

            # Parse aspects from JSON string if provided
            aspects_raw = row.get("aspects", "")
            if aspects_raw.strip():
                try:
                    item["aspects"] = json.loads(aspects_raw)
                except json.JSONDecodeError:
                    pass

            items.append(item)
    return items


def load_batch_json(path: Path) -> List[dict]:
    """Load products from JSON file (list or dict with 'items' key)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items", [])
    return []


def load_batch_file(path: Path) -> List[dict]:
    """Auto-detect CSV or JSON and load products."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_batch_csv(path)
    elif suffix == ".json":
        return load_batch_json(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .csv or .json")


class ListingManager:
    """Orchestrates the batch listing process."""

    def __init__(self, api: eBayAPI, config):
        self.api = api
        self.config = config
        self.inventory = InventoryManager(api)
        self.picture_service = PictureService(
            api.auth.get_valid_token(), config.sandbox
        )

    def _prepare_photos(self, items: List[dict], resize_dir: Optional[Path] = None) -> List[dict]:
        """Validate and resize photos for all items."""
        console.print("\n[bold]📸 Processing photos...[/bold]")
        for item in items:
            paths = [Path(p) for p in item.get("photo_paths", [])]
            existing = [p for p in paths if p.exists()]
            if not existing:
                console.print(f"  [yellow]⚠️  No valid photos for {item['sku']}[/yellow]")
                item["_photo_urls"] = []
                continue

            if resize_dir:
                existing = batch_resize(existing, resize_dir)

            # We'll upload in a later step
            item["_resized_paths"] = existing
        return items

    def _upload_photos(self, items: List[dict]) -> List[dict]:
        """Upload photos to eBay Picture Service."""
        console.print("\n[bold]☁️  Uploading photos to eBay...[/bold]")

        site_id = "0"  # Default US site; could be mapped from country
        all_photos = []
        photo_map = {}  # path -> list of (item_idx, ...)

        for idx, item in enumerate(items):
            for p in item.get("_resized_paths", []):
                all_photos.append(p)
                photo_map.setdefault(str(p), []).append(idx)

        if not all_photos:
            return items

        uploaded = self.picture_service.upload_many(all_photos, site_id)

        # Map uploaded URLs back to items
        url_idx = 0
        for item_idx, item in enumerate(items):
            urls = []
            for p in item.get("_resized_paths", []):
                if url_idx < len(uploaded) and uploaded[url_idx]:
                    urls.append(uploaded[url_idx])
                url_idx += 1
            item["_photo_urls"] = urls
            console.print(f"  [green]✓[/green] {item['sku']}: {len(urls)} photo(s) uploaded")

        return items

    def _create_inventory_items(self, items: List[dict]) -> List[dict]:
        """Create inventory items on eBay."""
        console.print("\n[bold]📦 Creating inventory items...[/bold]")
        results = []
        for item in items:
            try:
                result = self.inventory.create_or_replace(
                    item["sku"],
                    {
                        "title": item["title"],
                        "description": item.get("description", ""),
                        "image_urls": item.get("_photo_urls", []),
                        "condition": item.get("condition", "NEW"),
                        "quantity": item.get("quantity", 1),
                        "brand": item.get("brand", ""),
                        "mpn": item.get("mpn", ""),
                        "aspects": item.get("aspects", {}),
                    },
                )
                results.append({"sku": item["sku"], "status": "created", "result": result})
                console.print(f"  [green]✓[/green] {item['sku']}: inventory created")
            except Exception as e:
                results.append({"sku": item["sku"], "status": "error", "error": str(e)})
                console.print(f"  [red]✗[/red] {item['sku']}: {e}")
        return results

    def _build_offer_payload(self, item: dict, policies: dict) -> dict:
        """Build an offer payload for publishing."""
        return {
            "sku": item["sku"],
            "marketplaceId": f"EBAY_{self.config.default_country}",
            "format": "FIXED_PRICE",
            "availableQuantity": item.get("quantity", 1),
            "listingDescription": item.get("description", ""),
            "listingPolicies": policies,
            "pricingSummary": {
                "price": {
                    "value": f"{item['price']:.2f}",
                    "currency": self.config.default_currency,
                }
            },
            "categoryId": item.get("category_id", ""),
            "merchantLocationKey": self.config.merchant_location_key,
        }

    def _get_policies(self) -> dict:
        """Fetch or create default policies."""
        policies = {
            "fulfillmentPolicyId": "",
            "paymentPolicyId": "",
            "returnPolicyId": "",
        }

        for ptype in ["fulfillment_policy", "payment_policy", "return_policy"]:
            api_type = ptype.replace("_", "")
            try:
                existing = self.api.get_policies(f"{api_type}")
                if existing:
                    policies[f"{ptype}Id"] = existing[0].get(f"{ptype}Id", "")
            except Exception as e:
                console.print(f"[yellow]  ⚠️  Could not fetch {ptype}: {e}[/yellow]")
        return policies

    def _create_offers(self, items: List[dict], policies: dict, publish: bool = False):
        """Create offers for inventory items and optionally publish."""
        console.print("\n[bold]📋 Creating offers...[/bold]")
        results = []

        for item in items:
            try:
                offer_payload = self._build_offer_payload(item, policies)
                offer = self.api.create_offer(offer_payload)
                offer_id = offer.get("offerId", "")
                results.append({"sku": item["sku"], "offer_id": offer_id, "status": "created"})
                console.print(f"  [green]✓[/green] {item['sku']}: offer created (ID: {offer_id})")

                if publish and offer_id:
                    pub = self.api.publish_offer(offer_id)
                    listing_id = pub.get("listingId", "")
                    results[-1]["listing_id"] = listing_id
                    results[-1]["status"] = "published"
                    console.print(f"  [green]✓[/green]   → Published! Listing ID: {listing_id}")

            except Exception as e:
                results.append({"sku": item["sku"], "status": "error", "error": str(e)})
                console.print(f"  [red]✗[/red] {item['sku']}: {e}")

        return results

    def run_batch(
        self,
        items: List[dict],
        publish: bool = False,
        resize: bool = True,
        dry_run: bool = False,
    ) -> dict:
        """Full pipeline: photos → inventory → offers → publish."""
        report = {"total": len(items), "steps": {}}

        # Step 1: Prep photos
        resize_dir = Path("./resized_photos") if resize else None
        items = self._prepare_photos(items, resize_dir)
        report["steps"]["photos_prepped"] = len(items)

        if dry_run:
            console.print("\n[yellow]🧪 DRY RUN — no changes made to eBay[/yellow]")
            for item in items:
                console.print(f"  Would list: {item['sku']} - {item['title']} @ ${item['price']:.2f}")
            return report

        # Step 2: Upload photos
        items = self._upload_photos(items)
        report["steps"]["photos_uploaded"] = sum(
            1 for i in items if i.get("_photo_urls")
        )

        # Step 3: Create inventory items
        inv_results = self._create_inventory_items(items)
        report["steps"]["inventory_created"] = sum(
            1 for r in inv_results if r["status"] == "created"
        )

        # Step 4: Create (and publish) offers
        policies = self._get_policies()
        offer_results = self._create_offers(items, policies, publish=publish)
        report["steps"]["offers_created"] = sum(
            1 for r in offer_results if r["status"] in ("created", "published")
        )
        report["steps"]["offers_published"] = sum(
            1 for r in offer_results if r["status"] == "published"
        )

        # Step 5: Summary
        report["results"] = offer_results
        self._print_summary(report)
        return report

    def _print_summary(self, report: dict):
        """Print a results table."""
        table = Table(title="📊 Batch Listing Results")
        table.add_column("SKU", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Offer ID", style="yellow")
        table.add_column("Listing ID", style="blue")

        for r in report.get("results", []):
            status_style = "green" if r["status"] == "published" else (
                "yellow" if r["status"] == "created" else "red"
            )
            table.add_row(
                r["sku"],
                f"[{status_style}]{r['status']}[/{status_style}]",
                r.get("offer_id", "-"),
                r.get("listing_id", "-"),
            )

        console.print(table)
        console.print(f"\n[bold]Summary:[/bold] {report['steps'].get('offers_published', 0)} published, "
                      f"{report['steps'].get('offers_created', 0)} created, "
                      f"{report['total']} total")
