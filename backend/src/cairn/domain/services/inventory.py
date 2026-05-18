import copy

from cairn.types import InventoryItem


def find_item(inventory: list[InventoryItem], item_name: str) -> InventoryItem | None:
    """Find an inventory item by name or srd_index (case-insensitive)."""
    name_lower = item_name.lower()
    for item in inventory:
        if item.get("name", "").lower() == name_lower:
            return item
        if item.get("srd_index", "").lower() == name_lower:
            return item
    return None


def copy_inventory(items: list[InventoryItem]) -> list[InventoryItem]:
    """Deep-copy inventory so SQLAlchemy detects mutation on reassignment."""
    return copy.deepcopy(items)


def srd_index_of(item: InventoryItem) -> str:
    """Derive the SRD index from an item: prefer explicit srd_index, fall back to name slug."""
    return item.get("srd_index") or item.get("name", "").lower().replace(" ", "-")
