"""
TopGun Local Admin Dashboard (Streamlit)

Run locally:
    streamlit run admin_dashboard.py
"""

import io
import pandas as pd
import streamlit as st
import httpx
from app.config import settings

st.set_page_config(page_title="TopGun Admin Dashboard", layout="wide", page_icon="🎯")

# -----------------------------------------------------------------------------
# Sidebar Configuration
# -----------------------------------------------------------------------------
st.sidebar.title("🎯 TopGun Admin")
server_url = st.sidebar.text_input("Server URL", value="http://127.0.0.1:8000")
admin_key = st.sidebar.text_input("Admin API Key", value=settings.ADMIN_API_KEY, type="password")

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.rerun()

headers = {"X-Admin-Key": admin_key}


def api_get(endpoint: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            return client.get(f"{server_url.rstrip('/')}{endpoint}", headers=headers)
    except Exception as e:
        st.error(f"Failed to connect to server: {e}")
        return None


def api_post(endpoint: str, json_data: dict):
    try:
        with httpx.Client(timeout=60.0) as client:
            return client.post(f"{server_url.rstrip('/')}{endpoint}", json=json_data, headers=headers)
    except Exception as e:
        st.error(f"API request failed: {e}")
        return None


def api_delete(endpoint: str):
    try:
        with httpx.Client(timeout=10.0) as client:
            return client.delete(f"{server_url.rstrip('/')}{endpoint}", headers=headers)
    except Exception as e:
        st.error(f"API delete failed: {e}")
        return None


# -----------------------------------------------------------------------------
# Mode Management
# -----------------------------------------------------------------------------
st.subheader("⚙️ Competition Mode Control")

mode_resp = api_get("/api/v1/admin/mode")
current_mode = "unknown"
if mode_resp and mode_resp.status_code == 200:
    current_mode = mode_resp.json().get("global_mode", "unknown")

mode_labels = {
    "all": "🟢 All Active (Train + Test)",
    "train": "🟡 Train Only",
    "test": "🔴 Test Only (N-quota enforced)",
    "paused": "⏸️ Paused (All image requests blocked)"
}

col_m_view, col_m_switch = st.columns([1, 2])
with col_m_view:
    st.metric(label="Active Mode", value=current_mode.upper())

with col_m_switch:
    mode_options = ["all", "train", "test", "paused"]
    new_mode = st.selectbox(
        "Switch Mode",
        options=mode_options,
        format_func=lambda m: mode_labels.get(m, m),
        index=mode_options.index(current_mode) if current_mode in mode_options else 0
    )
    if st.button("Apply Mode Change"):
        resp = api_post("/api/v1/admin/mode", {"mode": new_mode})
        if resp and resp.status_code == 200:
            st.success(f"Mode changed to {new_mode.upper()}!")
            st.rerun()

st.divider()

# -----------------------------------------------------------------------------
# Live Statistics & Monitoring
# -----------------------------------------------------------------------------
st.subheader("📊 Live Team Activity & Quotas")

stats_resp = api_get("/api/v1/admin/stats")
teams_data = []
if stats_resp and stats_resp.status_code == 200:
    teams_data = stats_resp.json()
    if teams_data:
        df = pd.DataFrame(teams_data)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Registered Teams", len(df))
        m2.metric("Total Train Submissions", int(df["train_submissions"].sum()))
        m3.metric("Total Test Submissions", int(df["test_submissions"].sum()))
        active_count = int(df["is_active"].sum())
        m4.metric("Active Teams", f"{active_count} / {len(df)}")

        display_df = df[[
            "team_name", "token_prefix", "is_active", "train_dispatches", "train_submissions",
            "test_quota_limit", "test_dispatches", "test_submissions", "test_remaining", "avg_duration_sec"
        ]].copy()

        display_df.columns = [
            "Team Name", "Token Prefix", "Active", "Train (Req)", "Train (Sub)",
            "Quota", "Test (Req)", "Test (Sub)", "Remaining", "Avg Latency (s)"
        ]

        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("No teams registered yet. Use the tabs below to add or import teams.")
else:
    st.warning("Could not fetch team statistics. Verify server URL and admin API key.")

st.divider()

# -----------------------------------------------------------------------------
# Team Management Tabs
# -----------------------------------------------------------------------------
tab_import, tab_edit, tab_add, tab_export = st.tabs([
    "📥 Import Keys (CSV / Text)",
    "✏️ Edit & Adjust Teams",
    "➕ Add Single Team",
    "💾 Export Submissions"
])

# -----------------------------------------------------------------------------
# TAB 1: Flexible CSV / Pre-generated Key Import
# -----------------------------------------------------------------------------
with tab_import:
    st.write("#### Import Pre-Generated Team Keys")
    st.markdown("""
    Upload a CSV file or paste raw text containing team names and their pre-generated keys.
    *Any column headers work* (e.g., `team_id,key`, `team_name,token`, `name,secret,quota`, etc.).
    """)

    col_up1, col_up2 = st.columns([1, 1])
    with col_up1:
        uploaded_file = st.file_uploader("Upload CSV / TSV file", type=["csv", "tsv", "txt"])
    with col_up2:
        pasted_text = st.text_area("Or paste raw text (CSV / TSV):", placeholder="team_id,key,quota\nAlpha,key_abc123,5\nBeta,key_xyz987,5")

    default_quota_input = st.number_input("Default Quota if not in file", min_value=0, value=5, step=1)

    # Determine data source
    raw_csv_content = None
    if uploaded_file is not None:
        raw_csv_content = uploaded_file.getvalue().decode("utf-8-sig", errors="replace")
    elif pasted_text.strip():
        raw_csv_content = pasted_text.strip()

    if raw_csv_content:
        parsed_df = None
        try:
            # Flexible reading with delimiter detection
            parsed_df = pd.read_csv(io.StringIO(raw_csv_content), sep=None, engine="python")
            # Strip whitespace from column names so ' Password' becomes 'Password'
            parsed_df.columns = [str(c).strip() for c in parsed_df.columns]
        except Exception as e:
            st.error(f"Error parsing CSV content: {e}")

        if parsed_df is not None and not parsed_df.empty:
            cols = list(parsed_df.columns)
            st.write("**Parsed Columns Found:**", cols)

            # Auto-detection of columns with expanded keywords
            name_candidates = [c for c in cols if any(k in str(c).lower() for k in ["name", "team", "id", "teamid", "user"])]
            key_candidates = [c for c in cols if any(k in str(c).lower() for k in ["key", "token", "sec", "pass", "pwd", "password"])]
            quota_candidates = [c for c in cols if any(k in str(c).lower() for k in ["quota", "limit"])]

            col_map1, col_map2, col_map3 = st.columns(3)
            with col_map1:
                col_name = st.selectbox("Team Name/ID Column", options=cols, index=cols.index(name_candidates[0]) if name_candidates else 0)
            with col_map2:
                key_options = ["(None / Auto-Generate)"] + cols
                default_key_idx = cols.index(key_candidates[0]) + 1 if key_candidates else 0
                col_key = st.selectbox("Secret Key/Token Column", options=key_options, index=default_key_idx)
            with col_map3:
                quota_options = ["(Use Default)"] + cols
                default_q_idx = cols.index(quota_candidates[0]) + 1 if quota_candidates else 0
                col_quota = st.selectbox("Quota Column", options=quota_options, index=default_q_idx)

            # Build preview records
            import_records = []
            for _, row in parsed_df.iterrows():
                t_name = str(row[col_name]).strip()
                if not t_name or t_name.lower() == "nan":
                    continue
                t_key = None
                if col_key != "(None / Auto-Generate)":
                    raw_k = str(row[col_key]).strip()
                    if raw_k and raw_k.lower() != "nan":
                        t_key = raw_k

                t_q = None
                if col_quota != "(Use Default)":
                    try:
                        t_q = int(row[col_quota])
                    except Exception:
                        t_q = default_quota_input

                import_records.append({"name": t_name, "token": t_key, "test_quota_limit": t_q})

            st.write(f"**Preview of {len(import_records)} Teams Ready to Import:**")
            st.dataframe(pd.DataFrame(import_records), use_container_width=True)

            if st.button("🚀 Import / Update All Teams in Database", type="primary"):
                with st.spinner("Importing teams into database..."):
                    import_res = api_post("/api/v1/admin/teams/import", {
                        "teams": import_records,
                        "default_quota": default_quota_input
                    })
                    if import_res is not None:
                        if import_res.status_code == 200:
                            try:
                                res_data = import_res.json()
                                total_processed = res_data.get("total", len(import_records))
                            except Exception:
                                total_processed = len(import_records)
                            st.success(f"✅ Successfully processed {total_processed} teams!")
                            st.rerun()
                        else:
                            try:
                                err_msg = import_res.json().get("detail", import_res.text)
                            except Exception:
                                err_msg = import_res.text or f"HTTP {import_res.status_code}"
                            st.error(f"❌ Server Error (HTTP {import_res.status_code}): {err_msg}")
                    else:
                        st.error(f"❌ Could not communicate with server at {server_url}. Please ensure the server is running and the Server URL in the sidebar is correct.")

# -----------------------------------------------------------------------------
# TAB 2: Edit & Adjust Teams (Rename, Set Key, Change Quota, Delete)
# -----------------------------------------------------------------------------
with tab_edit:
    st.write("#### Edit Any Team Property")
    teams_resp = api_get("/api/v1/admin/teams")
    if teams_resp and teams_resp.status_code == 200:
        all_teams = teams_resp.json()
        if all_teams:
            team_map = {f"{t['name']}  (Key: {t['token_prefix']}, Quota: {t['test_quota_limit']})": t for t in all_teams}
            selected_team_label = st.selectbox("Choose a Team to Edit", options=list(team_map.keys()))
            team_obj = team_map[selected_team_label]

            st.markdown(f"**Team ID:** `{team_obj['id']}`")

            col_e1, col_e2 = st.columns(2)
            with col_e1:
                edit_name = st.text_input("Team Name", value=team_obj["name"])
                edit_quota = st.number_input("Test Quota Limit", min_value=0, value=int(team_obj["test_quota_limit"]), step=1)
            with col_e2:
                edit_token = st.text_input("Assign New Secret Key / Token (leave blank to keep current)", value="", type="password")
                edit_active = st.checkbox("Team is Active", value=bool(team_obj["is_active"]))

            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                if st.button("💾 Save Changes", type="primary"):
                    update_payload = {
                        "name": edit_name.strip(),
                        "test_quota_limit": edit_quota,
                        "is_active": edit_active
                    }
                    if edit_token.strip():
                        update_payload["custom_token"] = edit_token.strip()

                    up_res = api_post(f"/api/v1/admin/teams/{team_obj['id']}/edit", update_payload)
                    if up_res and up_res.status_code == 200:
                        st.success("Team updated successfully!")
                        st.rerun()
                    elif up_res:
                        st.error(f"Update failed: {up_res.json().get('detail', up_res.text)}")

            with col_btn2:
                if st.button("🗑️ Delete Team", type="secondary"):
                    del_res = api_delete(f"/api/v1/admin/teams/{team_obj['id']}")
                    if del_res and del_res.status_code == 200:
                        st.warning(f"Team '{team_obj['name']}' deleted.")
                        st.rerun()
                    elif del_res:
                        st.error(f"Delete failed: {del_res.text}")
        else:
            st.info("No teams available to edit.")

# -----------------------------------------------------------------------------
# TAB 3: Add Single Team
# -----------------------------------------------------------------------------
with tab_add:
    st.write("#### Add a Single Team")
    with st.form("single_team_form"):
        single_name = st.text_input("Team Name (e.g. 'Team Omega')")
        single_quota = st.number_input("Test Quota Limit", min_value=0, value=5, step=1)
        single_custom_key = st.text_input("Pre-generated Key / Token (Optional - leave blank to auto-generate)")
        create_btn = st.form_submit_button("Create Team")

        if create_btn and single_name:
            create_payload = {"name": single_name.strip(), "test_quota_limit": single_quota}
            if single_custom_key.strip():
                create_payload["custom_token"] = single_custom_key.strip()

            c_res = api_post("/api/v1/admin/teams", create_payload)
            if c_res and c_res.status_code == 200:
                data = c_res.json()
                st.success(f"Team '{data['name']}' created!")
                st.code(f"SECRET TOKEN: {data['token']}", language="bash")
                st.info("⚠️ Make sure to save or send this token to the team.")
            elif c_res:
                st.error(f"Error: {c_res.json().get('detail', c_res.text)}")

# -----------------------------------------------------------------------------
# TAB 4: Export Submissions & CSV Logs
# -----------------------------------------------------------------------------
with tab_export:
    st.write("#### 📦 Export Submissions & Evaluation Manifests")
    st.markdown("""
    Export complete submission logs with timestamps, file paths, image names, and final submission flags.
    The exported ZIP automatically contains both **`train_manifest.csv`** and **`test_manifest.csv`** at the root!
    """)

    col_exp_zip, col_exp_csv = st.columns([1, 1])

    with col_exp_zip:
        st.write("##### 1. Complete Package (.ZIP)")
        st.write("Contains all JSON prediction files + both `train_manifest.csv` and `test_manifest.csv`.")
        if st.button("📦 Prepare & Download Full ZIP"):
            with httpx.Client(timeout=120.0) as client:
                exp_res = client.get(f"{server_url.rstrip('/')}/api/v1/admin/export", headers=headers)
                if exp_res.status_code == 200:
                    st.download_button(
                        label="⬇️ Click here to save submissions .zip",
                        data=exp_res.content,
                        file_name="topgun_submissions_export.zip",
                        mime="application/x-zip-compressed"
                    )
                else:
                    st.error("Failed to generate zip export.")

    with col_exp_csv:
        st.write("##### 2. Quick CSV Manifests")
        st.write("Download standalone CSV logs without packaging all JSON files.")
        c_mode = st.radio("Select Mode Log", options=["test", "train"], horizontal=True)
        if st.button(f"📄 Fetch {c_mode.upper()} CSV"):
            with httpx.Client(timeout=30.0) as client:
                csv_res = client.get(f"{server_url.rstrip('/')}/api/v1/admin/export/csv?mode={c_mode}", headers=headers)
                if csv_res.status_code == 200:
                    csv_text = csv_res.text
                    st.session_state[f"csv_data_{c_mode}"] = csv_text
                else:
                    st.error("Failed to fetch CSV.")

        if f"csv_data_{c_mode}" in st.session_state:
            csv_str = st.session_state[f"csv_data_{c_mode}"]
            try:
                csv_df = pd.read_csv(io.StringIO(csv_str))
                st.write(f"**Preview of {c_mode.upper()} Submissions ({len(csv_df)} rows):**")
                st.dataframe(csv_df, use_container_width=True)
                st.download_button(
                    label=f"⬇️ Download {c_mode.upper()} Manifest CSV",
                    data=csv_str.encode("utf-8"),
                    file_name=f"{c_mode}_manifest.csv",
                    mime="text/csv"
                )
            except Exception as e:
                st.warning(f"No records found or error parsing: {e}")
