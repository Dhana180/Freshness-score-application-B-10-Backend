from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
import secrets
import joblib
import pandas as pd
import razorpay
from dotenv import load_dotenv

# Load env
load_dotenv()

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

app = Flask(__name__)

# ✅ SECRET KEY
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret")

# ✅ SESSION FIX (IMPORTANT FOR PRODUCTION)
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True
)

# ✅ CORS FIX (ALLOW DEPLOYED FRONTEND)
CORS(app, supports_credentials=True)

# ── Razorpay ──
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ── Firebase Init ──
def initialize_firebase():
    try:
        firebase_cred_dict = {
            "type": os.getenv("FIREBASE_TYPE"),
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": (os.getenv("FIREBASE_PRIVATE_KEY") or "").replace('\\n', '\n'),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
            "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
        }

        cred = credentials.Certificate(firebase_cred_dict)
        firebase_admin.initialize_app(cred)
        return True
    except Exception as e:
        print(f"Firebase Error: {e}")
        return False

if os.getenv("FIREBASE_PROJECT_ID"):
    if initialize_firebase():
        db = firestore.client()
        USE_FIREBASE = True
        print("✓ Firebase connected")
    else:
        USE_FIREBASE = False
else:
    USE_FIREBASE = False

# ── In-memory fallback ──
USERS_MEMORY = {}

# ── Load Models ──
try:
    freshness_model = joblib.load("freshness_model.pkl")
    discount_model = joblib.load("discount_model.pkl")
    print("✓ Models loaded")
except:
    freshness_model = None
    discount_model = None

# ── Helper Functions ──
def get_user(email):
    if USE_FIREBASE:
        doc = db.collection("users").document(email).get()
        return doc.to_dict() if doc.exists else None
    return USERS_MEMORY.get(email)

def save_user(email, data):
    if USE_FIREBASE:
        db.collection("users").document(email).set(data)
    else:
        USERS_MEMORY[email] = data

# ── AUTH ──
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data["email"]

    if get_user(email):
        return jsonify({"error": "User exists"}), 400

    user = {
        "email": email,
        "password": data["password"],
        "trial_used": 0,
        "is_pro": False
    }

    save_user(email, user)
    session["email"] = email
    return jsonify({"message": "Signup successful"}), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    user = get_user(data["email"])

    if not user or user["password"] != data["password"]:
        return jsonify({"error": "Invalid credentials"}), 401

    session["email"] = user["email"]
    return jsonify({"message": "Login successful"})

# ── FRESHNESS ──
@app.route("/api/predict/freshness", methods=["POST"])
def predict_freshness():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    days = int(data.get("days", 5))

    if freshness_model:
        score = float(freshness_model.predict(pd.DataFrame([data]))[0])
    else:
        score = max(0, 100 - days * 5)

    return jsonify({"score": round(score, 2)})

# ── DISCOUNT ──
@app.route("/api/predict/discount", methods=["POST"])
def predict_discount():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()

    if discount_model:
        discount = float(discount_model.predict(pd.DataFrame([data]))[0])
    else:
        discount = 10.0

    return jsonify({"discount": round(discount, 2)})

# ── PAYMENT ──
@app.route("/api/payment", methods=["POST"])
def payment():
    try:
        order = razorpay_client.order.create({
            "amount": 50000,
            "currency": "INR",
            "payment_capture": 1
        })
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return {
        "message": "Freshness API is running 🚀",
        "status": "success"
    }

# ── RUN ──
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
