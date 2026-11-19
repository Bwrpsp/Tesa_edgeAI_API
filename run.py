"""
TopGun Competition Client Runner
=============================================================
Instructions for Contestants:
1. Put your team token in TEAM_TOKEN below (or pass it via CLI: python run.py my_token).
2. Put your model inference logic in the `run_inference(image_bytes)` function.
3. Run the script:
       python run.py
=============================================================
"""

import json
import os
import sys
import time
from pathlib import Path

# ==============================================================================
# CONFIGURATION - EMBEDDED SETTINGS
# ==============================================================================
SERVER_URL = os.environ.get("SERVER_URL", "https://your-domain.com")  # Replace with your Cloudflare domain
TEAM_TOKEN = os.environ.get("TEAM_TOKEN", "PASTE_YOUR_TEAM_TOKEN_HERE") # Put your team token here
SAVE_DOWNLOADED_IMAGE = True             # Set to True to save downloaded images
# ==============================================================================

# Allow passing token via CLI argument: python run.py <token>
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    TEAM_TOKEN = sys.argv[1]

# Support both 'requests' and standard library 'urllib'
try:
    import requests
    USE_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    USE_REQUESTS = False


def run_inference(image_bytes: bytes, img_name: str) -> dict:
    """
    >>> YOUR MODEL INFERENCE LOGIC GOES HERE <<<
    
    Accepts raw image bytes and the image file name, runs your CV/ML model,
    and returns a prediction dict matching ground_truth format for 1 image:
    {
        "image_name": "Parchment_test.jpg",
        "objects": [
            {
                "id": 1,
                "class": "parchment",
                "polygon": [[x1, y1], [x2, y2], ...]
            }
        ]
    }
    """
    # Simulate processing time (e.g. 0.2s inference)
    time.sleep(0.2)

    return {
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


def main():
    server_base = SERVER_URL.rstrip("/")

    if not TEAM_TOKEN or TEAM_TOKEN == "PASTE_YOUR_TEAM_TOKEN_HERE":
        print("[!] ERROR: Please set your TEAM_TOKEN in run.py (line 19) or run: python run.py <your_token>")
        sys.exit(1)

    print("=" * 60)
    print(f"TopGun Competition Client")
    print(f"Server: {server_base}")
    print(f"Token:  {TEAM_TOKEN[:6]}...{TEAM_TOKEN[-4:] if len(TEAM_TOKEN) > 10 else ''}")
    print("=" * 60)

    # --------------------------------------------------------------------------
    # STEP 1: Fetch Image
    # --------------------------------------------------------------------------
    print("\n[1/3] Fetching image from server...")
    image_url = f"{server_base}/api/v1/image"
    headers = {"Authorization": f"Bearer {TEAM_TOKEN}"}

    img_id = None
    image_bytes = None
    content_type = "image/png"
    detected_mode = "unknown"

    start_dl = time.time()
    if USE_REQUESTS:
        try:
            resp = requests.get(image_url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"[-] Connection Error: {e}")
            sys.exit(1)

        if resp.status_code != 200:
            print(f"[-] Failed to fetch image (HTTP {resp.status_code})")
            print(f"[-] Response: {resp.text}")
            sys.exit(1)

        image_bytes = resp.content
        img_id = resp.headers.get("X-Image-ID")
        img_name = resp.headers.get("X-Image-Name", "image.png")
        detected_mode = resp.headers.get("X-Mode", "unknown")
        content_type = resp.headers.get("Content-Type", "image/png")
    else:
        req = urllib.request.Request(image_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                image_bytes = resp.read()
                img_id = resp.headers.get("X-Image-ID")
                img_name = resp.headers.get("X-Image-Name", "image.png")
                detected_mode = resp.headers.get("X-Mode", "unknown")
                content_type = resp.headers.get("Content-Type", "image/png")
        except urllib.error.HTTPError as e:
            print(f"[-] Failed to fetch image (HTTP {e.code}): {e.read().decode('utf-8')}")
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"[-] Connection Error: {e}")
            sys.exit(1)

    dl_duration = time.time() - start_dl
    print(f"[+] Image Received successfully!")
    print(f"    - Image ID:       {img_id}")
    print(f"    - Image Name:     {img_name}")
    print(f"    - Mode:           {detected_mode.upper()}")
    print(f"    - Size:           {len(image_bytes):,} bytes")
    print(f"    - Download Time:  {dl_duration:.3f}s")

    if SAVE_DOWNLOADED_IMAGE:
        out_folder = Path("downloaded_images")
        out_folder.mkdir(exist_ok=True)
        save_file = out_folder / img_name
        save_file.write_bytes(image_bytes)
        print(f"    - Saved locally:  {save_file}")

    # --------------------------------------------------------------------------
    # STEP 2: Run Inference
    # --------------------------------------------------------------------------
    print(f"\n[2/3] Running model inference on '{img_name}'...")
    predictions = run_inference(image_bytes, img_name)
    print(f"[+] Inference complete ({len(predictions.get('objects', []))} objects detected).")

    # --------------------------------------------------------------------------
    # STEP 3: Submit Predictions
    # --------------------------------------------------------------------------
    print(f"\n[3/3] Submitting prediction JSON for '{img_name}' (img_id: {img_id})...")
    submit_url = f"{server_base}/api/v1/submit"
    submit_body = {
        "img_id": img_id,
        "image_name": img_name,
        "objects": predictions.get("objects", [])
    }

    if USE_REQUESTS:
        try:
            sub_resp = requests.post(submit_url, json=submit_body, headers=headers, timeout=30)
            status_code = sub_resp.status_code
            result = sub_resp.json() if status_code == 200 else sub_resp.text
        except requests.exceptions.RequestException as e:
            print(f"[-] Submission Error: {e}")
            sys.exit(1)
    else:
        req_data = json.dumps(submit_body).encode("utf-8")
        sub_headers = {**headers, "Content-Type": "application/json"}
        req = urllib.request.Request(submit_url, data=req_data, headers=sub_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_code = resp.status
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status_code = e.code
            result = e.read().decode("utf-8")
        except urllib.error.URLError as e:
            print(f"[-] Submission Error: {e}")
            sys.exit(1)

    if status_code != 200:
        print(f"[-] Submission rejected (HTTP {status_code}): {result}")
        sys.exit(1)

    print(f"[+] SUBMISSION ACCEPTED!")
    print(f"    - Server Latency: {result.get('duration_seconds')}s (transfer finish -> submit)")
    print(f"    - Received At:    {result.get('received_at')}")

    # Optional: fetch stats
    stats_url = f"{server_base}/api/v1/stats"
    try:
        if USE_REQUESTS:
            st_resp = requests.get(stats_url, headers=headers, timeout=10)
            if st_resp.status_code == 200:
                stats = st_resp.json()
        else:
            with urllib.request.urlopen(urllib.request.Request(stats_url, headers=headers), timeout=10) as r:
                stats = json.loads(r.read().decode("utf-8"))

        print("\n" + "-" * 60)
        print(f"Team Stats for '{stats['team_name']}':")
        print(f"  • Train Mode: Requested {stats['train_mode']['images_requested']} | Submitted {stats['train_mode']['submissions_received']}")
        print(f"  • Test Mode:  Quota {stats['test_mode']['quota_limit']} | Submitted {stats['test_mode']['submissions_received']} | Remaining Attempts: {stats['test_mode']['remaining_attempts']}")
        print("-" * 60)
    except Exception:
        pass

    print("\n[+] Done!")


if __name__ == "__main__":
    main()
