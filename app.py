from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
from datetime import datetime, timezone
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://srmrmpparthiban:20a8yW18xd48XYJ9@cluster0.vviu6.mongodb.net/optimus?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["optimus"]

# Scenario → Collections Map
SCENARIO_COLLECTION_MAP = {
    "hazard warnings": ["fires", "gasleakages", "missingfiredatas"],
    "worker health & safety": ["slips", "ppekits"],
    "compliance policies": ["occupancies", "unauthorizedentries"]
}
ALL_COLLECTIONS = [col for cols in SCENARIO_COLLECTION_MAP.values() for col in cols]

# Emoji mapping for alert fields
EMOJI_MAP = {
    "priority": "⚠️",
    "person_count_status": "👥",
    "vacancy_status": "💺",
    "vacant_count_duration": "⏳",
    "person_count_duration": "⏱️",
    "exceeds_compliance_policy": "🚫",
    "fire_detected": "🔥",
    "smoke_detected": "💨",
    "timestamp_alert_start": "🕒",
    "timestamp_alert_end": "🕓",
    "ppe_compliance": "✅",
    "helmet_status": "🪖",
    "vest_status": "🦺",
    "occupancy_status": "👤",
    "unauthorized_person_detected": "🚷"
}

# Excluded fields
EXCLUDED_FIELDS = {"image", "createdAt", "updatedAt", "compliance frame", "vacant frame", "compliance_frame", "vacant_frame"}

def get_latest_from_collections(collection_names):
    latest_doc = None
    latest_collection = None
    latest_time = None

    for name in collection_names:
        collection = db[name]
        doc = collection.find_one(sort=[("createdAt", -1)]) or collection.find_one(sort=[("_id", -1)])
        if not doc:
            continue

        timestamp = doc.get("createdAt") or doc["_id"].generation_time
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        if not latest_time or timestamp > latest_time:
            latest_doc = doc
            latest_collection = name
            latest_time = timestamp

    if latest_doc:
        latest_doc["module"] = latest_collection
        latest_doc["final_time"] = latest_time
    return latest_doc

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/chat', methods=['POST'])
def chatbot_response():
    user_input = request.json.get("message", "").lower()

    greetings = ["hi", "hello", "hey"]
    thanks = ["thank you", "thanks"]
    help_requests = ["help", "assist", "support"]

    if any(greet in user_input for greet in greetings):
        return jsonify({"reply": "👋 Hello! Welcome to OptiMES. How can I assist you today?"})
    elif any(thank in user_input for thank in thanks):
        return jsonify({"reply": "😊 You're welcome! If you have any more questions, feel free to ask."})
    elif any(help_word in user_input for help_word in help_requests):
        return jsonify({"reply": "🆘 You can ask about latest alerts, full data reports, or module info like:\n• Show last alert of hazard\n• Show full data\n• What module triggered it?"})

    scenario = None

    # Determine collections based on user input
    if "fire" in user_input or "smoke" in user_input or "fire extinguisher" in user_input:
        collections = ["fires"] 
    elif "gas" in user_input:
        collections = ["gasleakages"]
    elif "slip" in user_input:
        collections = ["slips"]
    elif "ppe" in user_input:
        collections = ["ppekits"]
    elif "health" in user_input or "safety" in user_input:
        collections = ["slips", "ppekits"]
    elif "compliance exceedance" in user_input or "occupancy" in user_input or "vacancy" in user_input:
        collections = ["occupancies"]
    elif "unauthorized" in user_input or "entry" in user_input:
        collections = ["unauthorizedentries"]
    elif "compliance" in user_input or "policies" in user_input:
        collections = ["occupancies", "unauthorizedentries"]
    else:
        collections = ALL_COLLECTIONS

    latest_doc = get_latest_from_collections(collections)

    if not latest_doc:
        return jsonify({"reply": "⚠️ No recent data found in the system."})

    module = latest_doc.get("module", "unknown")
    timestamp = str(latest_doc.get("createdAt", latest_doc.get("_id").generation_time))

    # Generate alert summary
    summary_lines = [f"📢 Last Alert Summary from **{module}**:"]
    for key, value in latest_doc.items():
        if key.lower() in EXCLUDED_FIELDS or key.startswith("_") or isinstance(value, dict) or isinstance(value, list):
            continue
        if key == "final_time":
            value = str(value)
        emoji = EMOJI_MAP.get(key.lower(), "🔹")
        summary_lines.append(f"{emoji} {key.replace('_', ' ').title()}: **{value}**")

    reply_text = "\n".join(summary_lines)
    return jsonify({"reply": reply_text})

if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0",port=5001)
