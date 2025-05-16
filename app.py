from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient, DESCENDING
from bson.objectid import ObjectId
from datetime import datetime
from flask_cors import CORS
import os
import re

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://srmrmpparthiban:20a8yW18xd48XYJ9@cluster0.vviu6.mongodb.net/optimus"
client = MongoClient(MONGO_URI)
db = client["optimus"]

# Scenario → Collections Map
SCENARIO_COLLECTION_MAP = {
    "hazard warnings": ["fires", "gasleakages", "missingfiredatas"],
    "worker health & safety": ["slips", "ppekits"],
    "compliance policies": ["occupancies", "unauthorizedentries"]
}
ALL_COLLECTIONS = [col for cols in SCENARIO_COLLECTION_MAP.values() for col in cols]

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
    "compliance_frame", "vacant_frame", "Frame", "frame", "createdat", "updatedat"
}

def contains_term(text, terms):
    for term in terms:
        if re.search(r'\b' + re.escape(term) + r'\b', text):
            return True
    return False

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
                # If no strong keyword match, avoid defaulting to unfiltered (which may return authorized entries)
                filter_query = {"scenario": {"$not": {"$regex": r"^authorized entry$", "$options": "i"}}}
               

        doc = collection.find_one(
            filter_query,
            sort=[
                ("timestamp", DESCENDING),
                ("start_timestamp", DESCENDING),
                ("createdAt", DESCENDING),
                ("_id", DESCENDING)
            ]
        )

        latest_data = None
        if not doc:
            latest_results[col_name] = (None, col_name)
            continue

        for key, value in doc.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                try:
                    latest_nested = max(
                        value,
                        key=lambda x: x.get("timestamp") or
                                      x.get("start_timestamp") or
                                      x.get("createdAt") or
                                      (x.get("_id").generation_time if isinstance(x.get("_id"), ObjectId) else datetime.min)
                    )
                    latest_data = latest_nested
                except Exception:
                    latest_data = value[0]

        latest_results[col_name] = (latest_data if latest_data else doc, col_name)

    return latest_results


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

    if "worker" in user_input and any(word in user_input for word in ["safe", "safety", "status", "okay", "fine", "health", "injury", "accident"]):
        return jsonify({"reply": [
            "🛡️ To know about worker health and safety status, I recommend checking the **Worker Health & Safety** module.",
            "You can ask things like:\n• Show last PPE violation\n• Show latest slip incident\n• Is there any recent safety alert?"
        ]})

    emp_id_match = re.search(r'\badv\d{3}\b', user_input)
    if emp_id_match:
        emp_id = emp_id_match.group().upper()
        emp = db.employeedatas.find_one({"EmployeeID": emp_id})
        if emp:
            response = (
                "🧑‍🏭 **Employee Details:**\n\n"
                f"👤 Name: **{emp.get('Name', 'N/A')}**\n"
                f"📧 Email: {emp.get('EmailID', 'N/A')}\n"
                f"📞 Mobile: {emp.get('Mobilenumber', 'N/A')}\n"
                f"🏢 Dept: {emp.get('Department', 'N/A')}\n"
                f"💼 Designation: {emp.get('Designation', 'N/A')}\n"
                f"📍 Location: {emp.get('Location', 'N/A')}\n"
            )
            return jsonify({"reply": response.strip().split("\n")})
        else:
            return jsonify({"reply": f"❌ No employee found with ID {emp_id}."})

    if contains_term(user_input, ["ppe", "ppe violation", "last ppe", "person"]):
        results = db.ppekits.aggregate([
            {
                "$lookup": {
                    "from": "employeedatas",
                    "localField": "personName",
                    "foreignField": "_id",
                    "as": "employee"
                }
            },
            {"$unwind": "$employee"},
            {
                "$project": {
                    "_id": 0,
                    "name": "$employee.Name",
                    "email": "$employee.EmailID",
                    "designation": "$employee.Designation",
                    "department": "$employee.Department",
                    "location": "$employee.Location",
                    "mobile": "$employee.Mobilenumber"
                }
            }
        ])
        employees = list(results)

        if not employees:
            return jsonify({"reply": "❌ No employee data found linked to PPE kits."})

        response = "🧑‍🏭 **PPE Kit Compliance - Employee Details:**\n\n"
        for emp in employees:
            response += (
                f"👤 Name: **{emp['name']}**\n"
                f"📧 Email: {emp['email']}\n"
                f"📞 Mobile: {emp['mobile']}\n"
                f"🏢 Dept: {emp['department']}\n"
                f"💼 Designation: {emp['designation']}\n"
                f"📍 Location: {emp['location']}\n\n"
            )
        return jsonify({"reply": response.strip().split("\n")})

    unauth_terms = ["unauthorized", "trespass", "intruder", "unidentified", "trespasser",
                    "trespassing", "entered illegally", "someone not allowed", "intrusion",
                    "not authorized", "unknown person", "out of work", "stranger", "trespassed"]
    auth_terms = ["authorized", "permitted", "allowed"]

    if any(re.search(rf"\b{re.escape(term)}\b", user_input) for term in unauth_terms + auth_terms):
        result = get_latest_from_collections(["unauthorizedentries"], user_input=user_input)
        doc, _ = result.get("unauthorizedentries", (None, None))
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

    # Check for "today" related alert queries
    if "today" in user_input and any(term in user_input for term in ["alert", "incident", "violation"]):
        today = datetime.today().date()
        results_today = []

        for col_name in ALL_COLLECTIONS:
            collection = db[col_name]
            docs = collection.find().sort([
                ("timestamp", DESCENDING),
                ("start_timestamp", DESCENDING),
                ("createdAt", DESCENDING),
                ("_id", DESCENDING)
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
                    break  # Just need one per collection if exists

        if results_today:
            response_lines = ["📅 **Alerts/Incidents/Violations Today:**"]
            for doc, col in results_today:
                ts = doc.get("timestamp") or doc.get("start_timestamp") or doc.get("createdAt") or (doc["_id"].generation_time if isinstance(doc.get("_id"), ObjectId) else "N/A")
                ts = str(ts)
                module = doc.get("scenario") or doc.get("module") or col.replace("_", " ").title()
                response_lines.append(f"• **{module}** reported something at 🕒 **{ts}**")
            return jsonify({"reply": response_lines})
        else:
            return jsonify({"reply": "✅ No alerts, incidents, or violations reported today."})

    # Intent-to-collection mapping
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
    else:
        collections = ALL_COLLECTIONS

    latest_docs = get_latest_from_collections(collections, user_input=user_input)

    latest_doc = None
    latest_time = datetime.min
    latest_collection = None
    for doc, col_name in latest_docs.values():
        if doc:
            doc_time = (
                doc.get("timestamp") or
                doc.get("start_timestamp") or
                doc.get("createdAt") or
                (doc["_id"].generation_time if isinstance(doc.get("_id"), ObjectId) else None)
            )
            if doc_time and doc_time > latest_time:
                latest_time = doc_time
                latest_doc = doc
                latest_collection = col_name

    if not latest_doc:
        return jsonify({"reply": "⚠️ No recent data found in the system."})

    _id = latest_doc.get("_id")
    timestamp = (
        latest_doc.get("timestamp") or
        latest_doc.get("start_timestamp") or
        latest_doc.get("createdAt") or
        (_id.generation_time if isinstance(_id, ObjectId) else "N/A")
    )
    timestamp = str(timestamp)

    module = latest_doc.get("scenario") or latest_doc.get("module") or (latest_collection.replace("_", " ").title() if latest_collection else "Unknown Module")

    summary_lines = [f"📢 Last Alert Summary from **{module}** at 🕒 **{timestamp}**:\n"]

    for key, value in latest_doc.items():
        if key.lower() in EXCLUDED_FIELDS or key.startswith("_"):
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