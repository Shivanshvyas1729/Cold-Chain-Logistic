import os
import sys
import uuid
import json
import urllib
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from langchain_core.messages import HumanMessage, ToolMessage

# ==========================================
# 1. IMMEDIATE PATH & ENVIRONMENT RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent  # points to src/
project_root = script_dir.parent              # climbs to project root

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

load_dotenv(project_root / ".env")

# Import the compiled graph and tools list dynamically
from src.orchestrator import fde_agent
from src import sop_service

# ==========================================
# 2. SQL CREDENTIALS MAPPING FROM .ENV
# ==========================================
db_host = os.getenv("SQL_SERVER_HOST", "localhost")
db_port = os.getenv("SQL_SERVER_PORT", "1433")
db_user = os.getenv("SQL_AGENT_USER", "USR_FDE_RO")
db_password = os.getenv("SQL_AGENT_PASSWORD")
db_name = os.getenv("DB_NAME", "LogisticsDB")

def get_mssql_engine(user: str, password: str, target_db: str = None):
    """Dynamically connects to MSSQL using the best available driver and target database."""
    active_db = target_db or db_name
    try:
        import pyodbc
        available = pyodbc.drivers()
        preferred = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
        selected_driver = next((d for d in preferred if d in available), None)
        if selected_driver:
            extra = "Encrypt=no;TrustServerCertificate=yes;" if "18" in selected_driver else "TrustServerCertificate=yes;"
            conn_str = (
                f"DRIVER={{{selected_driver}}};"
                f"SERVER={db_host},{db_port};"
                f"DATABASE={active_db};"
                f"UID={user};"
                f"PWD={password};"
                f"{extra}"
            )
            params = urllib.parse.quote_plus(conn_str)
            return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
    except Exception:
        pass

    # Seamless fallback for pymssql
    encoded_pwd = urllib.parse.quote_plus(password) if password else ""
    return create_engine(f"mssql+pymssql://{user}:{encoded_pwd}@{db_host}:{db_port}/{active_db}")

log_engine = get_mssql_engine(db_user, db_password)

def write_audit_log(session_id, node_name, tool_name, content):
    """Silently writes agent execution traces to the SQL audit table using agent permissions."""
    try:
        with log_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO FDE_VIEWS.AgentAuditLog (SessionID, NodeExecuted, ToolName, Content)
                VALUES (:session_id, :node_name, :tool_name, :content)
            """), {
                "session_id": session_id,
                "node_name": node_name,
                "tool_name": tool_name,
                "content": content
            })
            conn.commit()
    except Exception as e:
        print(f"Audit Log Failed (Silent): {e}")

# ==========================================
# 3. PAGE CONFIGURATION & ENTERPRISE THEME
# ==========================================
st.set_page_config(
    page_title="FDE Supply Chain Dispatch Console",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #0B0E14; color: #E2E8F0; }
    div[data-testid="stSidebar"] { background-color: #111622; border-right: 1px solid #1E293B; }
    .stMarkdown code { background-color: #1E293B !important; color: #38BDF8 !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. MULTI-USER STATE & THREAD MANAGEMENT
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = []

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if "admin_user" not in st.session_state:
    st.session_state.admin_user = ""

if "admin_pass" not in st.session_state:
    st.session_state.admin_pass = ""

thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}

# ==========================================
# 5. SIDEBAR NAVIGATION & METADATA
# ==========================================
with st.sidebar:
    st.image(str(script_dir / "image_L25X5q.png") if (script_dir / "image_L25X5q.png").exists() else "https://cdn-icons-png.flaticon.com/512/2830/2830305.png", width=65)
    st.title("FDE Command Center")
    
    app_mode = st.radio("System Mode", ["🧊 Dispatch Console", "🛡️ Admin Operations"])
    
    st.markdown("---")
    st.caption(f"Session Token: `{st.session_state.thread_id[:8]}...`")
    st.markdown(f"**Reasoning Architecture:** `{os.getenv('Agent_llm', 'DEEPSEEK')}`")
    
    st.markdown("---")
    if st.button("🗑️ Purge Dispatch Workspace Session", use_container_width=True):
        st.session_state.ui_messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

# ==========================================
# 6. VIEW ROUTING (DISPATCH VS AUDIT)
# ==========================================

if app_mode == "🧊 Dispatch Console":
    # ------------------------------------------
    # TAB 1: CHAT UI & AGENT EXECUTION
    # ------------------------------------------
    st.title("Cold-Chain Incident Control Dashboard")
    st.caption("Production Data Engineering Pipeline • Real-Time Decision Optimization Platform")

    for entry in st.session_state.ui_messages:
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else "🤖"):
            if "traces" in entry:
                for trace in entry["traces"]:
                    if trace["type"] == "tool_input":
                        st.markdown(f"**⚡ Intent Recognized:** `{trace['name']}`")
                        with st.expander(f"📥 View Generated Input ({trace['name']})", expanded=False):
                            st.json(trace["args"])
                    elif trace["type"] == "tool_output":
                        with st.expander(f"📤 View Raw Output ({trace['name']})", expanded=False):
                            st.code(trace["content"], language="text")
            st.markdown(entry["content"])

    if user_input := st.chat_input("Query fleet telemetry, corridor updates, or compliance thresholds..."):
        
        st.session_state.ui_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            final_response = ""
            current_traces = [] 
            
            with st.status("🧠 Initializing Core Reasoner Node...", expanded=True) as status:
                events = fde_agent.stream(
                    {"messages": [HumanMessage(content=user_input)]}, 
                    config=thread_config,
                    stream_mode="updates"
                )
                
                for event in events:
                    for node_name, node_state in event.items():
                        
                        if node_name == "reasoner":
                            latest_msg = node_state["messages"][-1]
                            
                            # A. Intercept Tool Call Requests (Inputs)
                            if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                                status.update(label="🧠 Agent generated tool parameters...")
                                for tool_call in latest_msg.tool_calls:
                                    st.markdown(f"**⚡ Intent Recognized:** `{tool_call['name']}`")
                                    with st.expander(f"📥 View Generated Input ({tool_call['name']})", expanded=False):
                                        st.json(tool_call['args'])
                                    
                                    current_traces.append({
                                        "type": "tool_input",
                                        "name": tool_call['name'],
                                        "args": tool_call['args']
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="reasoner",
                                        tool_name=tool_call['name'],
                                        content=json.dumps(tool_call['args'])
                                    )
                            
                            # B. Intercept Final Generation
                            if latest_msg.content:
                                final_response = latest_msg.content
                                status.update(label="📝 Generating Operational Resolution Report...")
                                
                                write_audit_log(
                                    session_id=st.session_state.thread_id,
                                    node_name="reasoner_final",
                                    tool_name="LLM Text Synthesis",
                                    content=final_response
                                )
                                
                        elif node_name == "tools":
                            status.update(label="🔧 Executing Enterprise Subsystem Tools...")
                            for msg in node_state.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    with st.expander(f"📤 View Raw Output ({msg.name})", expanded=False):
                                        st.code(msg.content, language="text")
                                        
                                    current_traces.append({
                                        "type": "tool_output",
                                        "name": msg.name,
                                        "content": msg.content
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="tools",
                                        tool_name=msg.name,
                                        content=msg.content
                                    )
                
                status.update(label="Incident Matrix Evaluation Complete", state="complete", expanded=False)
                
            if final_response:
                st.markdown(final_response)
                st.session_state.ui_messages.append({
                    "role": "assistant",
                    "content": final_response,
                    "traces": current_traces
                })
            else:
                error_fallback = "⚠️ Execution Timeout: System engine encountered an unresolved processing edge case."
                st.error(error_fallback)


elif app_mode == "🛡️ Admin Operations":
    # ------------------------------------------
    # ADMIN OPERATIONS (RBAC GATED BY SQL_ADMIN_USER / PASSWORD)
    # ------------------------------------------
    st.title("🛡️ Enterprise Administrative Operations")
    st.caption("Secure Management Portal for SOP Knowledge Assets & Immutable Audit Logs")

    expected_admin_user = os.getenv("SQL_ADMIN_USER", "sa")
    expected_admin_pass = os.getenv("SQL_ADMIN_PASSWORD")

    if not st.session_state.admin_authenticated:
        st.markdown("### 🔐 Database & System Authorization Gate")
        st.info("Administrative access requires elevated credentials (`SQL_ADMIN_USER` / `SQL_ADMIN_PASSWORD`).")

        with st.form("admin_auth_form"):
            col1, col2 = st.columns(2)
            with col1:
                input_user = st.text_input("Admin Username", value=expected_admin_user)
            with col2:
                input_pass = st.text_input("Admin Password", type="password", value="")

            submit_admin = st.form_submit_button("Authenticate as Admin", use_container_width=True)

        if submit_admin:
            if input_user == expected_admin_user and input_pass == expected_admin_pass:
                st.session_state.admin_authenticated = True
                st.session_state.admin_user = input_user
                st.session_state.admin_pass = input_pass
                st.toast("✅ Authenticated successfully as Administrator!")
                st.rerun()
            else:
                st.error("❌ Invalid Administrator Credentials. Access Denied.")
    else:
        # Authenticated Admin Header with Sign-out
        col_status, col_btn = st.columns([4, 1])
        with col_status:
            st.success(f"🔐 Authenticated as: **{st.session_state.admin_user}** (Elevated Privileges)")
        with col_btn:
            if st.button("🚪 Sign Out", use_container_width=True):
                st.session_state.admin_authenticated = False
                st.session_state.admin_user = ""
                st.session_state.admin_pass = ""
                st.rerun()

        # Admin Feature Tabs
        tab_sop, tab_audit = st.tabs(["📋 SOP Policy Management", "📊 Security & Audit Logs"])

        # ----------------------------------------------------
        # TAB 1: SOP KNOWLEDGE BASE MANAGER
        # ----------------------------------------------------
        with tab_sop:
            st.markdown("### Standard Operating Procedure (SOP) Knowledge Base")
            st.caption("Manage regulatory documents, operational thresholds, and synchronize Pinecone vector indices.")

            # Refresh documents list
            docs = sop_service.list_sop_documents()
            total_docs = len(docs)
            total_size = sum(d["size_kb"] for d in docs)
            all_synced = all(d["is_synced"] for d in docs) if docs else False

            # Top Metrics & Sync Trigger
            m_col1, m_col2, m_col3, m_col4 = st.columns([1.5, 1.5, 2, 2])
            with m_col1:
                st.metric("Total SOP Assets", total_docs)
            with m_col2:
                st.metric("Storage Footprint", f"{total_size:.2f} KB")
            with m_col3:
                st.metric("Pinecone Index State", "🟢 Fully Synced" if all_synced else "🟡 Sync Recommended")
            with m_col4:
                st.write("")
                if st.button("🔄 Sync with Pinecone", use_container_width=True):
                    with st.status("🔄 Synchronizing SOP Knowledge Base with Pinecone...", expanded=True) as status:
                        success, logs = sop_service.run_pinecone_ingestion_sync()
                        if success:
                            status.update(label="✅ Knowledge Base Synchronized Successfully!", state="complete", expanded=False)
                            st.toast("Pinecone vector store is up to date!")
                        else:
                            status.update(label="❌ Synchronization Failed", state="error", expanded=True)
                            st.error("Error occurred during vector sync.")
                        with st.expander("📜 Ingestion Engine Logs", expanded=not success):
                            st.code(logs, language="text")
                    st.rerun()

            st.markdown("---")

            # Document Inventory Table
            st.markdown("#### 📁 Active Policy Inventory (`data/policy/`)")
            if docs:
                df_docs = pd.DataFrame(docs)[["filename", "format", "size_kb", "modified", "sync_status"]]
                st.dataframe(
                    df_docs,
                    column_config={
                        "filename": "Document Asset",
                        "format": "Format",
                        "size_kb": st.column_config.NumberColumn("Size", format="%.2f KB"),
                        "modified": "Last Modified",
                        "sync_status": "Index Status"
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No policy files found in `data/policy/`. Upload a document below.")

            st.markdown("---")
            st.markdown("#### 🛠️ Document Operations")

            op_upload, op_edit, op_delete = st.tabs(["📤 Upload New SOP", "✏️ View & Edit SOP", "🗑️ Delete SOP"])

            # SUB-OPERATION 1: UPLOAD
            with op_upload:
                st.markdown("Upload new compliance guidelines (`.md`, `.pdf`, `.txt`, `.csv`, `.xlsx`).")
                uploaded_file = st.file_uploader(
                    "Select Document Asset",
                    type=["md", "pdf", "txt", "csv", "xlsx"],
                    key="sop_file_uploader"
                )
                auto_sync_on_upload = st.checkbox("Automatically synchronize with Pinecone after saving", value=True)

                if st.button("💾 Save & Upload to Policy Store", disabled=(uploaded_file is None), use_container_width=True):
                    if uploaded_file is not None:
                        saved_path = sop_service.upload_sop_asset(uploaded_file.name, uploaded_file.getvalue())
                        st.success(f"✅ Saved `{uploaded_file.name}` to `{saved_path}`.")
                        if auto_sync_on_upload:
                            with st.status("🔄 Ingesting into Pinecone Vector Index...", expanded=True) as status:
                                success, logs = sop_service.run_pinecone_ingestion_sync()
                                if success:
                                    status.update(label="✅ Document Indexed Successfully!", state="complete", expanded=False)
                                else:
                                    status.update(label="❌ Indexing Encountered Issues", state="error", expanded=True)
                                with st.expander("📜 Ingestion Engine Output", expanded=not success):
                                    st.code(logs, language="text")
                        st.rerun()

            # SUB-OPERATION 2: VIEW & EDIT
            with op_edit:
                editable_docs = [d["filename"] for d in docs if d["editable"]]
                if editable_docs:
                    selected_edit_doc = st.selectbox("Choose Policy to Edit", editable_docs)
                    current_content = sop_service.read_sop_text(selected_edit_doc)
                    edited_content = st.text_area("Document Content (Markdown / Text)", value=current_content, height=450)
                    auto_sync_on_edit = st.checkbox("Automatically synchronize with Pinecone on save", value=True, key="edit_sync_chk")

                    if st.button("💾 Save Modifications & Re-Index", use_container_width=True):
                        sop_service.save_sop_text(selected_edit_doc, edited_content)
                        st.success(f"✅ Updated `{selected_edit_doc}` successfully.")
                        if auto_sync_on_edit:
                            with st.status("🔄 Re-indexing Modified Chunks in Pinecone...", expanded=True) as status:
                                success, logs = sop_service.run_pinecone_ingestion_sync()
                                if success:
                                    status.update(label="✅ Vector Index Synchronized!", state="complete", expanded=False)
                                else:
                                    status.update(label="❌ Ingestion Error", state="error", expanded=True)
                                with st.expander("📜 Ingestion Engine Output", expanded=not success):
                                    st.code(logs, language="text")
                        st.rerun()
                else:
                    st.info("No editable text documents (`.md`, `.txt`) currently available.")

            # SUB-OPERATION 3: DELETE
            with op_delete:
                if docs:
                    all_filenames = [d["filename"] for d in docs]
                    selected_del_doc = st.selectbox("Select Policy Document to Delete", all_filenames)
                    st.warning(f"⚠️ Deleting `{selected_del_doc}` will permanently remove it from `data/policy/` and purge its vector chunks from Pinecone.")
                    confirm_del = st.checkbox(f"Confirm permanent deletion of `{selected_del_doc}`", value=False)

                    if st.button("🗑️ Permanently Delete Document", disabled=not confirm_del, use_container_width=True):
                        sop_service.delete_sop_asset(selected_del_doc)
                        st.success(f"Deleted `{selected_del_doc}` from disk.")
                        with st.status("🔄 Purging Vector Chunks from Pinecone...", expanded=True) as status:
                            success, logs = sop_service.run_pinecone_ingestion_sync()
                            if success:
                                status.update(label="✅ Vector Chunks Purged & Index Updated!", state="complete", expanded=False)
                            else:
                                status.update(label="❌ Purge Encountered Issues", state="error", expanded=True)
                            with st.expander("📜 Ingestion Engine Output", expanded=not success):
                                st.code(logs, language="text")
                        st.rerun()
                else:
                    st.info("No documents available to delete.")

        # ----------------------------------------------------
        # TAB 2: AUDIT LOG VIEWER
        # ----------------------------------------------------
        with tab_audit:
            st.markdown("### 📊 Enterprise Agent Audit Trail")
            st.caption("Secure inspection of `FDE_VIEWS.AgentAuditLog`")

            try:
                admin_engine = get_mssql_engine(st.session_state.admin_user, st.session_state.admin_pass)
                with admin_engine.connect() as conn:
                    query = """
                        SELECT LogID, Timestamp, SessionID, NodeExecuted, ToolName, Content 
                        FROM FDE_VIEWS.AgentAuditLog 
                        ORDER BY Timestamp DESC
                    """
                    df = pd.read_sql(query, conn)

                if not df.empty:
                    st.dataframe(
                        df,
                        column_config={
                            "LogID": st.column_config.NumberColumn("ID", format="%d"),
                            "Timestamp": st.column_config.DatetimeColumn("Execution Time", format="DD/MM/YYYY-h:mm a"),
                            "SessionID": "Session Token",
                            "NodeExecuted": "Graph Node",
                            "ToolName": "Tool Triggered",
                            "Content": "Raw Payload Data"
                        },
                        hide_index=True,
                        use_container_width=True,
                        height=600
                    )
                else:
                    st.info("No audit logs found in the database. Run a query in the Dispatch Console first.")
            except Exception as e:
                st.error(f"Database Query Failed: {e}")