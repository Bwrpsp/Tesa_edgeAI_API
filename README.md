# 🎯 TopGun Benchmark & Competition Server

A high-reliability, zero-data-loss evaluation server built with **Python (FastAPI)**, designed for multi-team machine learning and computer vision competitions hosted on AWS.

---

## ⚡ Core Features

- **Socket-Accurate Finish Timestamps:** Measures latency from the exact millisecond the image transfer finishes over the network until the prediction JSON arrives.
- **Dual-Mode Operation:**
  - **`train` mode:** Unlimited image fetches and JSON submissions.
  - **`test` mode:** Strict $N$-attempt quota per team enforced at the database level.
- **Zero Data Loss Guarantee:** Submissions are written synchronously into PostgreSQL `JSONB` and backed up to AWS S3 (or local disk buffer).
- **Stat Tracking:** Real-time visibility into image requests, submissions, remaining test attempts, and average latency per team.
- **Admin Control Plane:** Local visual dashboard (**Streamlit**) and terminal CLI (**`admin_cli.py`**) to manage teams, switch competition modes, adjust quotas, and export submission files.

---

## 📂 Project Structure

```
topgun_server/
├── app/
│   ├── config.py             # Environment settings & defaults
│   ├── database.py           # Async SQLAlchemy engine (SQLite / PostgreSQL)
│   ├── models.py             # Team, ImageDispatch, Submission, SystemSetting
│   ├── security.py           # Token hashing (SHA-256) & Bearer auth
│   ├── storage.py            # Local disk & AWS S3 image/submission manager
│   ├── routes/
│   │   ├── client.py         # /image, /submit, /stats
│   │   └── admin.py          # /admin/* (mode, teams, quota, export)
│   └── main.py               # FastAPI entrypoint, CORS, lifespan
├── data/
│   ├── images/
│   │   ├── train/            # Put training images here
│   │   └── test/             # Put test evaluation images here
│   └── submissions/          # Local buffer for submitted JSONs
├── admin_dashboard.py        # Local visual dashboard (Streamlit)
├── admin_cli.py              # Local terminal admin management tool
├── run.py                    # Simple 1-click client runner for contestants
├── client_test.py            # CLI verification script for testing
├── API_DOCS.md               # Contestant API documentation
├── deploy_ec2.sh             # 1-click automated deployment script for AWS EC2
├── Dockerfile                # Production container for AWS ECS Fargate
├── docker-compose.yml        # 1-command local Postgres + API stack
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quickstart (Run Locally in 2 Minutes)

### 1. Install Dependencies
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Start the Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
*The server automatically initializes database tables and seeds sample images if the image folders are empty.*

---

## 🧪 Client Demonstration (`client_test.py`)

A ready-to-run test script is provided to verify the entire pipeline:
1. Calls `GET /api/v1/image?mode=train` with team token.
2. Extracts `X-Image-ID` from response headers and saves the image to `downloaded_samples/`.
3. Posts mock prediction JSON `{"hello": "world", ...}` with `img_id` to `POST /api/v1/submit`.
4. Calls `GET /api/v1/stats` to verify updated counts.

### Run Verification:
```bash
python client_test.py --url http://127.0.0.1:8000 --token "<YOUR_TEAM_TOKEN>" --mode train
```

**Example output:**
```
[1/4] Requesting image (mode='train')...
[+] Success! HTTP 200 OK
    - Image ID:      img_8a573a058b3743cf
    - Content-Type:  image/png
    - Saved image to: E:\Ai\topgun_server\downloaded_samples\received_img_8a573a058b3743cf.png

[2/4] Simulating local inference (0.5s pause)...

[3/4] Submitting predictions for img_id 'img_8a573a058b3743cf'...
[+] Submission Accepted!
    - Server Message:   Submission recorded successfully
    - Recorded Latency: 0.516s (from image delivery finish to submit)
    - Timestamp:        2026-11-18T07:10:30.137581+00:00

[4/4] Querying current team statistics...
[+] Stats for AlphaSquad:
    Train Mode -> Requested: 2 | Submissions: 1
    Test Mode  -> Quota: 3 | Requested: 0 | Submissions: 0 | Remaining: 3
```

---

## 🛠️ Admin Operations Guide

You can manage the competition either using the **Visual Web UI** or the **Terminal CLI**.

### Option A: Visual Dashboard (Streamlit)
Run on your local machine:
```bash
streamlit run admin_dashboard.py
```
From the dashboard you can:
- **Import Pre-Generated Keys:** Upload any CSV/TSV file or paste raw text. Intelligent column detection maps whatever headers you have (`team_id,key`, `name,token`, etc.) with a live preview before importing.
- **Edit & Adjust Teams:** Select any team to change their name, assign/overwrite a new secret key, update their test quota, or delete them.
- **Switch Competition Mode:** (`ALL`, `TRAIN ONLY`, `TEST ONLY`, `PAUSED`).
- **Batch generate 60 team keys:** Generate keys automatically and download them as CSV if you don't have existing keys.
- **Monitor live team progress:** Real-time table of requests, submissions, remaining quota, and average latency.
- **Export all submissions:** 1-click download of all JSONs in a single `.zip` file for evaluation.

---

### Option B: Terminal CLI (`admin_cli.py`)

#### 1. How to Import Pre-Generated Keys from CSV
If you already have a CSV file with teams and keys (any column names like `team_id,key`, `team_name,token,quota`, etc.):
```bash
# Auto-detects columns and imports/updates teams:
python admin_cli.py import-csv keys.csv --quota 5

# Or specify custom column header names explicitly if needed:
python admin_cli.py import-csv keys.csv --name-col "team_id" --key-col "key" --quota-col "attempts"
```
*If a team name already exists, the server updates their key and quota (Upsert).*

#### 2. How to Edit an Existing Team (Key, Name, Quota)
Admin can edit any team property at any time:
```bash
# Rename team, assign a new secret key, and update quota:
python admin_cli.py edit-team <team_id> --name "New Team Name" --token "new_secret_key_123" --quota 10

# Or deactivate a team:
python admin_cli.py edit-team <team_id> --inactive
```

#### 3. How to Add Images
Drop your competition images into the local folders:
- Training images: `data/images/train/` (JPEG, PNG, WebP)
- Real test images: `data/images/test/` (JPEG, PNG, WebP)

*(If using AWS S3, place them under `s3://<S3_IMAGE_BUCKET>/train/` and `s3://<S3_IMAGE_BUCKET>/test/`).*

#### 4. How to Add Teams & Generate Keys (If not using existing CSV)
* **Add a single team (with custom key or auto-generated):**
  ```bash
  # With pre-generated custom key:
  python admin_cli.py add-team "AlphaSquad" --token "my_custom_key_xyz" --quota 5

  # Auto-generate key:
  python admin_cli.py add-team "AlphaSquad" --quota 5
  ```
* **Batch create all 60 teams at once:**
  ```bash
  python admin_cli.py batch-add "Team 01, Team 02, Team 03, Team 04" --quota 5 --save-csv team_credentials.csv
  ```
  *This automatically generates unique, cryptographic tokens (`tg_...`) and saves them to `team_credentials.csv` ready to send to team leaders.*

#### 3. How to Change Competition Mode
```bash
# Check current mode:
python admin_cli.py get-mode

# Allow only training:
python admin_cli.py set-mode train

# Start real competition (enforce N quota):
python admin_cli.py set-mode test

# Pause competition (blocks all image requests):
python admin_cli.py set-mode paused

# Allow both modes:
python admin_cli.py set-mode all
```

#### 4. How to View Live Stats
```bash
python admin_cli.py stats
```
**Output:**
```
Team Name              Train (Req/Sub)    Test (Req/Sub)   Test Rem   Avg Dur (s)
==============================================================================
Team 01                14 / 14            5 / 5            0          0.48s
Team 02                8 / 7              3 / 3            2          0.72s
Team 03                22 / 20            0 / 0            5          -
```

#### 5. How to Adjust a Team's Quota
If a team's hardware crashed during a test run, grant them extra attempts:
```bash
python admin_cli.py set-quota <team_id> 6
```

#### 6. How to Export Submissions for Offline Evaluation
```bash
python admin_cli.py export-data --output submissions_final.zip
```
This downloads all JSON predictions organized by:
`submissions/<mode>/<team_name>/<img_id>_<timestamp>.json`

---

## ☁️ AWS Cloud Production Deployment Guide

For 60 teams, a minimal, robust AWS architecture costs **~$25–$40/month**:

```
[ Route 53 Custom Domain ]
           │
           ▼
[ AWS Application Load Balancer (ALB) + ACM HTTPS ]
           │ (Port 8000)
           ▼
[ AWS ECS Fargate Container (FastAPI) ]
      │                    │
      ▼                    ▼
[ AWS RDS PostgreSQL ]   [ AWS S3 Buckets ]
 (db.t4g.micro)           - Images
                          - Submissions backup
```

### Step 1: Create AWS RDS PostgreSQL Database
1. Go to AWS RDS $\rightarrow$ **Create Database** $\rightarrow$ **PostgreSQL**.
2. Template: **Free Tier / Dev/Test**.
3. DB instance class: **`db.t4g.micro`** (or `db.t4g.small`).
4. Set Master Username (`postgres`) and Password.
5. In Connectivity, place it in your default VPC.
6. Copy the RDS endpoint: e.g. `topgun-db.xxxxxx.us-east-1.rds.amazonaws.com`.

### Step 2: Create S3 Buckets
1. Bucket 1: `topgun-competition-images` (upload your train and test image folders here).
2. Bucket 2: `topgun-competition-submissions` (for immutable JSON submission backups).

### Step 3: Deploy FastAPI on AWS ECS Fargate
1. Build and push Docker image to **AWS ECR (Elastic Container Registry)**:
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t topgun-server .
   docker tag topgun-server:latest <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/topgun-server:latest
   docker push <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/topgun-server:latest
   ```
2. Create an **ECS Task Definition** (Fargate, 0.5 vCPU, 1 GB RAM).
3. Set Environment Variables in Task Definition:
   - `DATABASE_URL`: `postgresql+asyncpg://postgres:PASSWORD@topgun-db.xxxxxx.us-east-1.rds.amazonaws.com:5432/topgun`
   - `ADMIN_API_KEY`: A strong 32-character random string.
   - `S3_IMAGE_BUCKET`: `topgun-competition-images`
   - `S3_SUBMISSION_BUCKET`: `topgun-competition-submissions`
   - `DEFAULT_TEST_QUOTA`: `5`
   - `DEFAULT_GLOBAL_MODE`: `train`

### Step 4: Configure ALB & Custom Domain
1. In EC2 $\rightarrow$ **Load Balancers**, create an **Application Load Balancer (ALB)**.
2. Target Group: Port `8000`, Health check path: `/health`.
3. In **AWS Certificate Manager (ACM)**, request a free SSL certificate for your domain (e.g. `api.yourdomain.com`).
4. Add an HTTPS (443) listener to the ALB pointing to the ECS target group.
5. In **Route 53**, point `api.yourdomain.com` (A Record Alias) to your ALB.

### Step 5: Security Hardening (AWS WAF)
- Attach **AWS WAF** to your ALB:
  - Add rate-limiting rule (e.g., max 100 requests per 5 minutes per IP).
  - Add IP Whitelisting rule on `/api/v1/admin/*` so only your admin IP can reach the admin API.

---

## 🔒 Security Summary

1. **Tokens Hashed with SHA-256:** Raw team tokens are never stored in plaintext in the database.
2. **Timing Attack Protection:** Constant-time token comparisons (`secrets.compare_digest`).
3. **Admin Segregation:** Client tokens cannot access `/api/v1/admin/*`. Admin endpoints require `X-Admin-Key`.
4. **Duplicate Submission Locking:** Re-submitting for the same `img_id` is blocked with HTTP 409 Conflict.
5. **No Front-End Exposure:** The public domain exposes only API endpoints. Admin dashboards run privately on your local machine.
