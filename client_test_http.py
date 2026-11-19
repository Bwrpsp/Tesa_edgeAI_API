"""
TopGun Competition - Minimal HTTP Client Guide
================================================================================
HTTP Bearer Token = Password ที่ทีมใช้ล็อกอินเข้าสู่ระบบเว็บไซต์
================================================================================
"""

import requests

SERVER_URL = "http://127.0.0.1:8000"         # เปลี่ยนเป็น Domain Server เช่น https://api.yourdomain.com
TOKEN = "YOUR_TEAM_PASSWORD"                 # Password ที่ใช้ล็อกอินเว็บไซต์ของทีม
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# 1. Fetch Image
print("[1] Fetching image...")
img_resp = requests.get(f"{SERVER_URL}/api/v1/image", headers=HEADERS)
if img_resp.status_code != 200:
    print(f"Error fetching image: {img_resp.text}")
    exit(1)

# ดึงรหัสภาพ และชื่อไฟล์ภาพจาก Response Headers
img_id = img_resp.headers["X-Image-ID"]
img_name = img_resp.headers.get("X-Image-Name", "image.jpg")
image_bytes = img_resp.content

print(f"[+] Received image: {img_name} (ID: {img_id})")

# 2. Run Inference locally
# (นำ image_bytes เข้าสู่โมเดลตรวจจับเมล็ดกาแฟและหาพิกัด Polygon)
my_predictions = {
    "image_name": img_name,
    "objects": [
        {
            "id": 1,
            "class": "parchment",
            "polygon": [
                [767, 1335],
                [766, 1336],
                [765, 1336],
                [764, 1336]
            ]
        }
    ]
}

# 3. Submit Results
print("[2] Submitting predictions...")
payload = {
    "img_id": img_id,
    "predictions": my_predictions
}
sub_resp = requests.post(f"{SERVER_URL}/api/v1/submit", json=payload, headers=HEADERS)
print("Submission response:", sub_resp.json())
