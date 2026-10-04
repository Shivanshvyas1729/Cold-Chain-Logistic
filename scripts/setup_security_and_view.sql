-- ====================================================================
-- FDE ENTERPRISE SECURITY & SEMANTIC LAYER SCRIPT
-- Purpose: Protect the dedicated LogisticsDB from LLM hallucinations and mutations
-- ====================================================================

-- 1. Ensure dedicated application database exists
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'LogisticsDB')
BEGIN
    CREATE DATABASE LogisticsDB;
END
GO

-- 2. Switch context to the dedicated application database
USE LogisticsDB;
GO

-- 3. Create a dedicated schema for our clean AI views if it doesn't already exist
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'FDE_VIEWS')
BEGIN
    EXEC('CREATE SCHEMA FDE_VIEWS');
END
GO

-- 4. Create or update the Semantic View (Translating legacy columns to clean English)
CREATE OR ALTER VIEW FDE_VIEWS.VW_ACTIVE_FLEET AS
SELECT 
    TS_UTC AS [Timestamp],
    V_LAT AS [Latitude],
    V_LON AS [Longitude],
    CAST(IOT_TEMP_VAL_C AS FLOAT) AS [Current_Temperature_C],
    CGO_COND_CD AS [Cargo_Condition_Code],
    RISK_CLS_TXT AS [Risk_Classification],
    DELAY_PROB_DEC AS [Delay_Probability],
    PRT_CNG_LVL AS [Port_Congestion_Level],
    RT_RSK_IDX AS [Route_Risk_Index]
FROM dbo.TBL_SC_FLEET_HIST_RAW;
GO

-- 5. Create server-level login for the AI Agent if not already existing
IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = 'USR_FDE_RO')
BEGIN
    CREATE LOGIN USR_FDE_RO WITH PASSWORD = 'AgentPassword2026!';
END
GO

-- 6. Create database-level user inside LogisticsDB mapped to the server login
IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = 'USR_FDE_RO')
BEGIN
    CREATE USER USR_FDE_RO FOR LOGIN USR_FDE_RO;
END
GO

-- 7. Grant access ONLY to the semantic view, explicitly denying raw legacy tables
GRANT SELECT ON FDE_VIEWS.VW_ACTIVE_FLEET TO USR_FDE_RO;
DENY SELECT ON dbo.TBL_SC_FLEET_HIST_RAW TO USR_FDE_RO;
DENY INSERT, UPDATE, DELETE, ALTER ON SCHEMA::dbo TO USR_FDE_RO;
GO

-- 8. Phase 4 Agent Audit Log Table (in dedicated LogisticsDB)
IF NOT EXISTS (SELECT * FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE s.name = 'FDE_VIEWS' AND t.name = 'AgentAuditLog')
BEGIN
    CREATE TABLE FDE_VIEWS.AgentAuditLog (
        LogID INT IDENTITY(1,1) PRIMARY KEY,
        Timestamp DATETIME DEFAULT GETDATE(),
        SessionID VARCHAR(50),
        NodeExecuted VARCHAR(50),
        ToolName VARCHAR(100),
        Content NVARCHAR(MAX)
    );
    GRANT INSERT ON FDE_VIEWS.AgentAuditLog TO USR_FDE_RO;
END
GO