# main.py

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Azure identity and AI Project
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    BingGroundingTool, # Keep Bing for general questions if needed
    FunctionTool,
    ToolSet
)

# --- Import our store functions ---
from store_functions import (
    check_item_stock,
    find_item_location,
    get_shelf_layout,
    request_item_from_storage,
    check_delivery_status,
    get_items_needing_restock,
    update_inventory_count,
    mark_item_restocked,
    log_damaged_item,
    get_store_layout_overview,
    identify_and_restock_item_from_image # Simulated vision function
)

# Import the Gradio chat interface creator
import gradio as gr
from chat_ui import create_chat_interface

# Import tracing setup
from tracing import init_tracer, get_tracer

# --------------------------------------------------
# 1) Initialize the Azure AI Project Client
# --------------------------------------------------
credential = DefaultAzureCredential()
project_client = AIProjectClient.from_connection_string(
    credential=credential,
    conn_str=os.environ["PROJECT_CONNECTION_STRING"] # Set in your .env
)

# --------------------------------------------------
# 1.1) Setup OpenTelemetry Tracing
# --------------------------------------------------
tracer = init_tracer(project_client)  # Initialize the store tracer

# Add diagnostic logging to check tracer status
from tracing import get_tracer_status, debug_tracer_connection
print(f"Tracer status: {get_tracer_status(tracer)}")
print(f"Tracer connection: {debug_tracer_connection(project_client)}")

# --------------------------------------------------
# 2) Setup the Bing Grounding Tool
# --------------------------------------------------
bing_tool = None
bing_connection_name = os.environ.get("BING_CONNECTION_NAME")
if bing_connection_name:
    try:
        with tracer.start_as_current_span("setup_bing_tool") as span:
            span.set_attribute("bing_connection_name", bing_connection_name)
            bing_connection = project_client.connections.get(connection_name=bing_connection_name)
            conn_id = bing_connection.id
            bing_tool = BingGroundingTool(connection_id=conn_id)
            print("bing > connected")
    except Exception as ex:
        print(f"bing > not connected: {ex}")

# --------------------------------------------------
# 3) Create/Update an Agent with Tools
# --------------------------------------------------
AGENT_NAME = "store-restock-agent" 

with tracer.start_as_current_span("setup_agent") as span:
    span.set_attribute("agent_name", AGENT_NAME)
    span.set_attribute("model", os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")) # Using gpt-4o as requested

    # Find existing agent
    found_agent = next(
        (a for a in project_client.agents.list_agents().data if a.name == AGENT_NAME),
        None
    )

    # --- Build toolset with STORE functions ---
    toolset = ToolSet()

    # Add Bing if connected
    if bing_tool:
        toolset.add(bing_tool)

    # Add our function tools for store management
    toolset.add(FunctionTool({
        check_item_stock,
        find_item_location,
        get_shelf_layout,
        request_item_from_storage,
        check_delivery_status,
        get_items_needing_restock,
        update_inventory_count,
        mark_item_restocked,
        log_damaged_item,
        get_store_layout_overview,
        identify_and_restock_item_from_image
    }))

    # --- Define the new instructions for the STORE agent ---
    instructions = """
    You are a helpful Store Management assistant for front-of-store staff focused on restocking. Follow these rules:

    1.  **Stock Checks:** If the user asks about stock levels, use `check_item_stock` with the item ID (SKU).
    2.  **Item Location:** If the user asks where an item goes, use `find_item_location` with the item ID.
    3.  **Shelf Layout:** If the user asks what's on a specific shelf (shelf unit), use `get_shelf_layout` with the shelf ID (e.g., "A1", "B2"). Display the visual layout provided in the response.
    4.  **Request from Storage:** If the user needs items brought from the back, use `request_item_from_storage`. You need the item ID, quantity, and target shelf ID.
    5.  **Delivery Status:** To check on a storage request, use `check_delivery_status` with the request ID.
    6.  **Low Stock:** To find items that need restocking, use `get_items_needing_restock`. You can filter by category or use the default minimum stock level.
    7.  **Manual Inventory Update:** If stock needs adjusting manually (e.g., cycle count), use `update_inventory_count`. Specify the item ID and the *change* in quantity (positive to add, negative to remove) and a reason.
    8.  **Marking Restock:** When an item has been placed on the shelf, use `mark_item_restocked`. You need item ID, shelf ID, shelf index (0-based), position index (0-based), and quantity added. This also updates inventory.
    9.  **Damaged Goods:** To report damaged items, use `log_damaged_item` with item ID and quantity. This removes stock. Provide notes if possible.
    10. **Store Overview:** For a list of all shelfs, use `get_store_layout_overview`.
    11. **Vision Simulation (Restock):** If the user wants to mark an item restocked using an 'image' (provide the item ID for simulation), use `identify_and_restock_item_from_image`. You need the item ID (as image_data) and quantity restocked.
    12. **Clarification:** If unsure about an item ID, shelf ID, or specific location, ask the user for clarification.
    13. **General Questions:** Use the Bing grounding tool for general knowledge questions not related to store tasks.
    14. **Be Clear:** Provide concise and clear responses, including results from function calls (like stock counts, locations, or confirmation messages). Extract key information from the JSON results.

    Print out markdown tables whenever you are asked to display a shelf.
    """

    agent_model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o") # Explicitly gpt-4o

    if found_agent:
        # Update existing
        span.set_attribute("agent_action", "update")
        agent = project_client.agents.update_agent(
            assistant_id=found_agent.id,
            model=agent_model, # Update model if needed
            name=AGENT_NAME,   # Ensure name is updated if it changed
            instructions=instructions,
            toolset=toolset
        )
    else:
        # Create new
        span.set_attribute("agent_action", "create")
        agent = project_client.agents.create_agent(
            model=agent_model, # Use gpt-4o
            name=AGENT_NAME,
            instructions=instructions,
            toolset=toolset
        )
    print(f"Agent '{agent.name}' (ID: {agent.id}) is ready using model '{agent.model}'.")


# --------------------------------------------------
# 4) Create a Thread for conversation
# --------------------------------------------------
with tracer.start_as_current_span("create_thread") as span:
    thread = project_client.agents.create_thread()
    span.set_attribute("thread_id", thread.id)
    print(f"Created new thread: {thread.id}")


# --------------------------------------------------
# 5) Build a Gradio interface
# --------------------------------------------------
azure_store_chat = create_chat_interface(project_client, agent, thread, tracer)

with gr.Blocks(title="Store Restocking Assistant") as demo:
    gr.Markdown("## Store Restocking Assistant")

    chatbot = gr.Chatbot(type="messages", label="Chat History", height=500)
    input_box = gr.Textbox(label="Ask the assistant (e.g., 'How many SKU001 are left?', 'Where does SKU002 go?', 'Show layout for A1')")

    def clear_history():
        with tracer.start_as_current_span("clear_chat_history") as span:
            global thread, azure_store_chat # Need to update the chat function's thread reference
            print(f"Clearing history. Old thread: {thread.id}")
            thread = project_client.agents.create_thread()
            azure_store_chat = create_chat_interface(project_client, agent, thread, tracer) # Recreate chat function with new thread
            span.set_attribute("new_thread_id", thread.id)
            print(f"New thread: {thread.id}")
            return []

    # Buttons
    with gr.Row():
        clear_button = gr.Button("Clear Chat History")

    # --- Example questions for STORE MANAGEMENT ---
    gr.Markdown("### Example Tasks")
    with gr.Row():
        q1 = gr.Button("Check stock for SKU001")
        q2 = gr.Button("Where does SKU003 go?")
        q3 = gr.Button("Show layout for shelf C3")
        q4 = gr.Button("Request 10 SKU004 for C3")
    with gr.Row():
        q5 = gr.Button("Which items are low on stock?")
        q6 = gr.Button("Mark 5 SKU002 restocked on A1, shelf 1, pos 2") # Note: Indices are 0-based in function call
        q7 = gr.Button("Log 1 damaged SKU005")
        q8 = gr.Button("'Scan' SKU001 and restock 5 units") # Simulates vision

    # Handle clearing chat
    clear_button.click(fn=clear_history, outputs=chatbot)

    # Helper function to set example question
    def set_example_question(question):
        with tracer.start_as_current_span("select_example_question") as span:
            # Reformat some examples to be more natural language for the LLM
            if "Check stock for" in question:
                 input_text = question
            elif "Where does" in question:
                 input_text = question
            elif "Show layout for shelf" in question:
                input_text = question
            elif "Request 10 SKU004" in question:
                input_text = "I need 10 units of SKU004 delivered to shelf C3."
            elif "Which items are low" in question:
                 input_text = question
            elif "Mark 5 SKU002" in question:
                 input_text = "I just put 5 units of SKU002 on shelf A1, shelf 1, position 2." # 0-based indices for function: shelf 0, pos 1
            elif "Log 1 damaged" in question:
                 input_text = "I found 1 damaged unit of SKU005."
            elif "'Scan' SKU001" in question:
                input_text = "I scanned SKU001 with my device, I restocked 5 units." # Simulates vision input
            else:
                input_text = question

            span.set_attribute("example_question_raw", question)
            span.set_attribute("example_question_formatted", input_text)
            return input_text

    # Wire example question buttons
    all_buttons = [q1, q2, q3, q4, q5, q6, q7, q8]
    for btn in all_buttons:
        # Use a lambda to capture the button's value correctly
        btn.click(lambda x=btn.value: set_example_question(x), inputs=[], outputs=input_box) \
           .then(lambda: [], outputs=chatbot) \
           .then(azure_store_chat, inputs=[input_box, chatbot], outputs=[chatbot, input_box], show_progress="full") \
           .then(lambda: "", outputs=input_box) # Clear input after sending

    # Submit the user input
    input_box.submit(azure_store_chat, inputs=[input_box, chatbot], outputs=[chatbot, input_box], show_progress="full") \
             .then(lambda: "", outputs=input_box) # Clear input after sending

# Modify the demo launch at the bottom of the file
if __name__ == "__main__":
    # Enable custom server name and port
    server_name = os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0")
    server_port = int(os.environ.get("GRADIO_SERVER_PORT", 7860))
    
    # Launch with share=True and debug mode
    demo.queue().launch(
        server_name=server_name,
        server_port=server_port,
        share=True,     # Enable sharing
        debug=True,     # Keep debug enabled
        show_error=True # Show detailed errors
    )