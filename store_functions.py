import json
from typing import Optional, Dict, List
from opentelemetry import trace
import random

tracer = trace.get_tracer(__name__)

inventory: Dict[str, Dict] = {
    # Breakfast Aisle (A1-A3)
    "SKU001": {"name": "Contoso Cereal", "stock": 15, "category": "Breakfast", "location_id": "A1", "position": 1},
    "SKU002": {"name": "Northwind Oatmeal", "stock": 12, "category": "Breakfast", "location_id": "A1", "position": 2},
    "SKU003": {"name": "Adventure Granola", "stock": 8, "category": "Breakfast", "location_id": "A2", "position": 0},
    "SKU004": {"name": "Fabrikam Pancake Mix", "stock": 10, "category": "Breakfast", "location_id": "A2", "position": 1},
    
    # Dairy Section (B1-B3)
    "SKU010": {"name": "Fabrikam Milk (1L)", "stock": 20, "category": "Dairy", "location_id": "B1", "position": 0},
    "SKU011": {"name": "Contoso Yogurt", "stock": 18, "category": "Dairy", "location_id": "B1", "position": 1},
    "SKU012": {"name": "Adventure Cheese", "stock": 15, "category": "Dairy", "location_id": "B2", "position": 0},
    "SKU013": {"name": "Northwind Butter", "stock": 12, "category": "Dairy", "location_id": "B2", "position": 1},
    
    # Beverages (C1-C3)
    "SKU020": {"name": "Northwind Cola (Can)", "stock": 48, "category": "Drinks", "location_id": "C1", "position": 0},
    "SKU021": {"name": "Adventure Water (1L)", "stock": 36, "category": "Drinks", "location_id": "C1", "position": 1},
    "SKU022": {"name": "Fabrikam Juice (2L)", "stock": 15, "category": "Drinks", "location_id": "C2", "position": 0},
    "SKU023": {"name": "Contoso Energy Drink", "stock": 24, "category": "Drinks", "location_id": "C2", "position": 1},
    
    # Produce Section (P1-P3)
    "SKU030": {"name": "Adatum Apples (Bag)", "stock": 20, "category": "Produce", "location_id": "P1", "position": 0},
    "SKU031": {"name": "Fabrikam Bananas", "stock": 25, "category": "Produce", "location_id": "P1", "position": 1},
    "SKU032": {"name": "Contoso Oranges (Net)", "stock": 15, "category": "Produce", "location_id": "P2", "position": 0},
    "SKU033": {"name": "Northwind Carrots", "stock": 18, "category": "Produce", "location_id": "P2", "position": 1},
    
    # Household (H1-H3)
    "SKU040": {"name": "Woodgrove Cleaning Spray", "stock": 14, "category": "Household", "location_id": "H1", "position": 0},
    "SKU041": {"name": "Adventure Paper Towels", "stock": 22, "category": "Household", "location_id": "H1", "position": 1},
    "SKU042": {"name": "Contoso Dish Soap", "stock": 16, "category": "Household", "location_id": "H2", "position": 0},
    "SKU043": {"name": "Fabrikam Laundry Det.", "stock": 10, "category": "Household", "location_id": "H2", "position": 1}
}

shelf_layouts: Dict[str, List[List[Optional[str]]]] = {
    # Breakfast Aisle (A1-A3) - 4 levels per shelf
    "A1": [ ["SKU001", "SKU001", "SKU002"],  # Top shelf
            ["SKU001", "SKU002", "SKU002"],  # Eye level
            ["SKU001", "SKU002", None],      # Waist level
            [None, None, None] ],            # Bottom shelf
            
    "A2": [ ["SKU003", "SKU003", "SKU004"],
            ["SKU003", "SKU004", "SKU004"],
            ["SKU004", None, None],
            [None, None, None] ],
    
    # Dairy Section (B1-B3)
    "B1": [ ["SKU010", "SKU010", "SKU011"],
            ["SKU010", "SKU011", "SKU011"],
            ["SKU010", "SKU011", None],
            ["SKU010", None, None] ],  # Bottom shelf cooler
            
    "B2": [ ["SKU012", "SKU012", "SKU013"],
            ["SKU012", "SKU013", "SKU013"],
            ["SKU012", "SKU013", None],
            [None, None, None] ],
    
    # Beverages (C1-C3)
    "C1": [ ["SKU020", "SKU020", "SKU021"],
            ["SKU020", "SKU021", "SKU021"],
            ["SKU020", "SKU021", None],
            ["SKU020", "SKU021", None] ],  # Heavy items on bottom
            
    "C2": [ ["SKU022", "SKU022", "SKU023"],
            ["SKU022", "SKU023", "SKU023"],
            ["SKU022", "SKU023", None],
            [None, None, None] ],

    "C3": [ ["SKU022", "SKU022", "SKU023"],
            ["SKU022", "SKU023", "SKU023"],
            ["SKU022", "SKU023", None],
            [None, None, None] ],
    
    # Produce Section (P1-P3)
    "P1": [ ["SKU030", "SKU030", "SKU031"],
            ["SKU030", "SKU031", "SKU031"],
            ["SKU030", "SKU031", None],
            [None, None, None] ],
            
    "P2": [ ["SKU032", "SKU032", "SKU033"],
            ["SKU032", "SKU033", "SKU033"],
            ["SKU032", "SKU033", None],
            [None, None, None] ],
    
    # Household (H1-H3)
    "H1": [ ["SKU040", "SKU040", "SKU041"],
            ["SKU040", "SKU041", "SKU041"],
            ["SKU040", "SKU041", None],
            ["SKU040", None, None] ],  # Heavy cleaning supplies on bottom
            
    "H2": [ ["SKU042", "SKU042", "SKU043"],
            ["SKU042", "SKU043", "SKU043"],
            ["SKU042", "SKU043", None],
            ["SKU042", None, None] ]   # Heavy detergents on bottom
}

storage_requests: Dict[str, Dict] = {}

def check_item_stock(item_id: str) -> str:
    with tracer.start_as_current_span("check_item_stock") as span:
        span.set_attribute("item_id", item_id)
        item = inventory.get(item_id)
        if item:
            result = {"item_id": item_id, "name": item["name"], "stock": item["stock"]}
            span.set_attribute("result.stock", item["stock"])
        else:
            result = {"error": f"Item ID {item_id} not found."}
            span.set_attribute("error", result["error"])
        return json.dumps(result)

def find_item_location(item_id: str) -> str:
    with tracer.start_as_current_span("find_item_location") as span:
        span.set_attribute("item_id", item_id)
        item = inventory.get(item_id)
        if item and item.get("location_id"):
            result = {
                "item_id": item_id,
                "name": item["name"],
                "location_id": item["location_id"],
                "position": item.get("position", "N/A")
            }
            span.set_attribute("result.location_id", result["location_id"])
            span.set_attribute("result.position", result["position"])
        elif item:
             result = {"error": f"Location for Item ID {item_id} not defined."}
             span.set_attribute("error", result["error"])
        else:
            result = {"error": f"Item ID {item_id} not found."}
            span.set_attribute("error", result["error"])
        return json.dumps(result)

def get_shelf_layout(shelf_id: str) -> str:
    with tracer.start_as_current_span("get_shelf_layout") as span:
        span.set_attribute("shelf_id", shelf_id)
        layout = shelf_layouts.get(shelf_id)
        if layout:
            representation = f"### Layout for Shelf {shelf_id}\n\n"
            representation += "| Position | 1 | 2 | 3 |\n"
            representation += "|----------|---|---|---|\n"
            for i, shelf in enumerate(layout):
                shelf_repr = []
                for item_id in shelf:
                    if item_id and item_id in inventory:
                        name = inventory[item_id]['name']
                        # Increase the length limit to 20 characters and handle formatting
                        shelf_repr.append(name[:20].ljust(20))  # Use ljust to ensure consistent width
                    elif item_id:
                        shelf_repr.append(item_id[:20].ljust(20))
                    else:
                        shelf_repr.append("Empty".ljust(20))
                representation += f"| Shelf {i+1} | {' | '.join(shelf_repr)} |\n"
            result = {"shelf_id": shelf_id, "layout_visual": representation.strip()}
            span.set_attribute("result.shelf_count", len(layout))
        else:
            result = {"error": f"Shelf ID {shelf_id} not found."}
            span.set_attribute("error", result["error"])
        return json.dumps(result)

def request_item_from_storage(item_id: str, quantity: int, target_location_id: str) -> str:
    with tracer.start_as_current_span("request_item_from_storage") as span:
        span.set_attribute("item_id", item_id)
        span.set_attribute("quantity", quantity)
        span.set_attribute("target_location_id", target_location_id)

        if item_id not in inventory:
            result = {"error": f"Item ID {item_id} not found in inventory system."}
            span.set_attribute("error", result["error"])
            return json.dumps(result)
        if target_location_id not in shelf_layouts:
             result = {"error": f"Target Shelf ID {target_location_id} does not exist."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)
        if quantity <= 0:
             result = {"error": "Quantity must be positive."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)

        request_id = f"REQ{random.randint(1000, 9999)}"
        storage_requests[request_id] = {
            "item_id": item_id,
            "quantity": quantity,
            "target_location": target_location_id,
            "status": "Pending"
        }
        result = {"request_id": request_id, "status": "Pending", "message": f"Request {request_id} created for {quantity} of {inventory[item_id]['name']} to shelf {target_location_id}."}
        span.set_attribute("result.request_id", request_id)
        return json.dumps(result)

def check_delivery_status(request_id: str) -> str:
    with tracer.start_as_current_span("check_delivery_status") as span:
        span.set_attribute("request_id", request_id)
        request = storage_requests.get(request_id)
        if request:
            if request["status"] == "Pending" and random.random() > 0.7:
                request["status"] = "In Transit"
            elif request["status"] == "In Transit" and random.random() > 0.5:
                 request["status"] = "Delivered"

            result = {"request_id": request_id, "status": request["status"], "details": request}
            span.set_attribute("result.status", request["status"])
        else:
            result = {"error": f"Request ID {request_id} not found."}
            span.set_attribute("error", result["error"])
        return json.dumps(result)

def get_items_needing_restock(category: Optional[str] = None, min_stock_level: int = 5) -> str:
    with tracer.start_as_current_span("get_items_needing_restock") as span:
        span.set_attribute("category_filter", category if category else "None")
        span.set_attribute("min_stock_level", min_stock_level)

        low_stock_items = []
        for item_id, item_data in inventory.items():
            if item_data["stock"] < min_stock_level:
                if category is None or item_data.get("category") == category:
                    low_stock_items.append({
                        "item_id": item_id,
                        "name": item_data["name"],
                        "current_stock": item_data["stock"],
                        "location_id": item_data.get("location_id", "N/A")
                    })

        result = {"low_stock_items": low_stock_items, "count": len(low_stock_items)}
        span.set_attribute("result.count", len(low_stock_items))
        return json.dumps(result)

def update_inventory_count(item_id: str, quantity_change: int, reason: str = "Restock") -> str:
    with tracer.start_as_current_span("update_inventory_count") as span:
        span.set_attribute("item_id", item_id)
        span.set_attribute("quantity_change", quantity_change)
        span.set_attribute("reason", reason)

        item = inventory.get(item_id)
        if item:
            original_stock = item["stock"]
            item["stock"] += quantity_change
            if item["stock"] < 0: item["stock"] = 0
            result = {
                "item_id": item_id,
                "name": item["name"],
                "previous_stock": original_stock,
                "new_stock": item["stock"],
                "change": quantity_change,
                "reason": reason
            }
            span.set_attribute("result.new_stock", item["stock"])
        else:
            result = {"error": f"Item ID {item_id} not found."}
            span.set_attribute("error", result["error"])
        return json.dumps(result)

def mark_item_restocked(item_id: str, shelf_id: str, shelf_index: int, position_index: int, quantity: int) -> str:
    with tracer.start_as_current_span("mark_item_restocked") as span:
        span.set_attribute("item_id", item_id)
        span.set_attribute("shelf_id", shelf_id)
        span.set_attribute("shelf_index", shelf_index)
        span.set_attribute("position_index", position_index)
        span.set_attribute("quantity", quantity)

        if item_id not in inventory:
            result = {"error": f"Item ID {item_id} not found."}
            span.set_attribute("error", result["error"])
            return json.dumps(result)
        if shelf_id not in shelf_layouts:
            result = {"error": f"Shelf ID {shelf_id} not found."}
            span.set_attribute("error", result["error"])
            return json.dumps(result)
        if not (0 <= shelf_index < len(shelf_layouts[shelf_id])):
             result = {"error": f"Invalid shelf index {shelf_index} for Shelf {shelf_id}."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)
        if not (0 <= position_index < len(shelf_layouts[shelf_id][shelf_index])):
             result = {"error": f"Invalid position index {position_index} for Shelf {shelf_id}, Shelf {shelf_index+1}."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)
        if quantity <= 0:
             result = {"error": "Quantity must be positive."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)

        shelf_layouts[shelf_id][shelf_index][position_index] = item_id
        update_response = update_inventory_count(item_id, quantity, reason=f"Restocked on {shelf_id}-S{shelf_index+1}-P{position_index+1}")
        update_data = json.loads(update_response)

        if "error" in update_data:
             result = {"error": f"Failed to update inventory: {update_data['error']}", "layout_updated": True}
             span.set_attribute("error", result["error"])
        else:
            result = {
                "message": f"Successfully restocked {quantity} of {inventory[item_id]['name']} ({item_id}) at {shelf_id}-S{shelf_index+1}-P{position_index+1}.",
                "inventory_update": update_data
            }
            span.set_attribute("result.message", "Success")

        return json.dumps(result)

def log_damaged_item(item_id: str, quantity: int, notes: Optional[str] = None) -> str:
    with tracer.start_as_current_span("log_damaged_item") as span:
        span.set_attribute("item_id", item_id)
        span.set_attribute("quantity", quantity)
        if notes: span.set_attribute("notes", notes)

        if quantity <= 0:
             result = {"error": "Quantity must be positive."}
             span.set_attribute("error", result["error"])
             return json.dumps(result)

        update_response = update_inventory_count(item_id, -quantity, reason=f"Damaged ({notes if notes else 'No details'})")
        update_data = json.loads(update_response)

        if "error" in update_data:
            result = {"error": f"Failed to log damage: {update_data['error']}"}
            span.set_attribute("error", result["error"])
        else:
             result = {
                "message": f"Successfully logged {quantity} damaged units of {inventory[item_id]['name']} ({item_id}).",
                "inventory_update": update_data
             }
             span.set_attribute("result.message", "Success")
        return json.dumps(result)

def get_store_layout_overview() -> str:
    with tracer.start_as_current_span("get_store_layout_overview") as span:
        shelf_ids = list(shelf_layouts.keys())
        result = {"shelf_ids": shelf_ids, "count": len(shelf_ids)}
        span.set_attribute("result.count", len(shelf_ids))
        return json.dumps(result)

def identify_and_restock_item_from_image(image_data: str, quantity: int) -> str:
    with tracer.start_as_current_span("identify_and_restock_item_from_image") as span:
        span.set_attribute("simulated_input_type", "item_id_from_image_data")
        span.set_attribute("quantity", quantity)

        item_id = image_data
        span.set_attribute("identified_item_id", item_id)

        if not item_id:
            result = {"error": "Could not identify item from image data (simulation)." }
            span.set_attribute("error", result["error"])
            return json.dumps(result)

        location_response = find_item_location(item_id)
        location_data = json.loads(location_response)

        if "error" in location_data:
            result = {"error": f"Could not find location for identified item {item_id}: {location_data['error']}"}
            span.set_attribute("error", result["error"])
            return json.dumps(result)

        shelf_id = location_data.get("location_id")

        shelf_idx, pos_idx = -1, -1
        if shelf_id in shelf_layouts:
            for r_idx, shelf in enumerate(shelf_layouts[shelf_id]):
                try:
                    p_idx = shelf.index(item_id)
                    shelf_idx, pos_idx = r_idx, p_idx
                    break
                except ValueError:
                    if shelf_idx == -1:
                        try:
                            p_idx = shelf.index(None)
                            shelf_idx, pos_idx = r_idx, p_idx
                        except ValueError:
                            continue

        if shelf_idx == -1 or pos_idx == -1:
            result = {"error": f"Could not determine specific shelf/position for item {item_id} on shelf {shelf_id}. Layout might need update."}
            span.set_attribute("error", result["error"])
            return json.dumps(result)

        span.set_attribute("determined_shelf_index", shelf_idx)
        span.set_attribute("determined_position_index", pos_idx)

        restock_response = mark_item_restocked(item_id, shelf_id, shelf_idx, pos_idx, quantity)
        restock_data = json.loads(restock_response)

        if "error" in restock_data:
            result = {"error": f"Failed to restock after identification: {restock_data['error']}"}
            span.set_attribute("error", result["error"])
        else:
            result = {
                "message": f"Simulated vision identification and restocking complete for {item_id}.",
                "restock_details": restock_data
                }
            span.set_attribute("result.message", "Success")

        return json.dumps(result)