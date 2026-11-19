"""
TopGun Client Demonstration & Verification Script

This script simulates a team agent:
1. Calls GET /api/v1/image with team token.
2. Reads the 'X-Image-ID' header and saves the downloaded image.
3. Submits mock prediction JSON back to POST /api/v1/submit with the img_id.
4. Calls GET /api/v1/stats to show updated team statistics.

Usage:
    python client_test.py --token <YOUR_TEAM_TOKEN> --url http://127.0.0.1:8000 --mode train
"""

import argparse
import json
import time
from pathlib import Path
import httpx


def run_test(server_url: str, token: str, mode: str):
    server_url = server_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}

    print("=" * 60)
    print(f"TopGun Client Test - Mode: {mode.upper()}")
    print(f"Server: {server_url}")
    print(f"Token:  {token[:8]}...{token[-4:]}")
    print("=" * 60)

    with httpx.Client(timeout=30.0) as client:
        # -----------------------------------------------------------
        # Step 1: Request Image
        # -----------------------------------------------------------
        print(f"\n[1/4] Requesting image (mode='{mode}')...")
        start_req = time.time()
        
        img_resp = client.get(f"{server_url}/api/v1/image", params={"mode": mode}, headers=headers)
        elapsed_download = time.time() - start_req

        if img_resp.status_code != 200:
            print(f"[-] Error fetching image: HTTP {img_resp.status_code}")
            try:
                print(f"[-] Detail: {img_resp.json()}")
            except Exception:
                print(f"[-] Raw: {img_resp.text}")
            return

        img_id = img_resp.headers.get("X-Image-ID")
        content_type = img_resp.headers.get("Content-Type", "image/png")
        ext = ".png" if "png" in content_type else ".jpg"

        print(f"[+] Success! HTTP 200 OK")
        print(f"    - Image ID:      {img_id}")
        print(f"    - Content-Type:  {content_type}")
        print(f"    - Download Size: {len(img_resp.content):,} bytes")
        print(f"    - Transfer Time: {elapsed_download:.3f}s")

        # Save received image locally to verify it is intact
        output_dir = Path("downloaded_samples")
        output_dir.mkdir(exist_ok=True)
        saved_file = output_dir / f"received_{img_id}{ext}"
        saved_file.write_bytes(img_resp.content)
        print(f"    - Saved image to: {saved_file.resolve()}")

        # -----------------------------------------------------------
        # Step 2: Simulate Model Inference / Processing
        # -----------------------------------------------------------
        print("\n[2/4] Simulating local inference (0.5s pause)...")
        time.sleep(0.5)

        # -----------------------------------------------------------
        # Step 3: Submit Prediction JSON
        # -----------------------------------------------------------
        mock_predictions = {
            "hello": "world",
            "model_version": "v1.0-benchmark",
            "detected_objects": [
                {"label": "object_A", "confidence": 0.96, "bbox": [12, 45, 100, 220]},
                {"label": "object_B", "confidence": 0.88, "bbox": [150, 80, 230, 190]}
            ],
            "client_timestamp": time.time()
        }

        submit_payload = {
            "img_id": img_id,
            "predictions": mock_predictions
        }

        print(f"\n[3/4] Submitting predictions for img_id '{img_id}'...")
        sub_resp = client.post(
            f"{server_url}/api/v1/submit",
            json=submit_payload,
            headers=headers
        )

        if sub_resp.status_code != 200:
            print(f"[-] Submission failed: HTTP {sub_resp.status_code}")
            try:
                print(f"[-] Detail: {sub_resp.json()}")
            except Exception:
                print(f"[-] Raw: {sub_resp.text}")
            return

        sub_data = sub_resp.json()
        print(f"[+] Submission Accepted!")
        print(f"    - Server Message:   {sub_data.get('message')}")
        print(f"    - Recorded Latency: {sub_data.get('duration_seconds')}s (from image delivery finish to submit)")
        print(f"    - Timestamp:        {sub_data.get('received_at')}")

        # -----------------------------------------------------------
        # Step 4: Check Team Stats
        # -----------------------------------------------------------
        print("\n[4/4] Querying current team statistics...")
        stats_resp = client.get(f"{server_url}/api/v1/stats", headers=headers)
        if stats_resp.status_code == 200:
            stats = stats_resp.json()
            print(f"[+] Stats for {stats.get('team_name')}:")
            print(f"    Train Mode -> Requested: {stats['train_mode']['images_requested']} | Submissions: {stats['train_mode']['submissions_received']}")
            print(f"    Test Mode  -> Quota: {stats['test_mode']['quota_limit']} | Requested: {stats['test_mode']['images_requested']} | Submissions: {stats['test_mode']['submissions_received']} | Remaining: {stats['test_mode']['remaining_attempts']}")
        else:
            print(f"[-] Could not load stats: HTTP {stats_resp.status_code}")

    print("\n" + "=" * 60)
    print("Verification complete! System is working as expected.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TopGun Client Verification")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of TopGun server")
    parser.add_argument("--token", required=True, help="Team secret token (tg_...)")
    parser.add_argument("--mode", choices=["train", "test"], default="train", help="Mode: train or test")
    args = parser.parse_args()

    run_test(server_url=args.url, token=args.token, mode=args.mode)
