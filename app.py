from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient, DESCENDING
from bson.objectid import ObjectId
from datetime import datetime, timedelta
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

ABOUT_APP_TERMS = [
    "what is this", "what does this do", "about this app", "about this application",
    "what am i looking at", "what can this do", "explain this", "tell me about this",
    "what is this platform", "i don't know what this is", "describe this app",
    "who are you", "what is optimes", "what does optimes do", "explain optimes"
]

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

def get_valid_timestamp(record):
    ts = (
        record.get("timestamp") or
        record.get("start_timestamp") or
        record.get("createdAt") or
        (record.get("_id").generation_time if isinstance(record.get("_id"), ObjectId) else datetime.min)
    )
    return make_naive(ts)

def infer_collections_from_input(user_input):
    input_lower = user_input.lower()
    if "fire" in input_lower or "smoke" in input_lower:
        return ["fires"]
    elif "gas" in input_lower or "leak" in input_lower:
        return ["gasleakages"]
    elif "ppe" in input_lower or "helmet" in input_lower or "vest" in input_lower:
        return ["ppekits"]
    elif "slip" in input_lower or "fall" in input_lower:
        return ["slips"]
    elif "occupancy" in input_lower or "vacancy" in input_lower:
        return ["occupancies"]
    elif any(term in input_lower for term in ["unauthorized", "unauthorised", "authorized", "authorised", "intruder"]):
        return ["unauthorizedentries"]
    else:
        return ALL_COLLECTIONS

def get_violations_by_employee(emp_id):
    results = []
    for col_name in ALL_COLLECTIONS:
        collection = db[col_name]
        if col_name == "ppekits":
            pipeline = [
                {
                    "$lookup": {
                        "from": "employeedatas",
                        "localField": "personName",
                        "foreignField": "_id",
                        "as": "employee_info"
                    }
                },
                {"$unwind": "$employee_info"},
                {"$match": {"employee_info.employee_id": emp_id}}
            ]
            matches = list(collection.aggregate(pipeline))
        else:
            matches = list(collection.find({"employee_id": emp_id}))

        for doc in matches:
            doc["source"] = col_name
            doc["timestamp"] = get_valid_timestamp(doc)
            results.append(doc)

    results.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)
    return results

def get_employee_details(emp_id):
    return db["employeedatas"].find_one({"employee_id": emp_id})

def get_latest_from_collections(collection_names, user_input=None):
    latest_results = {}
    for col_name in collection_names:
        collection = db[col_name]
        filter_query = {}

        if col_name == "unauthorizedentries" and user_input:
            unauth_terms = ["unauthorized", "trespass", "intruder", "unidentified", "stranger", "not authorized", "unknown"]
            auth_terms = ["authorized", "permitted", "allowed"]
            if any(term in user_input for term in unauth_terms):
                filter_query = {"scenario": {"$regex": r"(unauthorized|trespass|intruder|unidentified|stranger|not authorized|unknown)", "$options": "i"}}
            elif any(term in user_input for term in auth_terms):
                filter_query = {"scenario": {"$regex": r"(authorized|permitted|allowed)", "$options": "i"}}
            else:
                filter_query = {"scenario": {"$not": {"$regex": r"^authorized entry$", "$options": "i"}}}

        if is_today_incident_query(user_input):
            today = datetime.now().date()
            start_of_day = datetime.combine(today, datetime.min.time())
            end_of_day = datetime.combine(today, datetime.max.time())
            filter_query["$or"] = [
                {"timestamp": {"$gte": start_of_day, "$lte": end_of_day}},
                {"start_timestamp": {"$gte": start_of_day, "$lte": end_of_day}},
                {"createdAt": {"$gte": start_of_day, "$lte": end_of_day}},
                {"_id": {"$gte": ObjectId.from_datetime(start_of_day)}}
            ]
        

        doc = collection.find_one(filter_query, sort=[
            ("timestamp", DESCENDING),
            ("start_timestamp", DESCENDING),
            ("createdAt", DESCENDING),
            ("_id", DESCENDING)
        ])

        latest_data = None
        if not doc:
            latest_results[col_name] = (None, col_name)
            continue

        for key, value in doc.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                try:
                    latest_nested = max(
                        value,
                        key=lambda x: get_valid_timestamp(x)
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

    if is_about_app(user_input):
        return jsonify({"reply": [
            "🛡️ **OptiMES – Safety Management System**",
            "It ensures industrial safety, compliance, and awareness across:",
            "1️⃣ Hazard Warnings – Fire, smoke, gas leak incidents.",
            "2️⃣ Worker Health & Safety – Slips, PPE violations, worker safety.",
            "3️⃣ Compliance Policies – Occupancy control, unauthorized entry.",
            "💡 You can ask me about recent alerts, employee details, policy breaches, and more."
        ]})
    

    if any(greet in user_input for greet in ["hi", "hello", "hey"]):
        return jsonify({"reply": "👋 Hello! How can I help you with safety insights today?"})

    if any(word in user_input for word in ["thank you", "thanks"]):
        return jsonify({"reply": "😊 You're welcome!"})

    if any(word in user_input for word in ["help", "assist", "support"]):
        return jsonify({"reply": "🆘 Try asking: 'last alert', 'employee violations', or 'details of employee ADV001'"})
    
    if "worker" in user_input and any(word in user_input for word in ["safe", "safety", "status", "okay", "fine", "health", "injury", "accident"]):
        return jsonify({"reply": [
            "🛡️ To know about worker health and safety status, I recommend checking the **Worker Health & Safety** module.",
            "You can ask things like:\n• Show last PPE violation\n• Show latest slip incident\n• Is there any recent safety alert?"
        ]})

    if contains_term(user_input, ["last alert", "last violation", "last incident", "latest alert", "recent incident"]):
        collections_to_check = infer_collections_from_input(user_input)
        latest_results = get_latest_from_collections(collections_to_check, user_input)
        responses = []

        for record, col_name in latest_results.values():
            if record:
                response_lines = [f"⚠️ **Latest Alert from `{col_name}`**:"]
                for key, value in record.items():
                    if key in EXCLUDED_FIELDS or isinstance(value, (dict, list)):
                        continue
                    emoji = EMOJI_MAP.get(key, "🔹")
                    response_lines.append(f"{emoji} **{key}**: {value}")
                responses.append("\n".join(response_lines))

        return jsonify({"reply": responses if responses else ["No alerts found."]})

    # Case 2: Cumulative employee violations
    emp_match = re.search(r"(adv\d+)", user_input)
    if emp_match and any(word in user_input for word in ["violation", "alert", "incident", "ppe", "slip", "record"]):
        emp_id = emp_match.group(1).upper()
        violations = get_violations_by_employee(emp_id)
        if not violations:
            return jsonify({"reply": [f"No violations found for employee {emp_id}."]})
        response = [f"📋 **Violations for {emp_id}**:"]
        for v in violations[:5]:
            ts = v.get("timestamp", "N/A")
            details = ", ".join([f"{k}: {v[k]}" for k in v if k not in EXCLUDED_FIELDS and not isinstance(v[k], (dict, list))])
            response.append(f"🔸 {ts} | Source: {v['source']} | {details}")
        return jsonify({"reply": response})

    # Case 3: Direct employee info
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

    
    # Case 4: Fetch all employees linked to PPE Kits
    if contains_term(user_input, ["ppe", "ppe violation", "ppe kit", "compliance", "person"]):
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

    # return jsonify({"reply": "🤔 I'm not sure how to help with that. Please rephrase your query."})


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
                    {"timestamp": {"$gte": datetime.combine(today, datetime.min.time())}},
                    {"start_timestamp": {"$gte": datetime.combine(today, datetime.min.time())}},
                    {"createdAt": {"$gte": datetime.combine(today, datetime.min.time())}}
                ]
            }
            record = collection.find_one(query, sort=[
                ("timestamp", DESCENDING),
                ("start_timestamp", DESCENDING),
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

    # --- Step 3: General Latest Alert (Fallback) ---
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
