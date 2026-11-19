# 📡 TopGun Competition API Documentation

Welcome to the **TopGun Competition API**. This document contains the full API specification and sample code for participants to interact with the evaluation server.

---

## 🔑 Authentication

Every request to the API must include your secret team token via the HTTP `Authorization` header:

```http
Authorization: Bearer YOUR_TEAM_TOKEN
```
*(Alternatively, you can provide the header `X-Team-Token: YOUR_TEAM_TOKEN`).*

---

## 📌 Competition Overview & Rules

1. **Two Phases / Modes:**
   - **`train` mode:** Unlimited image fetches and JSON submissions. Use this phase to benchmark your pipeline, measure latency, and test prediction formats.
   - **`test` mode:** Limited to **$N$ submissions** per team. The server will reject attempts beyond your quota with `403 Forbidden`.
2. **Fair Latency Timing:**
   - Latency timing starts **when your device finishes receiving the image**, and ends when your prediction JSON reaches the server.
   - Do not manually label images. If a submission deadline is configured, overdue submissions will be rejected.
3. **One Submission Per Image:**
   - Each `img_id` can only be submitted once. Resubmitting with the same `img_id` returns `409 Conflict`.

---

## 🛠️ API Endpoints

### 1. Fetch Image: `GET /api/v1/image`

Downloads an evaluation image.

* **Method:** `GET`
* **URL:** `/api/v1/image`
* **Query Parameters (Optional):**
  * `mode` (`train` or `test`): Optional. If omitted, the server automatically uses the active competition phase.
* **Headers:**
  ```http
  Authorization: Bearer <YOUR_TEAM_TOKEN>
  ```
* **Response:**
  * **Status:** `200 OK`
  * **Content-Type:** `image/jpeg` or `image/png` (binary image data)
  * **Key Response Headers:**
    * `X-Image-ID`: Unique tracking ID for this image (e.g. `img_8a573a058b3743cf`).
    * `X-Image-Name`: The original filename of the image (e.g. `Parchment_test.jpg`).
    * `X-Mode`: The phase the image was served in (`train` or `test`).
    * `Content-Disposition`: `inline; filename="Parchment_test.jpg"`

---

### 2. Submit Predictions: `POST /api/v1/submit`

Submits model prediction JSON for the image you downloaded. The format matches `ground_truth.json` for a single image.

* **Method:** `POST`
* **URL:** `/api/v1/submit`
* **Headers:**
  ```http
  Authorization: Bearer <YOUR_TEAM_TOKEN>
  Content-Type: application/json
  ```
* **Request Body Format (Matching Ground Truth for 1 image):**
  ```json
  {
    "img_id": "img_8a573a058b3743cf",
    "image_name": "Parchment_test.jpg",
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
  ```
  *(Note: You can also wrap objects in `"predictions": {"image_name": "...", "objects": [...]}` - both formats are accepted!)*
* **Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "message": "Submission recorded successfully",
    "img_id": "img_8a573a058b3743cf",
    "mode": "train",
    "duration_seconds": 0.452,
    "received_at": "2026-11-19T02:15:30.123456+00:00"
  }
  ```
  * `duration_seconds` is the exact round-trip latency measured by the server from the time the image delivery finished to when the JSON was received.

---

### 3. Check Team Statistics: `GET /api/v1/stats`

Query your team's request counts, submissions, and remaining test attempts.

* **Method:** `GET`
* **URL:** `/api/v1/stats`
* **Headers:**
  ```http
  Authorization: Bearer <YOUR_TEAM_TOKEN>
  ```
* **Response (`200 OK`):**
  ```json
  {
    "team_name": "AlphaSquad",
    "train_mode": {
      "images_requested": 42,
      "submissions_received": 42
    },
    "test_mode": {
      "quota_limit": 5,
      "images_requested": 2,
      "submissions_received": 2,
      "remaining_attempts": 3
    }
  }
  ```

---

## 💻 Code Examples

### Minimal Python Example (using `requests`)

```python
import requests

SERVER_URL = "https://api.yourdomain.com"
TOKEN = "YOUR_TEAM_TOKEN"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# 1. Fetch Image
img_resp = requests.get(f"{SERVER_URL}/api/v1/image", headers=HEADERS)
if img_resp.status_code != 200:
    print(f"Error fetching image: {img_resp.text}")
    exit(1)

img_id = img_resp.headers["X-Image-ID"]
image_bytes = img_resp.content

# 2. Run Inference locally
# (Pass image_bytes to your model here)
my_predictions = {
    "detected_items": [{"label": "target", "score": 0.98}]
}

# 3. Submit Results
payload = {
    "img_id": img_id,
    "predictions": my_predictions
}
sub_resp = requests.post(f"{SERVER_URL}/api/v1/submit", json=payload, headers=HEADERS)
print("Submission response:", sub_resp.json())
```

### Curl Example (Command Line)

```bash
# 1. Download image and save headers to get X-Image-ID
curl -s -D headers.txt "https://api.yourdomain.com/api/v1/image" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  --output test_image.png

# Extract Image ID:
grep -i "X-Image-ID" headers.txt

# 2. Submit Predictions
curl -X POST "https://api.yourdomain.com/api/v1/submit" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"img_id": "img_xxx", "predictions": {"sample": 123}}'

# 3. View Stats
curl -s "https://api.yourdomain.com/api/v1/stats" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## ⚠️ HTTP Status Codes Reference

| Status Code | Meaning | Description |
| :--- | :--- | :--- |
| `200 OK` | Success | Request succeeded. |
| `400 Bad Request` | Invalid `img_id` | No record of this `img_id` was dispatched to your team token. |
| `401 Unauthorized` | Invalid Token | Your team token is missing, expired, or invalid. |
| `403 Forbidden` | Quota Exceeded / Mode Locked | You have used all $N$ test attempts, or the requested mode is not currently open. |
| `408 Request Timeout` | Submission Too Late | Submission exceeded the maximum allowable time window. |
| `409 Conflict` | Duplicate Submission | A prediction has already been submitted for this `img_id`. |
| `503 Service Unavailable` | Server Paused | The competition is currently paused by administrators. |
