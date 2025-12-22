from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient, DESCENDING, ASCENDING
from bson.objectid import ObjectId
from datetime import datetime, timedelta, timezone
from flask_cors import CORS
import os
import re

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://adventistech2025:XOGhPBZxi0gDSPNO@cluster0.awnrusw.mongodb.net/OptiMES40"
client = MongoClient(MONGO_URI)
db = client["OptiMES40"]
permit_collection = db["permits"]

# Scenario → Collections Map
SCENARIO_COLLECTION_MAP = {
    "hazard warnings": ["fires", "gasleakages", "missingfiredatas"],
    "worker health & safety": ["slips", "ppekits"],
    "compliance policies": ["occupancies", "unauthorizedentries"]
}
ALL_COLLECTIONS = [col for cols in SCENARIO_COLLECTION_MAP.values() for col in cols]

# Inventory Collections
INVENTORY_COLLECTIONS = {
    "categories": db["inventorycategories"],
    "locations": db["inventorylocations"],
    "products": db["inventoryproducts"],
    "projects": db["inventoryprojects"],
    "suppliers": db["inventorysuppliers"],
    "stocks": db["stocks"],
    "distributions": db["inventorydistributions"]
}

# Maintenance & Asset Management Collections
MAINTENANCE_COLLECTIONS = {
    "equipments": db["equipments"],
    "groups": db["groups"],
    "makes": db["makes"],
    "locations": db["locations"],
    "suppliers": db["suppliers"],
    "workorders": db["workorders"],
    "workrequests": db["workrequests"],
    "spareparts": db["spareparts"]
}

# Maintenance Keywords - More specific to avoid confusion
MAINTENANCE_SPECIFIC_KEYWORDS = [
    "cmms", "pulse", "maintenance", "equipment", "asset", "workorder", "work request",
    "spare part", "sparepart", "breakdown", "repair", "service",
    "preventive", "corrective", "working", "under maintenance",
    "downtime", "uptime", "failure", "mtbf", "mttr", "warranty",
    "installation", "due date", "completed", "in progress",
    "closed", "assigned", "technician", "equipment id", "workorder id",
    "sparepart code", "model", "serial", "workorder pending", "workorders pending"
]

# Permit Keywords - VERY SPECIFIC
PERMIT_SPECIFIC_KEYWORDS = [
    "workpermit", "work permit", "permit", "pw-", "approval",
    "approver", "extension", "declaration", "risk assessment",
    "worker assignment", "work type", "form location",
    "permit pending", "pending permits", "permit status",
    "work permit pending", "workpermit pending"
]

# Inventory Keywords
INVENTORY_KEYWORDS = [
    "inventory", "stock", "product", "category", "categories", "material",
    "item", "warehouse", "rack", "storage", "quantity", "price", "part",
    "bhel", "electronics", "laptop", "capacity", "movement", "distribution",
    "transfer", "issue", "receive", "available", "vacant", "empty", "space",
    "utilization", "inventory location", "inventory supplier", "inventory project",
    "supplier", "suppliers", "vendor"
]

# Production & Energy Query Buttons
PRODUCTION_ENERGY_BUTTONS = [
    {"text": "What is the production today?", "action": "What is the production today?"},
    {"text": "Show me today's production report", "action": "Show me today's production report"},
    {"text": "Which shift had the lowest production?", "action": "Which shift had the lowest production?"},
    {"text": "What is the energy cost?", "action": "What is the energy cost?"},
    {"text": "Show power consumption cost", "action": "Show power consumption cost"},
    {"text": "What is the electricity bill?", "action": "What is the electricity bill?"},
    {"text": "Energy consumption patterns", "action": "Energy consumption patterns"},
]

# Inventory Query Buttons
INVENTORY_BUTTONS = [
    {"text": "Find product [name/ID]", "action": "Find product "},
    {"text": "Show low stock products", "action": "Show low stock products"},
    {"text": "Show all suppliers", "action": "Show all suppliers"},
    {"text": "Show all categories", "action": "Show all categories"},
    {"text": "What are the recent stock movements?", "action": "What are the recent stock movements?"},
    {"text": "What locations are available?", "action": "inventory what locations are available?"}
]

# Maintenance Query Buttons
MAINTENANCE_BUTTONS = [
    # {"text": "CMMS Help", "action": "cmms"},
    {"text": "Workorder status summary", "action": "Workorder status summary"},
    {"text": "Show all equipment", "action": "Show all equipment"},
    {"text": "Equipment by status", "action": "Equipment status working"},
    # {"text": "Find workorder by ID", "action": "Find workorder ID:"},  # Prompt text
    {"text": "Show all spare parts", "action": "Show all spare parts"},
    {"text": "Pending workorders", "action": "Pending workorders"},
    {"text": "Completed workorders", "action": "Completed workorders"},
    # {"text": "Equipment under maintenance", "action": "Equipment under maintenance"}
]

# Emoji mapping
EMOJI_MAP = {
    "priority": "⚠️", "person_count_status": "👥", "vacancy_status": "💺",
    "vacant_count_duration": "⏳", "person_count_duration": "⏱️", "exceeds_compliance_policy": "🚫",
    "fire_detected": "🔥", "smoke_detected": "💨", "timestamp_alert_start": "🕒",
    "timestamp_alert_end": "🕓", "ppe_compliance": "✅", "helmet_status": "🪖",
    "vest_status": "🦺", "occupancy_status": "👤", "unauthorized_person_detected": "🚷"
}

EXCLUDED_FIELDS = {
    "image", "createdAt", "updatedAt", "compliance frame", "vacant frame",
    "compliance_frame", "vacant_frame", "Frame", "frame", "createdat", "updatedat",
    "Image", "CameraLocationID", "seconds", "hours", "minutes"
}

ABOUT_APP_TERMS = [
    "what is this", "what does this do", "about this app", "about this application",
    "what am i looking at", "what can this do", "explain this", "tell me about this",
    "what is this platform", "i don't know what this is", "describe this app",
    "who are you", "what is optimes", "what does optimes do", "explain optimes"
]

# Context tracking
class ContextTracker:
    def __init__(self):
        self.current_context = None
        self.last_query = None
    
    def set_context(self, context):
        self.current_context = context
    
    def get_context(self):
        return self.current_context
    
    def set_last_query(self, query):
        self.last_query = query
    
    def get_last_query(self):
        return self.last_query

context_tracker = ContextTracker()

# ==================== MAINTENANCE HELPER FUNCTIONS ====================

def get_workorder_status_counts():
    """Get counts of workorders by status"""
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    results = list(MAINTENANCE_COLLECTIONS["workorders"].aggregate(pipeline))
    status_counts = {str(r["_id"]).lower(): r["count"] for r in results}
    
    all_statuses = ["pending", "in progress", "completed", "closed", "open", "assigned"]
    for s in all_statuses:
        status_counts.setdefault(s, 0)
    
    return status_counts

def get_workorder_by_id(workorder_id):
    """Get workorder by workorderid"""
    query = {"$or": [
        {"workorderid": workorder_id.upper()},
        {"workorderid": workorder_id},
        {"_id": ObjectId(workorder_id) if ObjectId.is_valid(workorder_id) else None}
    ]}
    return MAINTENANCE_COLLECTIONS["workorders"].find_one(query)

def get_workrequest_by_id(workrequest_id):
    """Get workrequest by workorderId"""
    query = {"$or": [
        {"workorderId": workrequest_id.upper()},
        {"workorderId": workrequest_id},
        {"_id": ObjectId(workrequest_id) if ObjectId.is_valid(workrequest_id) else None}
    ]}
    return MAINTENANCE_COLLECTIONS["workrequests"].find_one(query)

def get_all_equipment():
    """Get all equipment"""
    return list(MAINTENANCE_COLLECTIONS["equipments"].find().sort("equipmentname", ASCENDING))

def get_equipment_by_status(status):
    """Get equipment by status"""
    status_map = {
        "working": "Working",
        "under maintenance": "Under Maintenance",
        "down": "Down",
        "maintenance": "Under Maintenance",
        "repair": "Under Maintenance"
    }
    
    status_query = status_map.get(status.lower(), status.capitalize())
    return list(MAINTENANCE_COLLECTIONS["equipments"].find({"status": {"$regex": status_query, "$options": "i"}}))

def get_equipment_by_id(equipment_id):
    """Get equipment by equipmentid"""
    query = {"$or": [
        {"equipmentid": equipment_id.upper()},
        {"equipmentid": equipment_id},
        {"_id": ObjectId(equipment_id) if ObjectId.is_valid(equipment_id) else None}
    ]}
    return MAINTENANCE_COLLECTIONS["equipments"].find_one(query)

def get_workorders_by_equipment(equipment_id):
    """Get workorders for a specific equipment"""
    return list(MAINTENANCE_COLLECTIONS["workorders"].find({
        "$or": [
            {"equipmentid": equipment_id},
            {"equipmentid": {"$regex": equipment_id, "$options": "i"}}
        ]
    }))

def get_pending_workorders():
    """Get pending workorders"""
    return list(MAINTENANCE_COLLECTIONS["workorders"].find({
        "status": {"$in": ["Pending", "Open", "Assigned", "In Progress"]}
    }).sort("duedate", ASCENDING))

def get_completed_workorders():
    """Get completed workorders"""
    return list(MAINTENANCE_COLLECTIONS["workorders"].find({
        "status": {"$regex": "Completed", "$options": "i"}
    }).sort("duedate", DESCENDING).limit(10))

def get_all_spareparts():
    """Get all spare parts"""
    return list(MAINTENANCE_COLLECTIONS["spareparts"].find().sort("sparepartsname", ASCENDING))

def get_all_groups():
    """Get all groups"""
    return list(MAINTENANCE_COLLECTIONS["groups"].find().sort("group", ASCENDING))

def get_all_makes():
    """Get all makes"""
    return list(MAINTENANCE_COLLECTIONS["makes"].find().sort("makename", ASCENDING))

def get_all_suppliers_maint():
    """Get all suppliers (maintenance)"""
    return list(MAINTENANCE_COLLECTIONS["suppliers"].find().sort("suppliername", ASCENDING))

def get_all_locations_maint():
    """Get all locations (maintenance)"""
    return list(MAINTENANCE_COLLECTIONS["locations"].find().sort("locationName", ASCENDING))

def get_equipment_under_maintenance():
    """Get equipment under maintenance"""
    return list(MAINTENANCE_COLLECTIONS["equipments"].find({
        "status": {"$regex": "maintenance", "$options": "i"}
    }))

def format_maintenance_response(data, title):
    """Format maintenance data for chat response"""
    if not data:
        return ["No data found."]
    
    if isinstance(data, dict):
        response = [f"🔧 **{title}**"]
        for key, value in data.items():
            if key.startswith("_") or key in ["__v", "createdAt", "updatedAt"]:
                continue
            if isinstance(value, dict):
                response.append(f"  **{key}:**")
                for subkey, subvalue in value.items():
                    response.append(f"    {subkey}: {subvalue}")
            elif isinstance(value, list):
                response.append(f"  **{key}:** {len(value)} items")
                for i, item in enumerate(value, 1):
                    if isinstance(item, dict):
                        item_str = ", ".join([f"{k}: {v}" for k, v in item.items() 
                                            if not k.startswith("_")])
                        response.append(f"    {i}. {item_str}")
                    else:
                        response.append(f"    {i}. {item}")
            else:
                response.append(f"  **{key}:** {value}")
        return response
    
    elif isinstance(data, list):
        response = [f"🔧 **{title}** ({len(data)} items)"]
        for i, item in enumerate(data, 1):
            if isinstance(item, dict):
                # For equipment
                if "equipmentid" in item:
                    response.append(f"{i}. **{item.get('equipmentname', 'N/A')}** (ID: {item.get('equipmentid', 'N/A')})")
                    response.append(f"   Status: {item.get('status', 'N/A')}")
                    response.append(f"   Department: {item.get('department', 'N/A')}")
                    response.append(f"   Location: {item.get('location', 'N/A')}")
                    if item.get('maintenancepriority'):
                        response.append(f"   Priority: {item.get('maintenancepriority')}")
                    
                # For workorders
                elif "workorderid" in item:
                    response.append(f"{i}. **{item.get('workorderid', 'N/A')}** - {item.get('workordertype', 'N/A')}")
                    response.append(f"   Status: {item.get('status', 'N/A')}")
                    response.append(f"   Priority: {item.get('priority', 'N/A')}")
                    response.append(f"   Due Date: {item.get('duedate', 'N/A')}")
                    response.append(f"   Assigned to: {item.get('fullname', 'N/A')}")
                    
                # For workrequests
                elif "workorderId" in item:
                    response.append(f"{i}. **{item.get('workorderId', 'N/A')}** - {item.get('workorderType', 'N/A')}")
                    response.append(f"   Status: {item.get('status', 'N/A')}")
                    response.append(f"   Priority: {item.get('priority', 'N/A')}")
                    response.append(f"   Trade: {item.get('trade', 'N/A')}")
                    response.append(f"   Location: {item.get('location', 'N/A')}")
                    
                # For spare parts
                elif "sparepartcode" in item:
                    response.append(f"{i}. **{item.get('sparepartsname', 'N/A')}** (Code: {item.get('sparepartcode', 'N/A')})")
                    response.append(f"   Department: {item.get('department', 'N/A')}")
                    response.append(f"   Make: {item.get('make', 'N/A')}")
                    response.append(f"   Model: {item.get('model', 'N/A')}")
                    
                # For groups
                elif "group" in item:
                    response.append(f"{i}. **{item.get('group', 'N/A')}**")
                    
                # For makes
                elif "makename" in item:
                    response.append(f"{i}. **{item.get('makename', 'N/A')}**")
                    if item.get('location'):
                        response.append(f"   Location: {item.get('location')}")
                        
                # For suppliers (maintenance)
                elif "suppliername" in item:
                    response.append(f"{i}. **{item.get('suppliername', 'N/A')}**")
                    
                # For locations (maintenance)
                elif "locationName" in item:
                    response.append(f"{i}. **{item.get('locationName', 'N/A')}**")
                    if item.get('substation'):
                        response.append(f"   Substation: {item.get('substation')}")
                
                response.append("")
        return response
    
    return [str(data)]

# ==================== INVENTORY HELPER FUNCTIONS ====================

def search_inventory_products(search_term):
    """Search for products across multiple fields"""
    query = {
        "$or": [
            {"productId": {"$regex": search_term, "$options": "i"}},
            {"name": {"$regex": search_term, "$options": "i"}},
            {"category": {"$regex": search_term, "$options": "i"}},
            {"description": {"$regex": search_term, "$options": "i"}},
            {"make": {"$regex": search_term, "$options": "i"}},
            {"partNumber": {"$regex": search_term, "$options": "i"}}
        ]
    }
    return list(INVENTORY_COLLECTIONS["products"].find(query).limit(10))

def get_product_by_id(product_id):
    """Get product by productId"""
    return INVENTORY_COLLECTIONS["products"].find_one({"productId": product_id})

def get_stock_by_product(product_id):
    """Get stock information for a product"""
    return list(INVENTORY_COLLECTIONS["stocks"].find({"productId": product_id}))

def get_low_stock_products():
    """Get products with low stock"""
    products = INVENTORY_COLLECTIONS["products"].find({"quantity": {"$lt": 10}})
    return list(products)

def get_all_categories():
    """Get all inventory categories"""
    return list(INVENTORY_COLLECTIONS["categories"].find().sort("categoryName", ASCENDING))

def get_all_locations():
    """Get all inventory locations"""
    return list(INVENTORY_COLLECTIONS["locations"].find().sort("name", ASCENDING))

def get_available_locations():
    """Get locations with available capacity"""
    locations = list(INVENTORY_COLLECTIONS["locations"].find({
        "totalAvailableCapacity": {"$gt": 0}
    }).sort("totalAvailableCapacity", DESCENDING))
    
    return locations

def get_location_by_id(location_id):
    """Get location by ID"""
    query = {"$or": [
        {"locationId": location_id},
        {"_id": ObjectId(location_id) if ObjectId.is_valid(location_id) else None}
    ]}
    return INVENTORY_COLLECTIONS["locations"].find_one(query)

def get_location_by_name(location_name):
    """Get location by name"""
    return INVENTORY_COLLECTIONS["locations"].find_one({"name": {"$regex": location_name, "$options": "i"}})

def get_all_suppliers():
    """Get all suppliers"""
    return list(INVENTORY_COLLECTIONS["suppliers"].find().sort("name", ASCENDING))

def get_all_projects():
    """Get all projects"""
    return list(INVENTORY_COLLECTIONS["projects"].find().sort("Title", ASCENDING))

def get_project_by_id(project_id):
    """Get project by ProjectId or Title (case-insensitive)"""
    query = {"$or": [
        {"ProjectId": project_id},
        {"ProjectId": project_id.upper()},
        {"Title": {"$regex": f"^{project_id}$", "$options": "i"}},
        {"_id": ObjectId(project_id) if ObjectId.is_valid(project_id) else None}
    ]}
    return INVENTORY_COLLECTIONS["projects"].find_one(query)

def get_recent_stock_movements(limit=10):
    """Get recent stock movements/distributions"""
    if "distributions" in INVENTORY_COLLECTIONS:
        movements = list(INVENTORY_COLLECTIONS["distributions"].find()
                        .sort("createdAt", DESCENDING)
                        .limit(limit))
    else:
        movements = []
        products = INVENTORY_COLLECTIONS["products"].find({"movements": {"$exists": True, "$ne": []}})
        for product in products:
            for movement in product.get("movements", [])[-5:]:
                movement["productName"] = product.get("name", "Unknown")
                movement["productId"] = product.get("productId", "Unknown")
                movements.append(movement)
        
        movements.sort(key=lambda x: x.get("date", ""), reverse=True)
        movements = movements[:limit]
    
    return movements

def get_stock_movements_by_product(product_id):
    """Get stock movements for a specific product"""
    product = get_product_by_id(product_id)
    if product and "movements" in product:
        return product["movements"]
    return []

def get_stock_movements_by_location(location_id):
    """Get stock movements for a specific location"""
    movements = []
    products = INVENTORY_COLLECTIONS["products"].find({"movements": {"$exists": True, "$ne": []}})
    
    for product in products:
        for movement in product.get("movements", []):
            if movement.get("toLocation") == location_id or movement.get("fromLocation") == location_id:
                movement["productName"] = product.get("name", "Unknown")
                movement["productId"] = product.get("productId", "Unknown")
                movements.append(movement)
    
    movements.sort(key=lambda x: x.get("date", ""), reverse=True)
    return movements

def format_inventory_response(data, title):
    """Format inventory data for chat response"""
    if not data:
        return ["No data found."]
    
    if isinstance(data, dict):
        response = [f"📦 **{title}**"]
        for key, value in data.items():
            if key.startswith("_") or key in ["__v", "createdAt", "updatedAt", "image"]:
                continue
            if isinstance(value, dict):
                response.append(f"  **{key}:**")
                for subkey, subvalue in value.items():
                    response.append(f"    {subkey}: {subvalue}")
            elif isinstance(value, list):
                response.append(f"  **{key}:** {len(value)} items")
                for i, item in enumerate(value, 1):
                    if isinstance(item, dict):
                        item_str = ", ".join([f"{k}: {v}" for k, v in item.items() 
                                            if not k.startswith("_")])
                        response.append(f"    {i}. {item_str}")
                    else:
                        response.append(f"    {i}. {item}")
            else:
                response.append(f"  **{key}:** {value}")
        return response
    
    elif isinstance(data, list):
        response = [f"📦 **{title}** ({len(data)} items)"]
        for i, item in enumerate(data, 1):
            if isinstance(item, dict):
                if "productId" in item:
                    response.append(f"{i}. **{item.get('name', 'N/A')}** (ID: {item.get('productId', 'N/A')})")
                    response.append(f"   Category: {item.get('category', 'N/A')}")
                    response.append(f"   Quantity: {item.get('quantity', 0)} {item.get('unit', '')}")
                    if item.get('price'):
                        price_info = item['price']
                        if isinstance(price_info, dict):
                            response.append(f"   Price: ₹{price_info.get('value', 'N/A')}")
                    
                elif "vendorid" in item:
                    response.append(f"{i}. **{item.get('name', 'N/A')}** (ID: {item.get('vendorid', 'N/A')})")
                    response.append(f"   Contact: {item.get('contact', 'N/A')}")
                    response.append(f"   Phone: {item.get('phone', 'N/A')}")
                    
                elif "categoryCode" in item:
                    response.append(f"{i}. **{item.get('categoryName', 'N/A')}** (Code: {item.get('categoryCode', 'N/A')})")
                    
                elif "locationId" in item:
                    response.append(f"{i}. **{item.get('name', 'N/A')}** (ID: {item.get('locationId', 'N/A')})")
                    response.append(f"   Capacity: {item.get('currentUtilization', 0)}/{item.get('totalCapacity', 0)}")
                    response.append(f"   Available: {item.get('totalAvailableCapacity', 0)}")
                    if item.get('racks'):
                        response.append(f"   Racks: {len(item.get('racks', []))}")
                    
                elif "ProjectId" in item:
                    response.append(f"{i}. **{item.get('Title', 'N/A')}** (ID: {item.get('ProjectId', 'N/A')})")
                    response.append(f"   Client: {item.get('Client', 'N/A')}")
                    response.append(f"   Status: {item.get('Status', 'N/A')}")
                    response.append(f"   Description: {item.get('Description', 'N/A')}")
                    
                elif "serialNo" in item:
                    response.append(f"{i}. **{item.get('name', 'N/A')}** (SN: {item.get('serialNo', 'N/A')})")
                    response.append(f"   Quantity: {item.get('quantity', 0)} {item.get('unit', '')}")
                    response.append(f"   Location: {item.get('locationId', 'Not assigned')}")
                    
                elif "movementType" in item or "type" in item:
                    movement_type = item.get('movementType', item.get('type', 'Movement'))
                    response.append(f"{i}. **{movement_type}**")
                    if item.get('productName'):
                        response.append(f"   Product: {item.get('productName')} ({item.get('productId', 'N/A')})")
                    response.append(f"   Quantity: {item.get('quantity', 0)}")
                    if item.get('fromLocation'):
                        response.append(f"   From: {item.get('fromLocation')}")
                    if item.get('toLocation'):
                        response.append(f"   To: {item.get('toLocation')}")
                    if item.get('date'):
                        response.append(f"   Date: {item.get('date')}")
                    if item.get('reason'):
                        response.append(f"   Reason: {item.get('reason')}")
                    
                response.append("")
        return response
    
    return [str(data)]

# ==================== SAFETY HELPER FUNCTIONS ====================

def is_today_incident_query(user_input):
    return any(word in user_input for word in [
        "today", "happened today", "occurred today",
        "incident today", "fire today", "smoke today"
    ])

def is_about_app(user_input):
    return any(term in user_input for term in ABOUT_APP_TERMS) or \
           re.search(r"\b(what|who|tell|explain|describe).*(this|optimes|app|application|system)\b", user_input)

def contains_term(text, terms):
    for term in terms:
        if re.search(r'\b' + re.escape(term) + r'\b', text):
            return True
    return False

def make_naive(dt):
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

def is_latest_incident_query(user_input):
    keywords = ["latest", "last", "recent", "most recent", "newest"]
    incident_terms = ["incident", "violation", "alert", "issue", "event"]
    return any(k in user_input.lower() for k in keywords) and \
           any(t in user_input.lower() for t in incident_terms)

def get_valid_timestamp(record):
    ts = (
        record.get("timestamp_alert_start") or
        record.get("timestamp_alert_end") or
        record.get("createdAt") or
        (record.get("_id").generation_time if isinstance(record.get("_id"), ObjectId) else datetime.min)
    )
    return make_naive(ts)

def infer_collections_from_input(user_input):
    input_lower = user_input.lower()
    matched = []

    if "fire" in input_lower or "smoke" in input_lower:
        matched.append("fires")
    if "gas" in input_lower or "leak" in input_lower:
        matched.append("gasleakages")
    if "ppe" in input_lower or "helmet" in input_lower or "vest" in input_lower:
        matched.append("ppekits")
    if "slip" in input_lower or "fall" in input_lower:
        matched.append("slips")
    if "occupancy" in input_lower or "vacancy" in input_lower:
        matched.append("occupancies")
    if any(term in input_lower for term in ["unauthorized", "unauthorised", "authorized", "authorised", "intruder"]):
        matched.append("unauthorizedentries")

    return matched if matched else []

def get_violations_by_employee(person_id):
    """Fetch all violations/alerts for a person across all collections"""
    results = []

    for col_name in ALL_COLLECTIONS:
        collection = db[col_name]
        query = {
            "$or": [
                {"employee_id": person_id},
                {"personName": person_id}
            ]
        }
        matches = list(collection.find(query))

        for doc in matches:
            doc["source"] = col_name
            doc["timestamp"] = get_valid_timestamp(doc)
            results.append(doc)

    results.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)
    return results

def get_person_details(person_id):
    person_id = person_id.strip().upper()
    person = db["persons"].find_one({"personId": person_id})
    print(f"🔍 Looking for {person_id}, Found:", person)
    return person

def get_latest_from_collections(collection_names, user_input=None):
    latest_results = {}

    for col_name in collection_names:
        collection = db[col_name]

        filter_query = {}
        if col_name == "unauthorizedentries" and user_input:
            unauth_terms = ["unauthorized", "trespass", "intruder", "unidentified", "trespasser", "trespassing", "entered illegally", "someone not allowed", "intrusion", "not authorized", "unknown person", "out of work", "stranger", "trespassed"]
            auth_terms = ["authorized", "permitted", "allowed"]
            if any(re.search(rf"\b{term}\b", user_input) for term in unauth_terms):
                filter_query = {"scenario": {"$regex": r"(unauthorized|trespass|intruder|unidentified|stranger|not authorized|unknown)", "$options": "i"}}
            elif any(re.search(rf"\b{term}\b", user_input) for term in auth_terms):
                filter_query = {"scenario": {"$regex": r"(authorized|permitted|allowed)", "$options": "i"}}
            else:
                filter_query = {"scenario": {"$not": {"$regex": r"^authorized entry$", "$options": "i"}}}

        print(f"\n🔍 Searching in collection: '{col_name}'")
        print(f"📊 Total documents: {collection.count_documents({})}")
        print(f"🔎 Filter query: {filter_query}")
        
        try:
            print(f"🧮 Matching docs: {collection.count_documents(filter_query)}")
        except Exception as e:
            print(f"⚠️ Error counting filtered docs in '{col_name}': {e}")

        doc = collection.find_one(
            filter_query,
            sort=[
                ("createdAt", DESCENDING),
                ("timestamp_alert_start", DESCENDING),
                ("_id", DESCENDING)
            ]
        )

        if not doc:
            print(f"❌ No document found in '{col_name}' with given filter.")
            latest_results[col_name] = (None, None, col_name)
            continue

        print(f"✅ Found document in '{col_name}': _id = {doc.get('_id')}")

        frame_doc = None
        for key, value in doc.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                try:
                    frame_doc = max(
                        value,
                        key=lambda x: x.get("timestamp") or
                                      x.get("start_timestamp") or
                                      x.get("createdAt") or
                                      (x.get("_id").generation_time if isinstance(x.get("_id"), ObjectId) else datetime.min)
                    )
                    print(f"🧩 Selected latest frame from '{key}'")
                except Exception as e:
                    print(f"⚠️ Error parsing frames in '{col_name}': {e}")
                    frame_doc = value[0]

        latest_results[col_name] = (doc, frame_doc, col_name)

    return latest_results

def get_permit_by_number(permit_number):
    return permit_collection.find_one({"permitNumber": permit_number})

def get_specific_permit_status_count(user_input):
    """Check if user asks for count of a specific permit status"""
    status_terms = ["approved", "pending", "inprogress", "cancelled",
                    "closed", "overdue", "completed", "extended"]

    for status in status_terms:
        if status.replace(" ", "") in user_input.replace(" ", ""):
            count = permit_collection.count_documents({
                "status": {"$regex": f"^{status}$", "$options": "i"}
            })
            return count, status.title()
    return None, None

def get_permit_status_counts():
    """Get counts of permits by status"""
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    results = list(permit_collection.aggregate(pipeline))
    status_counts = {str(r["_id"]).lower(): r["count"] for r in results}

    all_statuses = ["approved", "pending", "inprogress", "cancelled", 
                    "closed", "overdue", "completed", "extended"]
    for s in all_statuses:
        status_counts.setdefault(s, 0)

    return status_counts

# ==================== ROUTES ====================

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/chat', methods=['POST'])
def chatbot_response():
    user_input = request.json.get("message", "").lower()
    
    # Store the last query for context
    context_tracker.set_last_query(user_input)
    
    # Check if this is coming from inventory context
    last_query = context_tracker.get_last_query()
    is_inventory_context = last_query and (
        "inventory" in last_query or 
        any(keyword in last_query for keyword in ["stock", "product", "category"])
    )
    
    # --- SIMPLE PRODUCTION QUERIES ---
    prod_patterns = [
        "production today", "today's production", "daily production", 
        "today production", "production report", "output today",
        "how many bottles today", "manufacturing output today",
        "what is the production", "show production", "total production",
        "production status", "production figures", "production count",
        "bottles produced", "bottles manufactured"
    ]
    
    for pattern in prod_patterns:
        if pattern in user_input:
            return jsonify({"reply": ["📊 **Total Production Today:** 37,369 Bottles"]})
    
    energy_patterns = [
        "energy cost", "power cost", "electricity cost", 
        "energy bill", "power consumption cost", "electricity bill",
        "energy expense", "cost of energy", "energy consumption",
        "power expense", "electricity expense", "energy charges"
    ]
    
    for pattern in energy_patterns:
        if pattern in user_input:
            return jsonify({"reply": ["⚡ **Total Energy Cost:** ₹ 1,21,800"]})
    
    lowest_words = ["lowest", "least", "minimum", "worst", "poor"]
    shift_words = ["shift", "batch", "schedule"]
    production_words = ["production", "output", "bottles", "manufacturing"]
    
    if (any(word in user_input for word in lowest_words) and 
        any(word in user_input for word in shift_words) and 
        any(word in user_input for word in production_words)) or \
       ("which shift" in user_input and any(word in user_input for word in lowest_words)) or \
       ("lowest production" in user_input) or \
       ("which shift has lowest" in user_input):
        
        return jsonify({"reply": [
            "📉 **Lowest Production Shift:**",
            "🔸 **Shift C** – 12,480 Bottles",
            "",
            "**Reason:**",
            "• 1 hr planned maintenance",
            "• 30 min material waiting",
            "• Low manpower"
        ]})
    
    if "why" in user_input and any(word in user_input for word in ["lowest", "least", "worst", "poor"]):
        return jsonify({"reply": [
            "📉 **Lowest Production Shift was Shift C**",
            "",
            "**Reasons for low production:**",
            "• 1 hr planned maintenance",
            "• 30 min material waiting",
            "• Low manpower"
        ]})

    production_keywords = [
        "production", "manufacturing", "output", "bottles", "units", 
        "energy", "power", "electricity", "consumption", "cost",
        "shift", "line", "machine", "efficiency", "oee", "throughput",
        "yield", "defect", "quality", "downtime", "maintenance",
        "capacity", "utilization", "throughput", "cycle time",
        "productivity", "operational", "plant", "factory", "assembly"
    ]

    if any(keyword in user_input for keyword in production_keywords):
        known_patterns = [
            "production today", "today's production", "daily production", 
            "today production", "production report", "output today",
            "how many bottles today", "manufacturing output today",
            "what is the production", "show production", "total production",
            "production status", "production figures", "production count",
            "bottles produced", "bottles manufactured", "energy cost",
            "power cost", "electricity cost", "energy bill", "power consumption cost",
            "electricity bill", "energy expense", "cost of energy", "energy consumption",
            "power expense", "electricity expense", "energy charges",
            "lowest production shift", "which shift has lowest",
            "lowest production", "worst shift", "least production"
        ]
        
        if not any(pattern in user_input for pattern in known_patterns):
            return jsonify({
                "reply": [
                    "🤖 **Production & Energy Data Assistant**",
                    "",
                    "I see you're asking about production or energy data. Please click a button below or try rephrasing your question:"
                ],
                "buttons": PRODUCTION_ENERGY_BUTTONS
            })

    # --- PERMIT QUERIES --- (MOVE THIS BEFORE MAINTENANCE!)
    # Check for permit-specific keywords FIRST
    if any(keyword in user_input for keyword in PERMIT_SPECIFIC_KEYWORDS):
        context_tracker.set_context("permit")
        
        # Permit number match
        permit_match = re.search(r"\b(pw-\w+-\d+)\b", user_input, re.IGNORECASE)
        if permit_match:
            permit_number = permit_match.group().upper()
            permit = db["permits"].find_one({"permitNumber": permit_number})
            if not permit:
                return jsonify({"reply": [f"❌ No permit found with number {permit_number}."]})

            reply_lines = []

            # Count extensions
            if "how many" in user_input and ("extend" in user_input or "extension" in user_input):
                exts = permit.get("extensionHistory", [])
                count = len(exts)
                reply_lines.append(f"📊 Permit **{permit_number}** has been extended **{count} time(s)**.")
                return jsonify({"reply": reply_lines})

            # Extension details
            elif "extend" in user_input or "extension" in user_input:
                exts = permit.get("extensionHistory", [])
                if not exts:
                    reply_lines.append("❌ No extension history found.")
                else:
                    for e in exts:
                        reply_lines.append(
                            f"📌 Extended from {e['oldEndDateTime']} → {e['newEndDateTime']} "
                            f"at {e['updatedAt']}"
                        )
                return jsonify({"reply": reply_lines})

            # General Permit Queries
            if "status" in user_input:
                reply_lines.append(f"📌 Permit **{permit_number}** is currently **{permit.get('status','N/A')}**")
            elif "start" in user_input and "end" in user_input:
                reply_lines.append(f"⏳ Permit **{permit_number}** runs from **{permit.get('startDateTime')}** to **{permit.get('endDateTime')}**")
            elif "type" in user_input:
                reply_lines.append(f"🛠️ Permit **{permit_number}** is for **{permit.get('workType','N/A')}** work")
            elif "location" in user_input:
                reply_lines.append(f"📍 Work location: **{permit.get('formLocation','N/A')}**")
            elif "created" in user_input or "updated" in user_input:
                reply_lines.append(f"🕒 Created: {permit.get('createdAt')} | Last Updated: {permit.get('updatedAt')}")

            elif "worker" in user_input or "workers" in user_input:
                workers = permit.get("workers", [])
                if not workers:
                    reply_lines.append("❌ No workers assigned.")
                else:
                    reply_lines.append(f"👷 Workers in permit **{permit_number}**:")
                    for w in workers:
                        reply_lines.append(f" - {w.get('workerName','N/A')} (ID: {w.get('workerId','N/A')}, Dept: {w.get('department','N/A')})")

            elif "activity" in user_input:
                reply_lines.append(f"📝 Activity: {permit.get('activityDescription','N/A')}")
            elif "risk" in user_input:
                reply_lines.append(f"⚠️ Risk Assessment: {permit.get('riskAssessment','N/A')}")
            elif "declaration" in user_input:
                declarations = permit.get("declarations", {})
                yes_decls = [k for k,v in declarations.items() if v == "YES"]
                reply_lines.append(f"✅ Confirmed Declarations: {', '.join(yes_decls)}")

            elif "approval" in user_input or "approver" in user_input:
                approvals = []
                for i in [1,2]:
                    appr = permit.get(f"approval{i}")
                    if appr:
                        approvals.append(f"{appr.get('name')} ({appr.get('status')}) at {appr.get('timestamp')}")
                if approvals:
                    reply_lines.append("📝 Approvals:\n" + "\n".join(approvals))
                else:
                    reply_lines.append("❌ No approvals found.")

            elif "history" in user_input or "inprogress" in user_input or "overdue" in user_input:
                status_hist = permit.get("statusHistory", [])
                if not status_hist:
                    reply_lines.append("❌ No status history found.")
                else:
                    reply_lines.append(f"📜 Status History for {permit_number}:")
                    for s in status_hist:
                        reply_lines.append(f" - {s['status']} at {s['timestamp']}")

            else:
                reply_lines.append(
                    f"📋 **Permit {permit_number}**\n"
                    f"🛠️ Type: {permit.get('workType','N/A')}\n"
                    f"📍 Location: {permit.get('formLocation','N/A')}\n"
                    f"⏳ Start: {permit.get('startDateTime')} → End: {permit.get('endDateTime')}\n"
                    f"📌 Status: {permit.get('status','N/A')}\n"
                )

            return jsonify({"reply": reply_lines})

        # Specific Permit Status Count
        count, status_title = get_specific_permit_status_count(user_input)
        if count is not None:
            return jsonify({"reply": [f"📊 There are **{count}** permit(s) in **{status_title}** status."]})

        # Overall Permit Status Summary
        if any(phrase in user_input for phrase in [
            "workpermit", "work permit", "permit status", 
            "current workpermit", "current permit", "permit pending",
            "workpermit pending", "work permit pending"
        ]) and not re.search(r"\b(pw-\w+-\d+)\b", user_input, re.IGNORECASE):
            status_counts = get_permit_status_counts()
            return jsonify({"reply": [
                "📋 **Work Permit Status Summary:**",
                "",
                f"✅ Approved: {status_counts['approved']}",
                f"🟡 Pending: {status_counts['pending']}",
                f"🔵 In Progress: {status_counts['inprogress']}",
                f"✅ Completed: {status_counts['completed']}",
                f"⚠️ Overdue: {status_counts['overdue']}",
                f"🟠 Extended: {status_counts['extended']}",
                f"❌ Cancelled: {status_counts['cancelled']}",
                f"🔴 Closed: {status_counts['closed']}"
            ]})

        # All pending permits today
        if "pending permits" in user_input and "today" in user_input:
            today = datetime.now().date()
            start_of_day = datetime.combine(today, datetime.min.time())
            end_of_day = datetime.combine(today, datetime.max.time())

            permits = list(permit_collection.find({
                "status": "PENDING",
                "startDateTime": {"$gte": start_of_day, "$lte": end_of_day}
            }))

            if not permits:
                return jsonify({"reply": ["✅ No pending permits for today."]})

            reply_lines = ["📋 **Pending Permits for Today:**"]
            for p in permits:
                reply_lines.append(
                    f" - {p['permitNumber']} ({p.get('workType','N/A')}) "
                    f"from {p.get('startDateTime')} to {p.get('endDateTime')}"
                )
            reply_lines.append(f"📊 Total: {len(permits)} permit(s).")
            return jsonify({"reply": reply_lines})

        # All pending permits till date
        if "pending permits" in user_input and "till date" in user_input:
            today = datetime.now()
            permits = list(permit_collection.find({
                "status": "PENDING",
                "endDateTime": {"$lte": today}
            }))

            if not permits:
                return jsonify({"reply": ["✅ No pending permits till date."]})

            reply_lines = ["📋 **Pending Permits Till Date:**"]
            for p in permits:
                reply_lines.append(
                    f" - {p['permitNumber']} ({p.get('workType','N/A')}) "
                    f"from {p.get('startDateTime')} to {p.get('endDateTime')}"
                )
            reply_lines.append(f"📊 Total: {len(permits)} permit(s).")
            return jsonify({"reply": reply_lines})

        # Month-wise pending permits count
        if ("pending permits" in user_input and "month" in user_input) or "month wise" in user_input:
            pipeline = [
                {"$match": {"status": "PENDING"}},
                {"$group": {
                    "_id": {"year": {"$year": "$endDateTime"}, "month": {"$month": "$endDateTime"}},
                    "count": {"$sum": 1}
                }},
                {"$sort": {"_id.year": 1, "_id.month": 1}}
            ]
            results = list(permit_collection.aggregate(pipeline))

            if not results:
                return jsonify({"reply": ["✅ No pending permits found in any month."]})

            reply_lines = ["📊 **Month-wise Pending Permits Count:**"]
            for r in results:
                year = r["_id"]["year"]
                month = r["_id"]["month"]
                reply_lines.append(f" - {year}-{month:02d}: {r['count']} permit(s)")
            return jsonify({"reply": reply_lines})
            
        # Permits extended beyond original end time
        if "extended beyond" in user_input or "overdue permits" in user_input:
            permits = list(permit_collection.find({"extensionHistory": {"$exists": True, "$ne": []}}))
            extended_permits = []
            for p in permits:
                end_time = p.get("endDateTime")
                exts = p.get("extensionHistory", [])
                if not end_time or not exts:
                    continue
                latest_ext = max(exts, key=lambda e: e["newEndDateTime"])
                if latest_ext["newEndDateTime"] > end_time:
                    extended_permits.append((p["permitNumber"], latest_ext))

            if not extended_permits:
                return jsonify({"reply": ["✅ No permits extended beyond their original end time."]})

            reply_lines = ["📌 **Permits Extended Beyond Original End Time:**"]
            for num, e in extended_permits:
                reply_lines.append(
                    f" - {num}: Extended to {e['newEndDateTime']} (original end {e['oldEndDateTime']})"
                )
            reply_lines.append(f"📊 Total: {len(extended_permits)} permit(s).")
            return jsonify({"reply": reply_lines})

    # --- CMMS/MAINTENANCE QUERIES ---
    # Check for specific maintenance keywords 
    if any(keyword in user_input for keyword in MAINTENANCE_SPECIFIC_KEYWORDS):
        # IMPORTANT: Skip if it's actually a permit query
        if any(keyword in user_input for keyword in PERMIT_SPECIFIC_KEYWORDS):
            # This was already handled above, skip maintenance
            pass
        else:
            context_tracker.set_context("maintenance")
            
            # 1. CMMS Help command - ONLY SHOW BUTTONS, NOT TEXT
            if "cmms" in user_input or "pulse" in user_input or "maintenance help" in user_input:
                return jsonify({
                    "reply": [
                        "🔧 **Maintenance & Asset Management (CMMS)**",
                        "",
                        "Click any button below to get started:"
                    ],
                    "buttons": MAINTENANCE_BUTTONS
                })
            
            # 2. Workorder status summary
            if any(phrase in user_input for phrase in [
                "workorder status", "workorder summary", "workorder counts",
                "workorder status summary", "how many workorders"
            ]):
                status_counts = get_workorder_status_counts()
                return jsonify({"reply": [
                    "📊 **Workorder Status Summary:**",
                    "",
                    f"✅ Completed: {status_counts.get('completed', 0)}",
                    f"🟡 In Progress: {status_counts.get('in progress', 0)}",
                    f"🔵 Pending: {status_counts.get('pending', 0)}",
                    f"🟠 Open: {status_counts.get('open', 0)}",
                    f"🔴 Closed: {status_counts.get('closed', 0)}",
                    f"👤 Assigned: {status_counts.get('assigned', 0)}",
                    "",
                    f"📈 **Total Workorders:** {sum(status_counts.values())}"
                ]})
            
            # 3. Find workorder by ID
            workorder_match = re.search(r"\b(WO-[\w-]+|WR-[\w-]+)\b", user_input, re.IGNORECASE)
            if workorder_match or any(phrase in user_input for phrase in [
                "find workorder", "workorder details", "show workorder",
                "details of workorder", "workorder info"
            ]):
                if workorder_match:
                    workorder_id = workorder_match.group().upper()
                else:
                    words = user_input.split()
                    workorder_id = None
                    for i, word in enumerate(words):
                        if word in ["workorder", "wo", "wr"] and i+1 < len(words):
                            workorder_id = words[i+1].upper()
                            break
                    else:
                        workorder_id = None
                
                if workorder_id:
                    workorder = get_workorder_by_id(workorder_id)
                    if not workorder:
                        workorder = get_workrequest_by_id(workorder_id)
                    
                    if workorder:
                        response = [f"📋 **Workorder Details:**"]
                        if "workorderid" in workorder:
                            response.append(f"**ID:** {workorder.get('workorderid', 'N/A')}")
                            response.append(f"**Type:** {workorder.get('workordertype', 'N/A')}")
                        elif "workorderId" in workorder:
                            response.append(f"**ID:** {workorder.get('workorderId', 'N/A')}")
                            response.append(f"**Type:** {workorder.get('workorderType', 'N/A')}")
                        
                        response.append(f"**Status:** {workorder.get('status', 'N/A')}")
                        response.append(f"**Priority:** {workorder.get('priority', 'N/A')}")
                        response.append(f"**Department:** {workorder.get('department', workorder.get('trade', 'N/A'))}")
                        
                        if "equipmentid" in workorder:
                            response.append(f"**Equipment ID:** {workorder.get('equipmentid', 'N/A')}")
                        
                        if "location" in workorder:
                            response.append(f"**Location:** {workorder.get('location', 'N/A')}")
                        elif "equipmentlocation" in workorder:
                            response.append(f"**Location:** {workorder.get('equipmentlocation', 'N/A')}")
                        
                        if "duedate" in workorder:
                            response.append(f"**Due Date:** {workorder.get('duedate', 'N/A')}")
                        elif "planningDate" in workorder:
                            response.append(f"**Planning Date:** {workorder.get('planningDate', 'N/A')}")
                        
                        if "assignedto" in workorder:
                            response.append(f"**Assigned To:** {workorder.get('fullname', workorder.get('assignedto', 'N/A'))}")
                        elif "assignTo" in workorder:
                            response.append(f"**Assigned To:** {workorder.get('assignTo', 'N/A')}")
                        
                        if "createdBy" in workorder:
                            response.append(f"**Created By:** {workorder.get('createdBy', 'N/A')}")
                        
                        if "requestedBy" in workorder:
                            response.append(f"**Requested By:** {workorder.get('requestedBy', 'N/A')}")
                        
                        # Show history if available
                        if "history" in workorder and workorder["history"]:
                            response.append("")
                            response.append("📜 **History:**")
                            for hist in workorder["history"][-3:]:  # Show last 3 history items
                                response.append(f"  • {hist.get('status', 'N/A')} at {hist.get('timestamp', 'N/A')}")
                        
                        return jsonify({"reply": response})
                    else:
                        return jsonify({"reply": [f"❌ Workorder '{workorder_id}' not found"]})
            
            # 4. Show all equipment
            if any(phrase in user_input for phrase in [
                "show all equipment", "list all equipment", "all equipment",
                "show equipment", "equipment list"
            ]):
                equipment = get_all_equipment()
                return jsonify({"reply": format_maintenance_response(equipment, "All Equipment")})
            
            # 5. Equipment by status
            status_keywords = ["working", "under maintenance", "maintenance", "down", "repair"]
            if any(status in user_input for status in status_keywords) and any(word in user_input for word in ["equipment", "asset", "status"]):
                for status in status_keywords:
                    if status in user_input:
                        equipment = get_equipment_by_status(status)
                        if equipment:
                            return jsonify({"reply": format_maintenance_response(equipment, f"Equipment ({status.title()})")})
                        else:
                            return jsonify({"reply": [f"✅ No equipment found with status '{status}'"]})
            
            # 6. Equipment under maintenance
            if any(phrase in user_input for phrase in [
                "equipment under maintenance", "under maintenance", "maintenance equipment",
                "assets under maintenance"
            ]):
                equipment = get_equipment_under_maintenance()
                if equipment:
                    return jsonify({"reply": format_maintenance_response(equipment, "Equipment Under Maintenance")})
                else:
                    return jsonify({"reply": ["✅ No equipment is currently under maintenance"]})
            
            # 7. Equipment details by ID
            equipment_match = re.search(r"\b(EQ-\d+)\b", user_input, re.IGNORECASE)
            if equipment_match or any(phrase in user_input for phrase in [
                "equipment details", "asset details", "show equipment",
                "details of equipment", "equipment info"
            ]):
                if equipment_match:
                    equipment_id = equipment_match.group().upper()
                else:
                    words = user_input.split()
                    for i, word in enumerate(words):
                        if word in ["equipment", "asset", "eq"] and i+1 < len(words):
                            equipment_id = words[i+1].upper()
                            break
                    else:
                        equipment_id = None
                
                if equipment_id:
                    equipment = get_equipment_by_id(equipment_id)
                    if equipment:
                        response = [f"🏭 **Equipment Details:**"]
                        response.append(f"**ID:** {equipment.get('equipmentid', 'N/A')}")
                        response.append(f"**Name:** {equipment.get('equipmentname', 'N/A')}")
                        response.append(f"**Status:** {equipment.get('status', 'N/A')}")
                        response.append(f"**Department:** {equipment.get('department', 'N/A')}")
                        response.append(f"**Make:** {equipment.get('make', 'N/A')}")
                        response.append(f"**Model:** {equipment.get('modelno', 'N/A')}")
                        response.append(f"**Location:** {equipment.get('location', 'N/A')}")
                        response.append(f"**Group:** {equipment.get('groupname', 'N/A')}")
                        response.append(f"**Supplier:** {equipment.get('suplier', 'N/A')}")
                        
                        if equipment.get('purchasedate'):
                            response.append(f"**Purchase Date:** {equipment.get('purchasedate')}")
                        
                        if equipment.get('installationdate'):
                            response.append(f"**Installation Date:** {equipment.get('installationdate')}")
                        
                        if equipment.get('warranty'):
                            response.append(f"**Warranty:** {equipment.get('warranty')}")
                            if equipment.get('warrantyFrom'):
                                response.append(f"**Warranty From:** {equipment.get('warrantyFrom')}")
                            if equipment.get('warrantyTo'):
                                response.append(f"**Warranty To:** {equipment.get('warrantyTo')}")
                        
                        if equipment.get('maintenancedate'):
                            response.append(f"**Maintenance Interval:** Every {equipment.get('maintenancedate')} days")
                        
                        if equipment.get('maintenancepriority'):
                            response.append(f"**Maintenance Priority:** {equipment.get('maintenancepriority')}")
                        
                        # Show metrics
                        response.append(f"**MTBF:** {equipment.get('mtbf', 0)} hours")
                        response.append(f"**MTTR:** {equipment.get('mttr', 0)} hours")
                        response.append(f"**Total Uptime:** {equipment.get('totalUptime', 0)} hours")
                        response.append(f"**Total Downtime:** {equipment.get('totalDowntime', 0)} hours")
                        response.append(f"**Failure Count:** {equipment.get('failureCount', 0)}")
                        
                        # Get workorders for this equipment
                        workorders = get_workorders_by_equipment(equipment.get('equipmentid', ''))
                        if workorders:
                            response.append("")
                            response.append("🔧 **Recent Workorders:**")
                            recent_workorders = workorders[:3]
                            for wo in recent_workorders:
                                response.append(f"  • {wo.get('workorderid', 'N/A')} - {wo.get('status', 'N/A')} (Due: {wo.get('duedate', 'N/A')})")
                        
                        return jsonify({"reply": response})
                    else:
                        return jsonify({"reply": [f"❌ Equipment '{equipment_id}' not found"]})
            
            # 8. Pending workorders (MAINTENANCE SPECIFIC)
            if any(phrase in user_input for phrase in [
                "pending workorders", "open workorders", "workorders pending",
                "uncompleted workorders", "workorder pending"
            ]) and "permit" not in user_input:
                pending = get_pending_workorders()
                if pending:
                    return jsonify({"reply": format_maintenance_response(pending, "Pending Workorders")})
                else:
                    return jsonify({"reply": ["✅ No pending workorders found"]})
            
            # 9. Completed workorders
            if any(phrase in user_input for phrase in [
                "completed workorders", "finished workorders", "closed workorders",
                "workorders completed"
            ]):
                completed = get_completed_workorders()
                if completed:
                    return jsonify({"reply": format_maintenance_response(completed, "Recently Completed Workorders")})
                else:
                    return jsonify({"reply": ["✅ No completed workorders found"]})
            
            # 10. Show all spare parts
            if any(phrase in user_input for phrase in [
                "show all spare parts", "list spare parts", "all spare parts",
                "spare parts list", "show spare parts"
            ]):
                spareparts = get_all_spareparts()
                return jsonify({"reply": format_maintenance_response(spareparts, "Spare Parts")})
            
            # 11. Spare part details
            sparepart_match = re.search(r"\b([A-Z]+-[A-Z]+-\d+)\b", user_input)
            if sparepart_match or any(phrase in user_input for phrase in [
                "spare part details", "sparepart details", "show spare part"
            ]):
                if sparepart_match:
                    sparepart_code = sparepart_match.group()
                else:
                    words = user_input.split()
                    for i, word in enumerate(words):
                        if word in ["spare", "part", "sparepart"] and i+1 < len(words):
                            sparepart_code = words[i+1].upper()
                            break
                    else:
                        sparepart_code = None
                
                if sparepart_code:
                    sparepart = MAINTENANCE_COLLECTIONS["spareparts"].find_one({
                        "sparepartcode": sparepart_code
                    })
                    if sparepart:
                        response = [f"🔩 **Spare Part Details:**"]
                        response.append(f"**Code:** {sparepart.get('sparepartcode', 'N/A')}")
                        response.append(f"**Name:** {sparepart.get('sparepartsname', 'N/A')}")
                        response.append(f"**Department:** {sparepart.get('department', 'N/A')}")
                        response.append(f"**Make:** {sparepart.get('make', 'N/A')}")
                        response.append(f"**Supplier:** {sparepart.get('suplier', 'N/A')}")
                        response.append(f"**Model:** {sparepart.get('model', 'N/A')}")
                        response.append(f"**Serial Number:** {sparepart.get('serialnumber', 'N/A')}")
                        response.append(f"**Group:** {sparepart.get('groupname', 'N/A')}")
                        
                        if sparepart.get('notes'):
                            response.append(f"**Notes:** {sparepart.get('notes')}")
                        
                        return jsonify({"reply": response})
                    else:
                        return jsonify({"reply": [f"❌ Spare part '{sparepart_code}' not found"]})
            
            # 12. Show all groups
            if any(phrase in user_input for phrase in [
                "show all groups", "list groups", "equipment groups"
            ]):
                groups = get_all_groups()
                return jsonify({"reply": format_maintenance_response(groups, "Equipment Groups")})
            
            # 13. Show all makes
            if any(phrase in user_input for phrase in [
                "show all makes", "list makes", "equipment makes"
            ]):
                makes = get_all_makes()
                return jsonify({"reply": format_maintenance_response(makes, "Equipment Makes")})
            
            # 14. Show all suppliers (maintenance) - VERY SPECIFIC CHECK
            if any(phrase in user_input for phrase in [
                "show all suppliers maintenance", "maintenance suppliers", "suppliers maintenance",
                "maintenance supplier list", "show maintenance suppliers"
            ]):
                suppliers = get_all_suppliers_maint()
                return jsonify({"reply": format_maintenance_response(suppliers, "Suppliers (Maintenance)")})
            
            # 15. Show all locations (maintenance) - check context
            if any(phrase in user_input for phrase in [
                "show locations", "list locations", "all locations"
            ]) and ("maintenance" in user_input or context_tracker.get_context() == "maintenance"):
                locations = get_all_locations_maint()
                return jsonify({"reply": format_maintenance_response(locations, "Locations (Maintenance)")})
            
            # 16. Asset status summary
            if any(phrase in user_input for phrase in [
                "asset status", "equipment status summary", "asset summary"
            ]):
                pipeline = [
                    {"$group": {"_id": "$status", "count": {"$sum": 1}}}
                ]
                results = list(MAINTENANCE_COLLECTIONS["equipments"].aggregate(pipeline))
                status_counts = {r["_id"]: r["count"] for r in results}
                
                total = sum(status_counts.values())
                response = ["🏭 **Asset Status Summary:**", ""]
                
                for status, count in status_counts.items():
                    percentage = (count / total * 100) if total > 0 else 0
                    response.append(f"• **{status}:** {count} assets ({percentage:.1f}%)")
                
                response.append("")
                response.append(f"📊 **Total Assets:** {total}")
                return jsonify({"reply": response})
            
            # 17. If no specific maintenance query matched, show maintenance help with buttons (ONLY BUTTONS)
            return jsonify({
                "reply": [
                    "🔧 **Maintenance Query Detected**",
                    "",
                    "Click any button below for maintenance queries:"
                ],
                "buttons": MAINTENANCE_BUTTONS
            })

    # --- INVENTORY QUERIES ---
    # Check for inventory keywords or if we're in inventory context
    if (any(keyword in user_input for keyword in INVENTORY_KEYWORDS) or 
        is_inventory_context or 
        "inventory what locations are available?" in user_input):
        
        context_tracker.set_context("inventory")
        
        # ADD THIS CHECK RIGHT HERE - Handle project IPRC details first
        if any(phrase in user_input for phrase in ["project details", "iprc details", "project iprc", "project info", "project iprc details"]):
            # Get project ID
            project_id = "IPRC"
            if "iprc" in user_input.lower():
                project_id = "IPRC"
            else:
                words = user_input.split()
                for i, word in enumerate(words):
                    if word.lower() in ["project", "proj"] and i+1 < len(words):
                        project_id = words[i+1].upper()
                        break
                
                if not project_id:
                    # Try to extract project ID from the input
                    for word in words:
                        if re.match(r'^\d+$', word):
                            project_id = word
                            break
                
                if not project_id:
                    project_id = "IPRC"
            
            project = get_project_by_id(project_id)
            
            if not project:
                # Try searching by title
                project = INVENTORY_COLLECTIONS["projects"].find_one(
                    {"Title": {"$regex": project_id, "$options": "i"}}
                )
            
            if project:
                response = format_inventory_response(project, f"Project: {project.get('Title', 'N/A')}")
                # Add additional details if available
                if isinstance(project, dict):
                    response.insert(1, f"**Project ID:** {project.get('ProjectId', 'N/A')}")
                    response.insert(2, f"**Client:** {project.get('Client', 'N/A')}")
                    response.insert(3, f"**Status:** {project.get('Status', 'N/A')}")
                    if project.get('Description'):
                        response.insert(4, f"**Description:** {project.get('Description', 'N/A')}")
                return jsonify({"reply": response})
            else:
                return jsonify({"reply": [f"❌ Project '{project_id}' not found. Try 'show all projects' to see available projects."]})
        
        # 1. Show all inventory help - ONLY SHOW BUTTONS
        if any(word in user_input for word in ["inventory help", "inventory commands", "inventory what can i ask"]):
            return jsonify({
                "reply": [
                    "📦 **Inventory Management**",
                    "",
                    "Click any button below for inventory queries:"
                ],
                "buttons": INVENTORY_BUTTONS
            })
        
        # 2. Recent stock movements query
        if any(phrase in user_input for phrase in [
            "recent stock movements", "stock movements", "recent movements",
            "stock transfers", "material movements", "recent distributions",
            "movement history", "transfer history"
        ]):
            movements = get_recent_stock_movements(limit=10)
            if movements:
                response = ["📊 **Recent Stock Movements (Last 10):**"]
                for i, movement in enumerate(movements, 1):
                    movement_type = movement.get('movementType', movement.get('type', 'Movement'))
                    product_name = movement.get('productName', movement.get('product', 'Unknown'))
                    product_id = movement.get('productId', 'N/A')
                    
                    response.append(f"{i}. **{movement_type}**")
                    response.append(f"   Product: {product_name} ({product_id})")
                    response.append(f"   Quantity: {movement.get('quantity', 0)}")
                    
                    if movement.get('fromLocation'):
                        response.append(f"   From: {movement.get('fromLocation')}")
                    if movement.get('toLocation'):
                        response.append(f"   To: {movement.get('toLocation')}")
                    if movement.get('date'):
                        response.append(f"   Date: {movement.get('date')}")
                    if movement.get('reason'):
                        response.append(f"   Reason: {movement.get('reason')}")
                    if movement.get('issuedBy'):
                        response.append(f"   Issued By: {movement.get('issuedBy')}")
                    
                    response.append("")
                
                return jsonify({"reply": response})
            else:
                return jsonify({"reply": ["✅ No recent stock movements found."]})
        
        # 3. Available locations query - SPECIFICALLY FOR INVENTORY
        if any(phrase in user_input for phrase in [
            "available locations", "locations available", "locations with space",
            "vacant locations", "empty locations", "locations with capacity",
            "where is space available", "which locations have space",
            "what locations are available", "inventory what locations are available"
        ]) and not any(keyword in user_input for keyword in MAINTENANCE_SPECIFIC_KEYWORDS):
            available_locations = get_available_locations()
            if available_locations:
                response = ["✅ **Available Inventory Locations with Capacity:**"]
                total_available = 0
                
                for location in available_locations:
                    name = location.get('name', 'Unknown')
                    location_id = location.get('locationId', 'N/A')
                    current = location.get('currentUtilization', 0)
                    total = location.get('totalCapacity', 0)
                    available = location.get('totalAvailableCapacity', 0)
                    utilization_percent = (current / total * 100) if total > 0 else 0
                    
                    total_available += available
                    
                    response.append(f"📍 **{name}** (ID: {location_id})")
                    response.append(f"   📦 Capacity: {current}/{total} ({utilization_percent:.1f}% utilized)")
                    response.append(f"   🆓 Available: {available} units")
                    
                    if location.get('racks'):
                        racks = location.get('racks', [])
                        response.append(f"   🗄️ Racks: {len(racks)}")
                        for rack in racks[:2]:
                            rack_name = rack.get('name', 'Unnamed')
                            rack_capacity = rack.get('capacity', 'N/A')
                            response.append(f"      • {rack_name} (Capacity: {rack_capacity})")
                        if len(racks) > 2:
                            response.append(f"      ... and {len(racks) - 2} more racks")
                    
                    response.append("")
                
                response.append(f"📊 **Total Available Capacity:** {total_available} units across {len(available_locations)} locations")
                return jsonify({"reply": response})
            else:
                return jsonify({"reply": ["⚠️ No inventory locations with available capacity found. All locations are at full capacity."]})
        
        # 4. Search for products
        search_match = re.search(r"(find|search|show|list).*product[s]?\s+(.+)", user_input)
        if search_match or any(phrase in user_input for phrase in ["find product", "search product", "products like"]):
            search_term = search_match.group(2) if search_match else user_input.split("product")[-1].strip()
            products = search_inventory_products(search_term)
            if products:
                return jsonify({"reply": format_inventory_response(products, f"Products matching '{search_term}'")})
            else:
                return jsonify({"reply": [f"❌ No products found matching '{search_term}'"]})
        
        # 5. Get specific product details
        product_id_match = re.search(r"\b(BHEL\s*[-\s]*[A-Z]+\s*[-\s]*\d+)\b", user_input, re.IGNORECASE)
        if product_id_match or any(phrase in user_input for phrase in ["details of product", "product details for"]):
            if product_id_match:
                product_id = product_id_match.group().replace(" ", "").upper()
            else:
                words = user_input.split()
                for i, word in enumerate(words):
                    if word in ["product", "id", "code"] and i+1 < len(words):
                        product_id = words[i+1].upper()
                        break
                else:
                    product_id = None
            
            if product_id:
                product = get_product_by_id(product_id)
                if product:
                    stocks = get_stock_by_product(product_id)
                    
                    response = [f"📱 **Product Details: {product.get('name', 'N/A')}**"]
                    response.append(f"**ID:** {product.get('productId', 'N/A')}")
                    response.append(f"**Category:** {product.get('category', 'N/A')}")
                    response.append(f"**Description:** {product.get('description', 'N/A')}")
                    response.append(f"**Make:** {product.get('make', 'N/A')}")
                    response.append(f"**Part Number:** {product.get('partNumber', 'N/A')}")
                    response.append(f"**Quantity Available:** {product.get('quantity', 0)} {product.get('unit', '')}")
                    
                    if product.get('price'):
                        price_info = product['price']
                        if isinstance(price_info, dict):
                            response.append(f"**Price:** ₹{price_info.get('value', 'N/A')}")
                    
                    response.append(f"**Low Stock Threshold:** {product.get('lowStockValue', 'N/A')}")
                    
                    movements = get_stock_movements_by_product(product_id)
                    if movements:
                        response.append("")
                        response.append("📊 **Recent Stock Movements:**")
                        recent_movements = movements[-5:]
                        for move in reversed(recent_movements):
                            move_type = move.get('type', 'Movement')
                            response.append(f"  • **{move_type}**: {move.get('quantity', 0)} units")
                            if move.get('date'):
                                response.append(f"    Date: {move.get('date')}")
                            if move.get('toLocation'):
                                response.append(f"    To: {move.get('toLocation')}")
                            if move.get('fromLocation'):
                                response.append(f"    From: {move.get('fromLocation')}")
                            response.append("")
                    
                    if stocks:
                        response.append("")
                        response.append("📦 **Stock Details:**")
                        total_qty = sum(stock.get('quantity', 0) for stock in stocks)
                        response.append(f"**Total Stock Quantity:** {total_qty} {product.get('unit', '')}")
                        
                        for stock in stocks:
                            response.append(f"  • **Serial:** {stock.get('serialNo', 'N/A')}")
                            response.append(f"    **Quantity:** {stock.get('quantity', 0)}")
                            response.append(f"    **Location:** {stock.get('locationId', 'Not assigned')}")
                            response.append(f"    **Condition:** {stock.get('conditionofproduct', 'N/A')}")
                            if stock.get('price'):
                                stock_price = stock['price']
                                if isinstance(stock_price, dict):
                                    response.append(f"    **Price:** ₹{stock_price.get('value', 'N/A')}")
                            response.append("")
                    else:
                        response.append("⚠️ **No stock records found for this product**")
                    
                    return jsonify({"reply": response})
                else:
                    return jsonify({"reply": [f"❌ Product '{product_id}' not found"]})
        
        # 6. Low stock products
        if any(phrase in user_input for phrase in ["low stock", "low inventory", "running out", "need to order"]):
            low_stock = get_low_stock_products()
            if low_stock:
                response = ["⚠️ **Low Stock Products (below threshold):**"]
                for product in low_stock:
                    response.append(f"• **{product.get('name', 'N/A')}** (ID: {product.get('productId', 'N/A')})")
                    response.append(f"  Quantity: {product.get('quantity', 0)} / Threshold: {product.get('lowStockValue', 'N/A')}")
                    response.append(f"  Category: {product.get('category', 'N/A')}")
                    response.append("")
                return jsonify({"reply": response})
            else:
                return jsonify({"reply": ["✅ All products are above low stock threshold"]})
        
        # 7. Show all categories
        if any(phrase in user_input for phrase in ["show categories", "list categories", "all categories", "product categories", "show all categories"]):
            categories = get_all_categories()
            return jsonify({"reply": format_inventory_response(categories, "Inventory Categories")})
        
        # 8. Show all locations - SPECIFICALLY FOR INVENTORY
        if any(phrase in user_input for phrase in [
            "show locations", "list locations", "all locations", "warehouse locations"
        ]) and not any(keyword in user_input for keyword in MAINTENANCE_SPECIFIC_KEYWORDS):
            locations = get_all_locations()
            return jsonify({"reply": format_inventory_response(locations, "Inventory Locations")})
        
        # 9. Get specific location details
        location_match = re.search(r"\b(LOC[-\s]*\d+[-\s]*\d+)\b", user_input, re.IGNORECASE)
        if location_match or any(phrase in user_input for phrase in ["location details", "capacity of location", "location info"]):
            if location_match:
                location_id = location_match.group().replace(" ", "").upper()
            elif "factory" in user_input:
                location = INVENTORY_COLLECTIONS["locations"].find_one({"name": "FACTORY"})
                if location:
                    return jsonify({"reply": format_inventory_response(location, "Factory Location")})
                else:
                    return jsonify({"reply": ["❌ Factory location not found"]})
            else:
                words = user_input.split()
                for i, word in enumerate(words):
                    if word in ["location", "warehouse", "storage"] and i+1 < len(words):
                        location_name = words[i+1].upper()
                        location = INVENTORY_COLLECTIONS["locations"].find_one({"name": location_name})
                        if location:
                            return jsonify({"reply": format_inventory_response(location, f"Location: {location_name}")})
                        else:
                            return jsonify({"reply": [f"❌ Location '{location_name}' not found"]})
            
            if location_id:
                location = get_location_by_id(location_id)
                if location:
                    location_movements = get_stock_movements_by_location(location_id)
                    
                    response = format_inventory_response(location, f"Location: {location_id}")
                    if location_movements:
                        response.append("")
                        response.append("📊 **Recent Movements at this Location:**")
                        recent_movements = location_movements[:5]
                        for move in recent_movements:
                            move_type = move.get('type', 'Movement')
                            product_name = move.get('productName', 'Unknown')
                            response.append(f"  • **{move_type}**: {product_name}")
                            response.append(f"    Quantity: {move.get('quantity', 0)}")
                            if move.get('date'):
                                response.append(f"    Date: {move.get('date')}")
                            response.append("")
                    
                    return jsonify({"reply": response})
                else:
                    return jsonify({"reply": [f"❌ Location '{location_id}' not found"]})
        
        # 10. Show all suppliers (FIXED: Now fetches from inventorysuppliers)
        if any(phrase in user_input for phrase in ["show suppliers", "list suppliers", "all suppliers", "vendor list", "show all suppliers"]):
            suppliers = get_all_suppliers()
            if suppliers:
                return jsonify({"reply": format_inventory_response(suppliers, "Inventory Suppliers")})
            else:
                return jsonify({"reply": ["❌ No suppliers found in inventory"]})
                
        # 11. Get specific supplier details
        if any(phrase in user_input for phrase in ["supplier details", "vendor details", "siemens details"]):
            supplier_name = None
            if "siemens" in user_input:
                supplier_name = "Siemens"
            else:
                words = user_input.split()
                for i, word in enumerate(words):
                    if word in ["supplier", "vendor", "company"] and i+1 < len(words):
                        supplier_name = words[i+1].title()
                        break
            
            if supplier_name:
                supplier = INVENTORY_COLLECTIONS["suppliers"].find_one({"name": {"$regex": supplier_name, "$options": "i"}})
                if supplier:
                    return jsonify({"reply": format_inventory_response(supplier, f"Supplier: {supplier.get('name', 'N/A')}")})
                else:
                    return jsonify({"reply": [f"❌ Supplier '{supplier_name}' not found in inventory"]})
        
        # 12. Show all projects (FIXED: Now properly fetches from inventoryprojects)
        if any(phrase in user_input for phrase in ["show projects", "list projects", "all projects", "show all projects"]):
            projects = get_all_projects()
            if projects:
                return jsonify({"reply": format_inventory_response(projects, "Projects")})
            else:
                return jsonify({"reply": ["❌ No projects found"]})
        
        # 13. Get specific project details (FIXED: Now properly fetches project details)
        project_match = re.search(r"\b(IPRC|001|ISRO)\b", user_input, re.IGNORECASE)
        if project_match or any(phrase in user_input for phrase in ["project details", "iprc details", "project iprc", "project info", "project iprc details"]):
            if project_match:
                project_id = project_match.group().upper()
            elif "iprc" in user_input.lower():
                project_id = "IPRC"
            else:
                words = user_input.split()
                project_id = None
                for i, word in enumerate(words):
                    if word.lower() in ["project", "proj"] and i+1 < len(words):
                        project_id = words[i+1].upper()
                        break
                
                if not project_id:
                    # Try to extract project ID from the input
                    for word in words:
                        if re.match(r'^\d+$', word):
                            project_id = word
                            break
                
                if not project_id:
                    project_id = "IPRC"
            
            project = get_project_by_id(project_id)
            
            if not project:
                # Try searching by title
                project = INVENTORY_COLLECTIONS["projects"].find_one(
                    {"Title": {"$regex": project_id, "$options": "i"}}
                )
            
            if project:
                response = format_inventory_response(project, f"Project: {project.get('Title', 'N/A')}")
                # Add additional details if available
                if isinstance(project, dict):
                    response.insert(1, f"**Project ID:** {project.get('ProjectId', 'N/A')}")
                    response.insert(2, f"**Client:** {project.get('Client', 'N/A')}")
                    response.insert(3, f"**Status:** {project.get('Status', 'N/A')}")
                    if project.get('Description'):
                        response.insert(4, f"**Description:** {project.get('Description', 'N/A')}")
                return jsonify({"reply": response})
            else:
                return jsonify({"reply": [f"❌ Project '{project_id}' not found. Try 'show all projects' to see available projects."]})
        
        # 14. Show all products
        if any(phrase in user_input for phrase in ["show all products", "list all products", "all products"]):
            products = list(INVENTORY_COLLECTIONS["products"].find().limit(20))
            if products:
                return jsonify({"reply": format_inventory_response(products, "All Products")})
            else:
                return jsonify({"reply": ["❌ No products found"]})
        
        # 15. Show all stock
        if any(phrase in user_input for phrase in ["show all stock", "list all stock", "all stock items"]):
            stocks = list(INVENTORY_COLLECTIONS["stocks"].find().limit(20))
            if stocks:
                return jsonify({"reply": format_inventory_response(stocks, "All Stock Items")})
            else:
                return jsonify({"reply": ["❌ No stock items found"]})
        
        # 16. Search stock by serial number
        serial_match = re.search(r"\b(\d{5,})\b", user_input)
        if serial_match and any(word in user_input for word in ["serial", "sn", "serial number"]):
            serial_no = serial_match.group()
            stock = INVENTORY_COLLECTIONS["stocks"].find_one({"serialNo": serial_no})
            if stock:
                return jsonify({"reply": format_inventory_response(stock, f"Stock Item (Serial: {serial_no})")})
            else:
                return jsonify({"reply": [f"❌ No stock found with serial number '{serial_no}'"]})
        
        # 17. Products by category
        if any(phrase in user_input for phrase in ["products in category", "electronics products", "category electronics"]):
            category_name = None
            if "electronics" in user_input:
                category_name = "ELECTRONICS"
            else:
                words = user_input.split()
                for i, word in enumerate(words):
                    if word in ["category", "type"] and i+1 < len(words):
                        category_name = words[i+1].upper()
                        break
            
            if category_name:
                products = list(INVENTORY_COLLECTIONS["products"].find({"category": {"$regex": category_name, "$options": "i"}}))
                if products:
                    return jsonify({"reply": format_inventory_response(products, f"Products in Category: {category_name}")})
                else:
                    return jsonify({"reply": [f"❌ No products found in category '{category_name}'"]})
        
        # 18. If no specific inventory query matched, show inventory help with buttons (ONLY BUTTONS)
        return jsonify({
            "reply": [
                "📦 **Inventory Query Detected**",
                "",
                "Click any button below for inventory queries:"
            ],
            "buttons": INVENTORY_BUTTONS
        })

    # Case 1: Cumulative person (employee/visitor) violations
    id_match = re.search(r"\b(adv\d{2,4}|emp\d{2,4}|vst\d{2,4})\b", user_input, re.IGNORECASE)
    if id_match and any(word in user_input for word in ["violation", "alert", "incident", "ppe", "slip", "record"]):
        person_id = id_match.group().upper()
        person = get_person_details(person_id)

        if not person:
            return jsonify({"reply": [f"❌ No record found with ID {person_id}."]})

        emp_id = person.get("personId")

        # Fetch violations across all collections
        violations = get_violations_by_employee(emp_id)
        if not violations:
            return jsonify({"reply": [f"✅ No violations found for {emp_id} ({person.get('name','Unknown')})."]})

        # Format response
        response = [f"📋 **Violations for {emp_id} ({person.get('name','Unknown')})**:"]
        for v in violations[:5]:
            ts = v.get("timestamp", "N/A")
            # Include only relevant fields (exclude internal/extraneous ones)
            details = ", ".join([
                f"{k}: {v[k]}" for k in v
                if k not in EXCLUDED_FIELDS and k not in ["_id", "__v", "source", "timestamp"] 
                and not isinstance(v[k], (dict, list))
            ])
            response.append(f"🔸 {ts} | Source: {v['source']} | {details}")

        return jsonify({"reply": response})

    
    # Case 2:  employee/visitor details
    id_match = re.search(r"\b(adv\d{2,4}|emp\d{2,4}|vst\d{2,4})\b", user_input, re.IGNORECASE)
    if id_match:
        person_id = id_match.group().upper()
        person = get_person_details(person_id)
        
        if person:
            if person.get("personType") == "employee":
                response = (
                    "🧑‍🏭 **Employee Details:**\n\n"
                    f"👤 Name: **{person.get('name', 'N/A')}**\n"
                    f"📧 Email: {person.get('email', 'N/A')}**\n"
                    f"📞 Mobile: {person.get('mobileNumber', 'N/A')}**\n"
                    f"🏢 Dept: {person.get('department', 'N/A')}**\n"
                    f"💼 Designation: {person.get('designation', 'N/A')}**\n"
                    f"📍 Location: {person.get('location', 'N/A')}**\n"
                    f"🆔 RFID: {person.get('rfid', 'N/A')}**\n"
                )
            elif person.get("personType") == "visitor":
                response = (
                    "🧑‍💼 **Visitor Details:**\n\n"
                    f"👤 Name: **{person.get('name', 'N/A')}**\n"
                    f"🏢 Company: {person.get('company', 'N/A')}**\n"
                    f"💼 Designation: {person.get('designation', 'N/A')}**\n"
                    f"🎯 Purpose: {person.get('purpose', 'N/A')}**\n"
                    f"📅 From: {person.get('fromDateTime', 'N/A')}**\n"
                    f"📅 To: {person.get('toDateTime', 'N/A')}**\n"
                )
            else:
                response = f"⚠️ Record found but unknown personType: {person.get('personType')}"
        else:
            response = f"❌ No record found with ID {person_id}."

        return jsonify({"reply": response.strip().split("\n")})
        
    # case 3 : 
    unauth_terms = ["unauthorized", "trespass", "intruder", "unidentified", "trespasser",
                    "trespassing", "entered illegally", "someone not allowed", "intrusion",
                    "not authorized", "unknown person", "out of work", "stranger", "trespassed"]
    auth_terms = ["authorized", "permitted", "allowed"]

    if any(re.search(rf"\b{re.escape(term)}\b", user_input) for term in unauth_terms + auth_terms):
        result = get_latest_from_collections(["unauthorizedentries"], user_input=user_input)
        doc, _ , _= result.get("unauthorizedentries", (None, None,None))
        if not doc:
            return jsonify({"reply": "✅ No matching unauthorized or authorized entries found yet."})
        ts = doc.get("timestamp") or doc.get("start_timestamp") or doc.get("createdAt") or (doc.get("_id").generation_time if isinstance(doc.get("_id"), ObjectId) else "N/A")
        ts = str(ts)
        response = [
            f"📢 Last Alert Summary from **{doc.get('scenario', 'entry')}** at 🕒 **{ts}**:",
            f"\n🔸 Employee Id: **{doc.get('employee_id', 'N/A')}**",
            f"\n🔸 Scenario: **{doc.get('scenario', 'N/A')}**",
            f"\n⚠️ Priority: **{doc.get('priority', 'N/A')}**",
            f"\n🔸 Cameralocationid: **{doc.get('cameralocationid', 'N/A')}**",
            f"\n🔸 Location Name: **{doc.get('location_name', 'N/A')}**",
            f"\n🔸 Start Timestamp: **{str(doc.get('start_timestamp', 'N/A'))}**",
            f"\n🔸 Seconds: **{doc.get('seconds', 'N/A')}**",
            f"\n🔸 Minutes: **{doc.get('minutes', 'N/A')}**",
            f"\n🔸 Hours: **{doc.get('hours', 'N/A')}**"
        ]
        return jsonify({"reply": response})    

    # Fire/Smoke Incident Today
    UNSAFE_KEYWORDS = [
    "fire", "smoke", "ppe", "unauthorized", "unauthorised",
    "trespass", "trespasser", "trespassers", "intruder", "intruders",
    "occupancy", "leak", "leakage", "gas", "slip", "unauthorised entry","hazard warnings","worker health & safety","compliance policies"
    ]
    if is_today_incident_query(user_input) and any(term in user_input.lower() for term in UNSAFE_KEYWORDS):
        today = datetime.now().date()
        matched_records = []
        for col in ALL_COLLECTIONS:
            collection = db[col]
            query = {
                "$or": [
                    {"timestamp_alert_start": {"$gte": datetime.combine(today, datetime.min.time())}},
                    {"createdAt": {"$gte": datetime.combine(today, datetime.min.time())}}
                ]
            }
            record = collection.find_one(query, sort=[
                ("timestamp_alert_start", DESCENDING),
                ("createdAt", DESCENDING),
                ("_id", DESCENDING)
            ])
            if record:
                record["source"] = col
                matched_records.append(record)

        if matched_records:
            responses = []
            for rec in matched_records:
                ts = get_valid_timestamp(rec)
                source = rec.get("source", "unknown")
                response_lines = [f"🔥 **Incident detected today in `{source}`**:"]
                for k, v in rec.items():
                    if k not in EXCLUDED_FIELDS and not isinstance(v, (dict, list)):
                        emoji = EMOJI_MAP.get(k, "🔹")
                        response_lines.append(f"{emoji} **{k}**: {v}")
                responses.append("\n".join(response_lines))
            return jsonify({"reply": responses})
        else:
            return jsonify({"reply": ["✅ No violation or incidents recorded today across monitored modules."]})


    # --- Step 2: Generic "today alerts" across all modules ---
    if "today" in user_input and any(term in user_input for term in ["alert", "incident", "violation"]):
        today = datetime.today().date()
        results_today = []
        for col_name in ALL_COLLECTIONS:
            collection = db[col_name]
            docs = collection.find().sort([
                ("timestamp", -1),
                ("start_timestamp", -1),
                ("createdAt", -1),
                ("_id", -1)
            ])
            for doc in docs:
                doc_time = (
                    doc.get("timestamp") or
                    doc.get("start_timestamp") or
                    doc.get("createdAt") or
                    (doc["_id"].generation_time if isinstance(doc.get("_id"), ObjectId) else None)
                )
                if doc_time and doc_time.date() == today:
                    results_today.append((doc, col_name))
                    break

        if results_today:
            response_lines = ["📅 **Alerts/Incidents/Violations Today:**"]
            for doc, col in results_today:
                ts = doc.get("timestamp") or doc.get("start_timestamp") or doc.get("createdAt") or (doc["_id"].generation_time if isinstance(doc.get("_id"), ObjectId) else "N/A")
                module = doc.get("scenario") or doc.get("module") or col.replace("_", " ").title()
                response_lines.append(f"• **{module}** reported something at 🕒 **{ts}**")
            return jsonify({"reply": response_lines})
        else:
            return jsonify({"reply": "✅ No alerts, incidents, or violations reported today."})    

    if is_about_app(user_input):
        return jsonify({"reply": [
            "🛡️ **OptiMES – Safety Management System**",
            "It ensures industrial safety, compliance, and awareness across:",
            "1️⃣ Hazard Warnings – Fire, smoke, gas leak incidents.",
            "2️⃣ Worker Health & Safety – Slips, PPE violations, worker safety.",
            "3️⃣ Compliance Policies – Occupancy control, unauthorized entry.",
            "",
            "💡 You can also ask about:",
            "• 📦 **Inventory Management** - Products, stock, locations",
            "• 🔧 **Maintenance (CMMS)** - Equipment, workorders, spare parts",
            "• 📋 **Work Permits** - Status, approvals, worker details",
            "• 📊 **Production & Energy** - Daily output, energy costs"
        ]})
    

    if any(greet in user_input for greet in ["hi", "hello", "hey"]):
        return jsonify({
            "reply": "👋 Hello! I'm your OptiMES assistant. I can help you with Safety, Inventory, Maintenance (CMMS), Work Permits, and Production data. How can I assist you today?",
            "buttons": PRODUCTION_ENERGY_BUTTONS
        })

    if any(word in user_input for word in ["thank you", "thanks"]):
        return jsonify({"reply": "😊 You're welcome!"})

    if any(word in user_input for word in ["help", "assist", "support"]):
        return jsonify({
            "reply": [
                "🆘 **I can help you with:**",
                "",
                "🔐 **Safety:** 'last alert', 'employee violations ADV001', 'today's incidents'",
                "📦 **Inventory:** 'find product laptop', 'low stock', 'available locations'",
                "🔧 **Maintenance (CMMS):** 'cmms help', 'workorder status', 'equipment under maintenance'",
                "📋 **Work Permits:** 'permit status', 'pending permits', 'permit PW-2024-001'",
                "📊 **Production:** 'production today', 'energy cost', 'lowest production shift'",
                "",
                "💡 Try any of the buttons below or ask a specific question!"
            ],
            "buttons": PRODUCTION_ENERGY_BUTTONS
        })
    
    
     # Try to infer collections first
    collections = infer_collections_from_input(user_input)
    # Fallback: use SCENARIO_COLLECTION_MAP if user refers to a module (like "hazard warnings")
    if not collections:
        for scenario, cols in SCENARIO_COLLECTION_MAP.items():
            if scenario.rstrip("s") in user_input or scenario in user_input:
                collections = cols
                break

    # Still nothing? Try keyword-based logic
    if not collections:
        if "fire" in user_input or "smoke" in user_input or "fire extinguisher" in user_input:
             collections = ["fires"]
        elif "gas" in user_input:
            collections = ["gasleakages"]
        elif "slip" in user_input:
            collections = ["slips"]
        elif "health" in user_input or "safety" in user_input:
            collections = ["slips", "ppekits"]
        elif any(term in user_input for term in ["compliance exceedance", "occupancy", "vacancy"]):
            collections = ["occupancies"]
        elif any(term in user_input for term in ["trespass", "trespasser", "unauthorized", "intruder", "unidentified person"]):
            collections = ["unauthorizedentries"]
        elif "compliance" in user_input or "policies" in user_input:
            collections = ["occupancies", "unauthorizedentries"]

    # As a last resort, if nothing matched
    if not collections:
        print("⚠️ No specific module inferred. Falling back to ALL collections.")
        collections = ALL_COLLECTIONS

    latest_docs = get_latest_from_collections(collections, user_input=user_input)

    latest_doc = None
    latest_time = datetime.min.replace(tzinfo=timezone.utc)
    latest_collection = None
    
    #for doc, col_name in latest_docs.values():
    for parent_doc, frame_doc, col_name in latest_docs.values():
        if parent_doc:
            doc_time = (
                parent_doc.get("timestamp") or
                parent_doc.get("start_timestamp") or
                parent_doc.get("createdAt") or
                (parent_doc["_id"].generation_time if isinstance(parent_doc.get("_id"), ObjectId) else None)
            )
            print(f"🧪 Checking document in collection: '{col_name}' with doc_time: {doc_time}")
        
            if not doc_time:
                _id = parent_doc.get("_id", "unknown")
                print(f"⚠️ No timestamp info found in document from '{col_name}' with _id: {_id}")
            # Normalize datetime before comparison
            if doc_time:
                if doc_time.tzinfo is None:
                    doc_time = doc_time.replace(tzinfo=timezone.utc)
                if doc_time > latest_time:
                    latest_time = doc_time
                    latest_doc = parent_doc
                    latest_collection = col_name
                    
    # If still nothing found in collections
    if not latest_doc:
        return jsonify({"reply": [f"✅ No recent alerts found in: {', '.join(collections)}."]})

    # Extract timestamp and module info
    _id = latest_doc.get("_id")
    timestamp = (
        latest_doc.get("timestamp") or
        latest_doc.get("start_timestamp") or
        latest_doc.get("createdAt") or
        (_id.generation_time if isinstance(_id, ObjectId) else "N/A")
    )
    timestamp = str(timestamp)
    module = latest_doc.get("scenario") or latest_doc.get("module") or (latest_collection.replace("_", " ").title() if latest_collection else "Unknown Module")

    summary_lines = [f"📢 Last Alert Summary from {module} at 🕒 **{timestamp}**:\n"]
    print("📄 Entire latest_doc:", latest_doc)
    
    # 1️⃣ First check if 'location ID' is at the root of the latest document
    location_id = None
    if parent_doc:
        for key in ["locationID", "location_id", "locationId", "location ID"]:
            if key in parent_doc:
                location_id = parent_doc[key]
                print(f"✅ Found location in parent: {key} = {location_id}")
                break
    # 2️⃣ If not found, check in selected frame (if available)
    if not location_id and frame_doc:
        for key in ["locationID", "location_id", "locationId", "location ID"]:
            if key in frame_doc:
                location_id = frame_doc[key]
                print(f"✅ Found location ID in frame: {key} = {location_id}")
                break

    # 3️⃣ Optional fallback: match any key with both 'location' and 'id'
    if not location_id and parent_doc:
        for k, v in parent_doc.items():
            if "location" in k.lower() and "id" in k.lower():
                location_id = v
                print(f"✅ Fallback location ID match: {location_id}")
                break
    
    # Insert Location ID if found
    if location_id:
        summary_lines.append(f"🔹 Location ID: **{location_id}**")
    else:
        print("❌ Location ID not found in any source")

    # Show latest frame info (if present)
    if frame_doc:
        for key, value in frame_doc.items():
            if key.startswith("_") or key.lower() in EXCLUDED_FIELDS:
                continue
            emoji = EMOJI_MAP.get(key.lower(), "🔸")
            summary_lines.append(f"{emoji} {key.replace('_', ' ').title()}: **{value}**")
    else:
        # Fallback: loop through top-level fields (only if no frame)
        for key, value in latest_doc.items():
            if key in ["locationID", "location_id", "locationId", "location ID"]:
                # already added
                continue
            if (latest_collection == "ppekits" and key.lower() == "statuschanges") or \
                (key.lower() in EXCLUDED_FIELDS and key.lower() != "statuschanges") or \
                    key.startswith("_"):
                continue
            
            if isinstance(value, dict):
                for subkey, subval in value.items():
                    emoji = EMOJI_MAP.get(subkey.lower(), "🔸")
                    summary_lines.append(f"{emoji} {subkey.replace('_', ' ').title()}: **{subval}**")
            else:
                emoji = EMOJI_MAP.get(key.lower(), "🔸")
                summary_lines.append(f"{emoji} {key.replace('_', ' ').title()}: **{value}**")

    return jsonify({"reply": summary_lines})
  
if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=5001)
