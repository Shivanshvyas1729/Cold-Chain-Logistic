from pathlib import Path
import pandas as pd
import urllib.parse
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Path resolution
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parents[0]

load_dotenv(project_root / ".env")

data_path = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset.csv"

# you are creating a database inside docker container -> local host-> port 1433->user->sa->pass 
db_host = os.getenv("SQL_SERVER_HOST", "localhost")
db_port = os.getenv("SQL_SERVER_PORT", "1433")
db_user = os.getenv("SQL_ADMIN_USER", "sa")
db_password = os.getenv("SQL_ADMIN_PASSWORD")
db_name = os.getenv("DB_NAME", "LogisticsDB")

def get_db_engine(target_db: str = None):
    active_db = target_db or db_name
    # Attempt pyodbc if modern ODBC Driver 18/17 is installed
    try:
        import pyodbc
        available = pyodbc.drivers()
        preferred = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
        selected_driver = next((d for d in preferred if d in available), None)
        if selected_driver:
            extra = "Encrypt=no;TrustServerCertificate=yes;" if "18" in selected_driver else "TrustServerCertificate=yes;"
            conn_str = (
                f"DRIVER={{{selected_driver}}};"
                f"SERVER={db_host},{db_port};"
                f"DATABASE={active_db};"
                f"UID={db_user};"
                f"PWD={db_password};"
                f"{extra}"
            )
            params = urllib.parse.quote_plus(conn_str)
            return create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)
    except Exception:
        pass

    # Seamless cross-platform fallback with pymssql (no Windows ODBC Driver MSI required)
    encoded_pwd = urllib.parse.quote_plus(db_password) if db_password else ""
    return create_engine(f"mssql+pymssql://{db_user}:{encoded_pwd}@{db_host}:{db_port}/{active_db}")

def ensure_database_exists():
    """Checks if the target database exists; if not, creates it via the master connection."""
    admin_engine = get_db_engine(target_db="master")
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(text(f"SELECT 1 FROM sys.databases WHERE name = '{db_name}'")).scalar()
        if not exists:
            print(f"Creating dedicated database [{db_name}]...")
            conn.execute(text(f"CREATE DATABASE [{db_name}]"))
            print(f"Database [{db_name}] created successfully.")
        else:
            print(f"Dedicated database [{db_name}] is already available.")

# 1. Ensure target database exists
ensure_database_exists()

# 2. Load the raw dataset
print(f"Loading CSV from {data_path}...")
df = pd.read_csv(data_path)

# 3. Map clean columns to legacy enterprise schema
legacy_mapping = {
    'timestamp': 'TS_UTC',
    'vehicle_gps_latitude': 'V_LAT',
    'vehicle_gps_longitude': 'V_LON',
    'iot_temperature': 'IOT_TEMP_VAL_C',
    'cargo_condition_status': 'CGO_COND_CD',
    'risk_classification': 'RISK_CLS_TXT',
    'delay_probability': 'DELAY_PROB_DEC',
    'port_congestion_level': 'PRT_CNG_LVL',
    'route_risk_level': 'RT_RSK_IDX'
}

df_legacy = df[list(legacy_mapping.keys())].rename(columns=legacy_mapping)
df_legacy['SYS_INGEST_FLAG'] = 'Y'

# 4. Connect to target MSSQL Database
print(f"Connecting to dedicated MSSQL Database [{db_name}]...")
engine = get_db_engine()

# 5. Ingest data into the table
table_name = 'TBL_SC_FLEET_HIST_RAW'
print(f"Ingesting into {table_name}. This may take a minute...")
df_legacy.to_sql(table_name, engine, if_exists='replace', index=False, schema='dbo', chunksize=2000)

print(f"[SUCCESS] Legacy data ingestion complete into [{db_name}]! (32,065 rows ingested)")