Viewed agent_tools.py:1-60
Viewed agent_tools.py:80-140
Viewed setup_security_and_view.sql:1-60

Here is the complete guide to running the entire **Cold-Chain Logistics AI system locally on your machine** (Windows with Docker Desktop).

---

### 💻 Local Architecture Overview
When running locally:
* **Database**: Microsoft SQL Server 2022 runs in **Docker Desktop** on `localhost:1433`.
* **AI & Web UI**: The LangGraph Agent and Streamlit Web Console run in your local Python `.venv`.
* **Vector Store**: Pinecone runs in the cloud (accessed via `PINECONE_API_KEY`).
* **Weather API**: Open-Meteo REST API (zero authentication, queries directly).

---

### 🚀 Step-by-Step Local Setup

#### Step 1: Start SQL Server in Local Docker Desktop
Make sure **Docker Desktop** is open and running on your Windows machine, then run:

```powershell
docker run -v mssql_data:/var/opt/mssql `
  -e "ACCEPT_EULA=Y" `
  -e "MSSQL_SA_PASSWORD=FdeEnterprisePass123!" `
  -p 1433:1433 `
  --name legacy-mssql `
  --restart unless-stopped `
  -d mcr.microsoft.com/mssql/server:2022-latest
```

*Verify it's running:*
```powershell
docker ps
```
*(You should see `legacy-mssql` with port `0.0.0.0:1433->1433/tcp`)*

---

#### Step 2: Configure Your Local [`.env`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/.env) File
Ensure your `.env` is set to **`localhost`**:

```env
# Database Settings (Local Docker)
SQL_SERVER_HOST=localhost
SQL_SERVER_PORT=1433
DB_NAME=LogisticsDB
SQL_ADMIN_USER=sa
SQL_ADMIN_PASSWORD=FdeEnterprisePass123!
SQL_AGENT_USER=USR_FDE_RO
SQL_AGENT_PASSWORD=AgentPassword2026!

# LLM & Embeddings API
BASE_URL=https://api.aicredits.in/v1
API_KEY=sk-...
Agent_llm=DEEPSEEK
Embeddings_model=OPENAI

# Vector Database
PINECONE_API_KEY=pcsk_...
```

---

#### Step 3: Ingest Historical Telemetry into Local Database
In your local PowerShell, run:

```powershell
uv run python scripts/ingest_legacy_data.py
```
*(Or `python scripts/ingest_legacy_data.py` if not using `uv`)*

**What this does:**
1. Connects to `localhost:1433`.
2. Creates the `LogisticsDB` database if not present.
3. Ingests all **32,065 historical records** into `dbo.TBL_SC_FLEET_HIST_RAW`.

---

#### Step 4: Create Semantic Views & Security Roles
Execute the SQL security script to create the clean view `FDE_VIEWS.VW_ACTIVE_FLEET`, the restricted role `USR_FDE_RO`, and the `AgentAuditLog` table:

**Option A (PowerShell Pipe directly to Docker container - Fastest):**
```powershell
Get-Content scripts\setup_security_and_view.sql | docker exec -i legacy-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "FdeEnterprisePass123!" -C -d LogisticsDB
```

**Option B (Via VS Code SQL Server extension):**
1. Connect to `Server: localhost, 1433`, User: `sa`, Password: `FdeEnterprisePass123!`.
2. Open [`scripts/setup_security_and_view.sql`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/scripts/setup_security_and_view.sql).
3. Press **Ctrl + Shift + E** (or click the green Play button).

---

#### Step 5: Index SOP Guidelines into Pinecone
Run the SOP vectorization script:

```powershell
uv run python scripts/ingest_sop_pinecone.py
```
*(This parses [`data/policy/Cold_Chain_Incident_SOP_v2.md`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/data/policy/Cold_Chain_Incident_SOP_v2.md) and indexes the compliance vectors into Pinecone Cloud).*

---

#### Step 6: Launch and Test the Application Locally

You have **two interfaces** to run the local AI dispatcher:

##### Option A: Streamlit Web UI (Recommended)
```powershell
uv run streamlit run src/ui.py
```
* Automatically opens in your browser at: **`http://localhost:8501`**
* Features:
  * 📊 **Fleet KPI Metrics**: Live trucks count, critical high-risk alerts, avg temperatures.
  * 💬 **Interactive Dispatch Chat**: Plain-English questions with expandable accordion tool traces (SQL, Open-Meteo weather, Pinecone SOP hits).
  * 📑 **Admin Audit Log & SOP Manager**: Live inspection of every query logged to `FDE_VIEWS.AgentAuditLog`.

##### Option B: Terminal Interactive CLI
```powershell
uv run python src/orchestrator.py
```
* Runs in your terminal with a `Dispatcher >` prompt.

---

### 🧪 Test Queries to Try Locally

1. **Multi-Tool Domino Effect Test** (Queries SQL + Weather API + Pinecone SOP):
   > *"Find active shipments near Los Angeles (Latitude ~33.8, Longitude ~-118.1). Check the local weather there, and tell me if the current cargo temperature violates our perishables SOP."*

2. **Restraint Test** (Pure reasoning, no unnecessary SQL/tools executed):
   > *"I'm a new dispatcher on the night shift. Can you quickly explain the difference between a Tier 1 and Tier 2 escalation?"*

---

### 🔄 How to Switch Between Local & AWS Cloud
You only ever need to toggle **one line** in your [`.env`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/.env) file:
* **To run locally**: `SQL_SERVER_HOST=localhost`
* **To query AWS EC2**: `SQL_SERVER_HOST=<YOUR_EC2_PUBLIC_IP>`













----------------------------------------------------
Viewed README.md:1210-1260

Here is the clear, step-by-step separation: **First, you upload and prepare the data on AWS EC2**, and **second, you use GitHub Actions (`deploy.yml`) to deploy the application**.

---

# 📦 STAGE 1: First, Push the Data to AWS EC2
*(Do this first from your local computer. This is a one-time database setup.)*

### Step 1: In AWS Console, Open Port 1433
1. Open **AWS Management Console** $\rightarrow$ **EC2** $\rightarrow$ **Security Groups**.
2. Select your EC2 instance's security group $\rightarrow$ **Edit inbound rules**.
3. Add this rule so your local computer can stream data to the EC2 database:
   * **Type**: MS SQL (Port `1433`)
   * **Source**: `Anywhere-IPv4` (`0.0.0.0/0`) or `My IP`

---

### Step 2: Start SQL Server in Docker on EC2
SSH into your EC2 instance:
```bash
ssh -i "cold-chain-key.pem" ubuntu@<YOUR_EC2_PUBLIC_IP>
```
Run this single command to spin up the SQL Server database container:
```bash
docker run -v mssql_data:/var/opt/mssql \
  -e "ACCEPT_EULA=Y" \
  -e "MSSQL_SA_PASSWORD=FdeEnterprisePass123!" \
  -p 1433:1433 \
  --name legacy-mssql \
  --restart unless-stopped \
  -d mcr.microsoft.com/mssql/server:2022-latest
```
*(You can now exit the SSH session: type `exit`)*

---

### Step 3: Stream the 32,065 Rows from Your Local Machine to AWS
1. On your **local machine**, open [`.env`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/.env) and change `SQL_SERVER_HOST` from `localhost` to your EC2 public IP:
   ```env
   SQL_SERVER_HOST=<YOUR_EC2_PUBLIC_IP>
   SQL_SERVER_PORT=1433
   SQL_ADMIN_USER=sa
   SQL_ADMIN_PASSWORD=FdeEnterprisePass123!
   DB_NAME=LogisticsDB
   ```

2. Open your local Windows PowerShell in the project directory and run:
   ```powershell
   uv run python scripts/ingest_legacy_data.py
   ```
   **What happens here:** This runs locally on your PC, reaches across the internet to your AWS EC2 container on port 1433, automatically provisions `LogisticsDB`, and streams all **32,065 rows** into `dbo.TBL_SC_FLEET_HIST_RAW`.

---

### Step 4: Create Security Views & Roles on AWS
Now configure the security schema (`FDE_VIEWS.VW_ACTIVE_FLEET` and role `USR_FDE_RO`) on EC2:
* **Option A (VS Code)**: In VS Code, connect the **SQL Server (mssql)** extension to `<YOUR_EC2_PUBLIC_IP>`, open [`scripts/setup_security_and_view.sql`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/scripts/setup_security_and_view.sql), and click **Execute**.
* **Option B (SSH one-liner on EC2)**:
  ```bash
  docker exec -i legacy-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "FdeEnterprisePass123!" -C -d LogisticsDB < scripts/setup_security_and_view.sql
  ```

---

### Step 5: Upload SOP Documents to Pinecone
From your **local machine terminal**:
```powershell
uv run python scripts/ingest_sop_pinecone.py
```
*(This parses [`data/policy/Cold_Chain_Incident_SOP_v2.md`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/data/policy/Cold_Chain_Incident_SOP_v2.md) and indexes the compliance vectors into Pinecone Cloud).*

---

### Step 6: Verify Data is Live on AWS
To be 100% sure your database on AWS has the data, run:
```powershell
python -c "from src.agent_tools import query_telemetry_db; print(query_telemetry_db.invoke('SELECT @@SERVERNAME as server_name, COUNT(*) as total_records FROM FDE_VIEWS.VW_ACTIVE_FLEET'))"
```
If you see the EC2 container ID and **32,065 rows**, **Stage 1 is complete!**

---
---

# 🚀 STAGE 2: Then, Deploy the Application (`deploy.yml`)
*(Now that your database and data are live in AWS, deploy the AI web application).*

### 1. Add Secrets in GitHub
Go to your GitHub repo $\rightarrow$ **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions** $\rightarrow$ **New repository secret**:

| Secret Name | Value |
| :--- | :--- |
| `EC2_HOST` | `<YOUR_EC2_PUBLIC_IP>` |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | Paste the **entire content** of your `cold-chain-key.pem` file |
| `ENV_FILE` | Paste the text of your project's [`.env`](file:///c:/Users/DELL/Desktop/Cold%20Chain%20Logistic/.env) file |

---

### 2. Push Code to Trigger Auto-Deployment
Commit your changes and push to GitHub:
```powershell
git add .
git commit -m "Setup CI/CD deployment to AWS EC2"
git push origin main
```

---

### 3. What GitHub Actions Does Automatically
When you push to `main`:
1. ✅ Runs syntax validation on all Python scripts.
2. 🔑 Connects to your EC2 instance via SSH.
3. 📥 Pulls the latest code and updates `venv` dependencies.
4. 🐳 Confirms the `legacy-mssql` Docker container is running.
5. 🔄 Restarts the `streamlit` service.
6. 🌐 Your live AI Dispatcher Console is ready at:
   ```text
   http://<YOUR_EC2_PUBLIC_IP>:8501
   ```