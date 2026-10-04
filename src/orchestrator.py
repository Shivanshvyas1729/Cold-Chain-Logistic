import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from pathlib import Path
from dotenv import load_dotenv

from typing import TypedDict , Annotated
from agent_tools import( query_telemetry_db , fetch_corridor_conditions , search_compliance_sop)
from langchain_core.messages import BaseMessage , SystemMessage
from langgraph.graph import StateGraph , START, END
from langgraph.graph.message import add_messages 
import os
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver


# ==========================================
# 1. SETUP & PATH RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parents[0]
load_dotenv(project_root / ".env")


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage],add_messages]

# ==========================================
# 2. FACTORY INITIALIZATION: AGENT REASONER LLM
# ==========================================

AGENT_LLM_SETTING = os.getenv("Agent_llm", "OLLAMA").strip().upper()
BASE_URL = os.getenv("BASE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.strip()

LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")

if AGENT_LLM_SETTING == "OPENAI":
    print("🤖 Brain Mode: Utilizing Cloud OpenAI Reasoner (gpt-4o)...")
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o", temperature=0, base_url=BASE_URL, api_key=LLM_API_KEY)

elif AGENT_LLM_SETTING == "DEEPSEEK":
    print("🐳 Brain Mode: Utilizing Flagship DeepSeek Cloud Reasoner (deepseek-v4-flash)...")
    from langchain_openai import ChatOpenAI
    
    llm = ChatOpenAI(
        model="deepseek-v4-flash",
        temperature=0,
        api_key=LLM_API_KEY,
        base_url=BASE_URL,
        max_tokens=2048,
    )


else:  # FALLBACK / DEFAULT RUNNER MODE
    print("🤗 Brain Mode: Local Fallback Activated. Binding Local Ollama (qwen2.5:7b)...")
    from langchain_community.chat_models import ChatOllama
    llm = ChatOllama(model="qwen2.5:7b", temperature=0, num_predict=1024)


tools = [query_telemetry_db,fetch_corridor_conditions,search_compliance_sop]

llm_with_tools = llm.bind_tools(tools)


def reasoning_node(state:AgentState):
    response = llm_with_tools.invoke(state["messages"])

    return {"messages":[response]}


    
print("⚙️ Compiling LangGraph  Orchestrator...")

graph_builder = StateGraph(AgentState)

graph_builder.add_node("reasoner",reasoning_node)
graph_builder.add_node("tools",ToolNode(tools))


graph_builder.add_edge(START, "reasoner")
graph_builder.add_conditional_edges("reasoner", tools_condition)
graph_builder.add_edge("tools", "reasoner")

agent = graph_builder.compile(checkpointer=MemorySaver())
fde_agent = agent









# ==========================================
# 4. CHAT LOOP TESTING PANEL
# ==========================================
if __name__ == "__main__":
    print("\n" + "="*55)
    print("🚀 FDE Supply Chain Orchestrator State Machine Online")
    print(f"   Configured Execution: [LLM: {AGENT_LLM_SETTING}] -> [Embeddings: {os.getenv('Embeddings_model', 'LOCAL')}]")
    print("="*55 + "\n")
    
    # Load the business-structured system prompt from the external file
    prompt_path = project_root / "src" / "prompts" / "system_prompt.txt"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_instructions = f.read()
    except FileNotFoundError:
        print(f"Error: Could not find {prompt_path}")
        system_instructions = "You are a helpful AI assistant." # Basic fallback

    system_prompt = SystemMessage(content=system_instructions)
    
    thread_config = {"configurable": {"thread_id": "production_test_1"}}
    agent.update_state(thread_config, {"messages": [system_prompt]})
    
    while True:
        user_input = input("\nDispatcher > ")
        if user_input.lower() in ['exit', 'quit']:
            break
            
        events = agent.stream({"messages": [("user", user_input)]}, config=thread_config, stream_mode="updates")
        for event in events:
            for node_name, node_state in event.items():
                if node_name == "tools":
                    print("   [System] 🔄 Retrieving external data elements via ToolNode...")
                elif node_name == "reasoner":
                    latest_msg = node_state["messages"][-1]
                    if latest_msg.content:
                        print(f"\n🤖 FDE Agent:\n{latest_msg.content}")