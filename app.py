from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient, DESCENDING
from bson.objectid import ObjectId
from datetime import datetime, timedelta , timezone
from flask_cors import CORS
import os
import re

app = Flask(__name__)
CORS(app)

# MongoDB Connection
# MONGO_URI = "mongodb+srv://srmrmpparthiban:20a8yW18xd48XYJ9@cluster0.vviu6.mongodb.net/optimus"
# MONGO_URI = "mongodb+srv://adventistech2025:XOGhPBZxi0gDSPNO@cluster0.awnrusw.mongodb.net/OptiMES40"
MONGO_URI = "mongodb+srv://adventistech2025:adventistech2025@cluster0.8pgh2fg.mongodb.net/optimestest"
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
    "compliance_frame", "vacant_frame", "Frame", "frame", "createdat", "updatedat","Image","CameraLocationID",
    "seconds","hours","minutes"

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

print(f"📚 All collections in DB: {db.list_collection_names()}")
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
    """
    Fetch all violations/alerts for a person (employee or visitor)
    across all collections, using personId.
    """
    results = []

    for col_name in ALL_COLLECTIONS:
        collection = db[col_name]

        # Query matches either 'employee_id' or 'personName' with the given person_id
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

    # Sort results by timestamp descending
    results.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)
    return results


def get_person_details(person_id):
    person_id = person_id.strip().upper()  # normalize
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

        # ✅ DEBUG LOGS
        print(f"\n🔍 Searching in collection: '{col_name}'")
        print(f"📊 Total documents: {collection.count_documents({})}")
        print(f"🔎 Filter query: {filter_query}")
        try:
            print(f"🧮 Matching docs: {collection.count_documents(filter_query)}")
        except Exception as e:
            print(f"⚠️ Error counting filtered docs in '{col_name}': {e}")

        # 🛠️ TEMP: override filter_query if needed to test
        # if col_name == "ppekits":
        #     print("⚠️ Overriding filter_query for debugging")
        #     filter_query = {}

        # 🔽 Try fetching latest document by timestamp/etc
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

        # Look for a list of frames inside document
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

        # Always return parent_doc, frame_doc, collection name
        latest_results[col_name] = (doc, frame_doc, col_name)

    return latest_results

def get_permit_by_number(permit_number):
    return permit_collection.find_one({"permitNumber": permit_number})

# --- SPECIFIC PERMIT STATUS COUNT ---
def get_specific_permit_status_count(user_input):
    """
    Check if user asks for count of a specific permit status
    and return the count along with normalized status.
    """
    status_terms = ["approved", "pending", "inprogress", "cancelled",
                    "closed", "overdue", "completed", "extended"]

    for status in status_terms:
        if status.replace(" ", "") in user_input.replace(" ", ""):
            # Count documents with case-insensitive match
            count = permit_collection.count_documents({
                "status": {"$regex": f"^{status}$", "$options": "i"}
            })
            return count, status.title()
    return None, None

# --- PERMIT STATUS COUNTS ---
def get_permit_status_counts():
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    results = list(permit_collection.aggregate(pipeline))
    status_counts = {str(r["_id"]).lower(): r["count"] for r in results}

    # Ensure all statuses exist even if count = 0
    all_statuses = ["approved", "pending", "inprogress", "cancelled", 
                    "closed", "overdue", "completed", "extended"]
    for s in all_statuses:
        status_counts.setdefault(s, 0)

    return status_counts


@app.route('/')
def home():
    return render_template("index.html")

@app.route('/chat', methods=['POST'])
def chatbot_response():
    user_input = request.json.get("message", "").lower()

    # --- Case 0: Permit Queries ---
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


    # --- Case 1: Specific Permit Status Count (no permit number, just status) ---
    count, status_title = get_specific_permit_status_count(user_input)
    if count is not None:
        return jsonify({"reply": [f"📊 There are **{count}** permit(s) in **{status_title}** status."]})

    # --- Case 2: Overall Permit Status Summary ---
    if "permit status count" in user_input or "how many permits" in user_input:
        status_counts = get_permit_status_counts()
        reply_lines = ["📊 **Permit Status Summary**:"]
        reply_lines.append(f"✅ Approved: {status_counts['approved']}")
        reply_lines.append(f"🟡 Pending: {status_counts['pending']}")
        reply_lines.append(f"🔵 In Progress: {status_counts['inprogress']}")
        reply_lines.append(f"❌ Cancelled: {status_counts['cancelled']}")
        reply_lines.append(f"🔴 Closed: {status_counts['closed']}")
        reply_lines.append(f"⚠️ Overdue: {status_counts['overdue']}")
        reply_lines.append(f"✅ Completed: {status_counts['completed']}")
        reply_lines.append(f"🟠 Extended: {status_counts['extended']}")
        return jsonify({"reply": reply_lines})


    # --- Case: All pending permits today ---
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

    # --- Case: All pending permits till date ---
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

    # --- Case: Month-wise pending permits count ---
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

    # --- Case: Permits extended beyond original end time ---
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
                    f"📧 Email: {person.get('email', 'N/A')}\n"
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
            
                 
            "💡 You can ask me about recent alerts, employee details, policy breaches, and more."
        ]})
    

    if any(greet in user_input for greet in ["hi", "hello", "hey"]):
        return jsonify({"reply": "👋 Hello! How can I help you with safety insights today?"})

    if any(word in user_input for word in ["thank you", "thanks"]):
        return jsonify({"reply": "😊 You're welcome!"})

    if any(word in user_input for word in ["help", "assist", "support"]):
        return jsonify({"reply": "🆘 Try asking: 'last alert', 'employee violations', or 'details of employee ADV001'"})
    
    
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
        # return jsonify({"reply": [
        #     "⚠️ Sorry, I couldn't determine which module to check.",
        #     "Try asking about alerts related to fire, gas, occupancy, trespass, PPE, or slips."
        # ]})
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

