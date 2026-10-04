import os
import urllib.parse
from pathlib import Path
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore


# ==========================================
# 1. ENVIRONMENT & CONFIGURATION
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
load_dotenv(dotenv_path=project_root / ".env")



PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
if not PINECONE_API_KEY:
    raise ValueError("CRITICAL: Ensure PINECONE_API_KEY is present in your .env file.")



# Database Credentials
DB_HOST = os.getenv("SQL_SERVER_HOST", "localhost")
DB_PORT = os.getenv("SQL_SERVER_PORT", "1433")
DB_USER = os.getenv("SQL_AGENT_USER", "USR_FDE_RO")
DB_PASSWORD = os.getenv("SQL_AGENT_PASSWORD")
DB_NAME= os.getenv("")

# Model Settings
EMBEDDINGS_MODE = os.getenv("Embeddings_model", "LOCAL").strip().upper()
OPENAI_BASE_URL = os.getenv("BASE_URL")
OPENAI_API_KEY = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
LOCAL_MODEL_NAME = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()




# ==========================================
# 2. EMBEDDINGS & VECTOR STORE SETUP
# ==========================================
def _load_local_hf_model(model_name: str) -> HuggingFaceEmbeddings:
    """Helper to instantiate local HuggingFace embeddings with normalization."""
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},  # Optimizes for cosine similarity
    )



def get_embeddings_and_index():
    """Initializes embeddings and selects index dynamically."""
    if EMBEDDINGS_MODE == "OPENAI":
        print("🤖 Mode: Utilizing Cloud OpenAI Embeddings (1536 Dim)...")
        openai_kwargs = {"model": "text-embedding-3-small"}
        if OPENAI_API_KEY:
            openai_kwargs["api_key"] = OPENAI_API_KEY
        if OPENAI_BASE_URL:
            openai_kwargs["base_url"] = OPENAI_BASE_URL

        embeddings = OpenAIEmbeddings(**openai_kwargs)
        index_name = "sop-index-openai"
        return embeddings, index_name

    # Local HuggingFace Mode
    print(f"🤗 Mode: Local HuggingFace Embedding Activated [{LOCAL_MODEL_NAME}] (1024 Dim)...")
    
    # Cache weights in RAM if running within a Streamlit session
    try:
        import streamlit as st
        if st.runtime.exists():
            cached_loader = st.cache_resource(show_spinner=False)(_load_local_hf_model)
            embeddings = cached_loader(LOCAL_MODEL_NAME)
        else:
            embeddings = _load_local_hf_model(LOCAL_MODEL_NAME)
    except ImportError:
        embeddings = _load_local_hf_model(LOCAL_MODEL_NAME)

    index_name = "sop-index-local"
    return embeddings, index_name


    
embeddings, index_name = get_embeddings_and_index()
vector_store = PineconeVectorStore(index_name=index_name, embedding=embeddings)
retriever = vector_store.as_retriever(search_kwargs={"k": 2})


# ==========================================
# 3. AGENT TOOLS
# ==========================================
@tool
def query_telemetry_db(sql_query: str) -> str:
    """
    Executes a read-only SELECT query against FDE_VIEWS.VW_ACTIVE_FLEET.
    Columns: Timestamp, Latitude, Longitude, Current_Temperature_C,
    Cargo_Condition_Code, Risk_Classification, Delay_Probability,
    Port_Congestion_Level, Route_Risk_Index.
    """
    if not sql_query.strip().upper().startswith("SELECT"):
        return "SECURITY BLOCK: Only SELECT queries are permitted."

    target_database_name = os.getenv("DB_NAME", "LogisticsDB")

    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_HOST},{DB_PORT};"
        f"DATABASE={target_database_name};" 
        f"UID={DB_USER};" # Should be the restricted user, e.g., 'USR_FDE_RO'
        f"PWD={DB_PASSWORD};"
        f"Encrypt=no;TrustServerCertificate=yes;"
    )
    params = urllib.parse.quote_plus(conn_str)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

    try:
        with engine.connect() as conn:
            cursor = conn.execute(text(sql_query))
            rows = cursor.fetchmany(10)
            if not rows:
                return "No records matched the query criteria."

            formatted = f"COLUMNS: {', '.join(cursor.keys())}\n"
            for row in rows:
                formatted += f"{tuple(row)}\n"
            return formatted
    except Exception as e:
        return f"Database Error: {e}"



@tool
def fetch_corridor_conditions(latitude:float,longitude:float)->str:
    """Fetches real-time weather and corridor risk from Open-Meteo for given coordinates."""

    # 1. Define your base URL and coordinates
    url = "https://api.open-meteo.com/v1/forecast"
    # 2. Package your query variables into a dictionary
    # The requests library will automatically glue these onto the URL
    query_parameters = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ["temperature_2m", "wind_speed_10m", "weather_code"],
        "timezone": "auto"
    }

    try:
        response = requests.get(url,params=query_parameters)
        response.raise_for_status()
        data = response.json()
        current_data = data["current"]


        temperature = current_data.get("temperature_2m","N/A")
        wind_speed = current_data.get("wind_speed_10m",0.0)
        time = current_data.get("time","N/A")
        disrupted = wind_speed > 10.0 

        
        return (
            f"--- LIVE CORRIDOR TELEMETRY ---\n"
            f"Target GPS: {latitude}, {longitude}\n"
            f"External Temp: {temperature}°C | Wind Speed: {wind_speed} km/h\n"
            f"Corridor Risk: {'High Disruption' if disrupted else 'Normal'} "
            f"(Congestion Index: {8.5 if disrupted else 2.5}/10)\n"
            f"-------------------------------"
        )
    except Exception as e:
        return f"Corridor API Communication Failure: {e}"


@tool
def search_compliance_sop(query:str)->str:
    """Searches compliance and Standard Operating Procedure (SOP) documents in Pinecone."""

    try:
        retrieved_docs = retriever.invoke(query)
        if not retrieved_docs :
            return f"No matching compliance clause found.you can retry by enchancing the query."

        context = "\n\n".join(
            f"--- Document ---\n"
            f"Source: {doc.metadata.get('source_file', 'SOP')}\n"
            f"Format: {doc.metadata.get('file_format', 'RAW')}\n"
            f"Type: {doc.metadata.get('document_type', 'UNKNOWN')}\n"
            f"Content:\n{doc.page_content.strip()}"
            for doc in retrieved_docs
        )  


        return f"""--- COMPLIANCE SOP CONTEXT  ---
        {context}
        --- END OF RETRIEVED CONTEXT ---"""
        
    except Exception as e:
        return f"Vector Store Retrieval Error: {e}"





# ==========================================
# 4. VERIFICATION / TESTING
# ==========================================
if __name__ == "__main__":
    print("\n--- Testing Tool 1: SQL Telemetry View ---")
    print(query_telemetry_db.invoke("SELECT TOP 2 Latitude, Longitude, Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET"))

    # print("\n--- Testing Tool 2: Live Corridor API ---")
    # print(fetch_corridor_conditions.invoke({"latitude": 33.77, "longitude": -118.19}))

    # print("\n--- Testing Tool 3: Pinecone Vector Retrieval ---")
    # print(search_compliance_sop.invoke("What are the temperature rules for fresh perishables?"))