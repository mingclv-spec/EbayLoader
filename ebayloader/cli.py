#!/usr/bin/env python3
"""EbayLoader — CLI entry point using Click."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ebayloader import __version__
from ebayloader.config import Config, ENV_MAP
from ebayloader.auth import eBayAuth, login_flow
from ebayloader.api import eBayAPI
from ebayloader.listing import ListingManager, load_batch_file

console = Console()


# ── Shared options ────────────────────────────────────────────────

def common_options(f):
    """Reusable config/debug options."""
    f = click.option("--config", "-c", default=None, help="Path to config YAML file")(f)
    f = click.option("--verbose", "-v", is_flag=True, help="Verbose output")(f)
    return f


def get_config(ctx) -> Config:
    """Load config from ctx, with helpful error."""
    config_path = ctx.params.get("config")
    cfg = Config(config_path)
    valid = cfg.validate()
    if not valid:
        console.print("[yellow]Run [bold]ebay config show[/bold] to see what's needed.[/yellow]")
    return cfg


# ── CLI Group ─────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="ebayloader")
@common_options
@click.pass_context
def cli(ctx, config, verbose):
    """EbayLoader — Batch upload products to sell on eBay.

    Load products from a CSV/JSON file, upload photos, create inventory
    items, and publish listings — all in one go.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


# ── Auth Commands ─────────────────────────────────────────────────

@cli.group()
def auth():
    """eBay OAuth authentication."""


@auth.command("login")
@click.pass_context
def auth_login(ctx):
    """Authenticate with eBay via OAuth."""
    cfg = get_config(ctx)
    if login_flow(cfg):
        console.print("[green]✅ You're authenticated! Run [bold]ebay batch list[/bold] to get started.[/green]")
    else:
        sys.exit(1)


@auth.command("refresh")
@click.pass_context
def auth_refresh(ctx):
    """Refresh the access token."""
    cfg = get_config(ctx)
    ebay_auth = eBayAuth(cfg)
    try:
        token = ebay_auth.refresh_token()
        console.print("[green]✅ Token refreshed successfully![/green]")
    except Exception as e:
        console.print(f"[red]❌ Refresh failed: {e}[/red]")
        sys.exit(1)


@auth.command("status")
@click.pass_context
def auth_status(ctx):
    """Check authentication status."""
    cfg = get_config(ctx)
    ebay_auth = eBayAuth(cfg)
    if ebay_auth.is_authenticated():
        console.print("[green]✅ Authenticated[/green]")
    else:
        console.print("[yellow]⚠️  Not authenticated — run [bold]ebay auth login[/bold][/yellow]")


# ── Config Commands ───────────────────────────────────────────────

@cli.group()
def config():
    """Manage EbayLoader configuration."""


@config.command("show")
@click.pass_context
def config_show(ctx):
    """Show current configuration."""
    cfg = get_config(ctx)
    table = Table(title="⚙️  Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Source", style="yellow")

    for env_key, dot_key in ENV_MAP.items():
        val = cfg._resolve(dot_key)
        in_env = env_key in __import__("os").environ
        source = "env" if in_env else "file" if val else "missing"
        style = "green" if val else "red"
        table.add_row(dot_key, f"[{style}]{val or '—'}[/{style}]", source)

    console.print(table)


@config.command("init")
@click.option("--output", "-o", default="ebay_config.yaml", help="Output path")
@click.pass_context
def config_init(ctx, output):
    """Generate a sample config file to get started."""
    sample = """# EbayLoader Configuration
# Get your API keys from: https://developer.ebay.com/

ebay:
  api:
    # Required — eBay Developer Program credentials
    app_id: "YOUR_APP_ID"
    cert_id: "YOUR_CERT_ID"
    dev_id: "YOUR_DEV_ID"
    redirect_uri: "https://localhost/signin"
    environment: "sandbox"  # sandbox | production
    token_path: "~/.ebayloader/token.json"

  seller:
    merchant_location_key: ""
    currency: "AUD"
    country: "AU"
    default_condition: "NEW"
    listing_duration: "GTC"

# ── Setup Instructions ──────────────────────────────────────────
# 1. Go to https://developer.ebay.com/ — sign up for a free account
# 2. Create an application to get App ID, Cert ID, and Dev ID
# 3. Set your OAuth redirect URI to: https://localhost/signin
# 4. Copy those values above
# 5. Run: ebay auth login
# 6. Run: ebay batch load sample_batch.csv
"""
    out = Path(output)
    if out.exists():
        if not click.confirm(f"⚠️  {out} exists. Overwrite?"):
            return
    out.write_text(sample)
    console.print(f"[green]✅ Sample config written to {out}[/green]")
    console.print("   Edit it with your eBay API keys, then run [bold]ebay auth login[/bold]")


# ── Inventory Commands ────────────────────────────────────────────

@cli.group()
def inventory():
    """Manage eBay inventory items."""


@inventory.command("list")
@click.pass_context
def inventory_list(ctx):
    """List existing inventory items (TODO)."""
    cfg = get_config(ctx)
    api = eBayAPI(cfg)
    # eBay doesn't have a simple list endpoint — requires paginated search
    console.print("[yellow]Use [bold]ebay bat ch load[/bold] to see current items in your batch file.[/yellow]")


@inventory.command("delete")
@click.argument("sku")
@click.pass_context
def inventory_delete(ctx, sku):
    """Delete an inventory item by SKU."""
    cfg = get_config(ctx)
    api = eBayAPI(cfg)
    from ebayloader.inventory import InventoryManager
    mgr = InventoryManager(api)
    try:
        mgr.delete_item(sku)
        console.print(f"[green]✅ Deleted {sku}[/green]")
    except Exception as e:
        console.print(f"[red]❌ Failed: {e}[/red]")


# ── Batch Commands ────────────────────────────────────────────────

@cli.group()
def batch():
    """Batch listing operations."""


@batch.command("load")
@click.argument("file", type=click.Path(exists=True))
@click.option("--publish", is_flag=True, help="Publish listings immediately")
@click.option("--no-resize", is_flag=True, help="Skip photo resizing")
@click.option("--dry-run", is_flag=True, help="Preview without making any changes")
@click.pass_context
def batch_load(ctx, file, publish, no_resize, dry_run):
    """Load products from CSV/JSON and list on eBay."""
    cfg = get_config(ctx)
    api = eBayAPI(cfg)

    console.print(f"[bold]🚀 EbayLoader — Batch Listing[/bold]\n")

    # Load items
    console.print(f"📂 Loading from: {file}")
    try:
        items = load_batch_file(Path(file))
    except Exception as e:
        console.print(f"[red]❌ Failed to load file: {e}[/red]")
        sys.exit(1)

    if not items:
        console.print("[red]❌ No items found in file.[/red]")
        sys.exit(1)

    console.print(f"   Found [bold]{len(items)}[/bold] item(s)\n")

    # Preview
    table = Table(title="📋 Items to List")
    table.add_column("SKU", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Price", style="green")
    table.add_column("Qty", style="yellow")
    table.add_column("Photos", style="blue")

    for item in items:
        table.add_row(
            item.get("sku", ""),
            item.get("title", "")[:40],
            f"${item.get('price', 0):.2f}",
            str(item.get("quantity", 1)),
            str(len(item.get("photo_paths", []))),
        )
    console.print(table)

    if dry_run:
        console.print("\n[yellow]🧪 DRY RUN MODE[/yellow]")

    if not click.confirm("\nProceed?"):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Run the pipeline
    manager = ListingManager(api, cfg)
    report = manager.run_batch(
        items,
        publish=publish,
        resize=not no_resize,
        dry_run=dry_run,
    )

    console.print(f"\n[bold green]✅ Done![/bold green]")


@batch.command("template")
@click.option("--output", "-o", default="sample_batch.csv", help="Output path")
def batch_template(output):
    """Generate a sample CSV template for batch listings."""
    sample = """sku,title,description,price,quantity,condition,brand,mpn,category_id,photo_paths,aspects
SKU001,Example Product - Black,A great product description,29.99,10,NEW,AcmeBrand,MPN001,9355,photos/img1.jpg;photos/img2.jpg,"{""Color"":[""Black""],""Size"":[""M""]}"
SKU002,Example Product - White,Another description,34.99,5,NEW,AcmeBrand,MPN002,9355,photos/img3.jpg,"{""Color"":[""White""],""Size"":[""L""]}"
"""
    out = Path(output)
    out.write_text(sample)
    console.print(f"[green]✅ Sample CSV written to {out}[/green]")
    console.print("   Edit it with your products, then run [bold]ebay batch load sample_batch.csv[/bold]")


# ── Help Command ──────────────────────────────────────────────────

@cli.command("guide")
def show_guide():
    """Show a quick-start guide."""
    guide = """
[bold cyan]🚀 EbayLoader Quick Start Guide[/bold cyan]

[bold]1. Get eBay API Keys[/bold]
   - Go to https://developer.ebay.com/
   - Create an app → get App ID, Cert ID, Dev ID
   - Set redirect URI to: https://localhost/signin

[bold]2. Configure[/bold]
   $ ebay config init        # Generate config file
   # Edit ebay_config.yaml with your keys

[bold]3. Authenticate[/bold]
   $ ebay auth login         # OAuth in browser + paste code
   $ ebay auth status        # Verify it worked

[bold]4. Prepare Your Products[/bold]
   $ ebay batch template     # Generate sample CSV
   # Edit sample_batch.csv with your products + photos

[bold]5. List 'em[/bold]
   $ ebay batch load sample_batch.csv         # Dry run preview
   $ ebay batch load sample_batch.csv --publish  # Go live!

[bold]Tips:[/bold]
   - Use --dry-run first to preview without charges
   - Use --publish to list immediately (instead of draft)
   - Start with sandbox (ebay.api.environment: sandbox)
   - Photos resize automatically to 1600px max

[link=https://developer.ebay.com/api-docs/sell/inventory/overview.html]eBay Inventory API Docs[/link]
"""
    console.print(guide)


# ── Main ──────────────────────────────────────────────────────────

def main():
    cli()


if __name__ == "__main__":
    main()
