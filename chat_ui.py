import json
import time
from typing import List, Optional
import gradio as gr
from gradio import ChatMessage
from opentelemetry import trace

from azure.ai.projects.models import (
    AgentEventHandler,
    RunStep,
    RunStepDeltaChunk,
    ThreadMessage,
    ThreadRun,
    MessageDeltaChunk,
)

# Helper context manager for when no tracer is provided
class nullcontext:
    def __init__(self, enter_result=None):
        self.enter_result = enter_result
    def __enter__(self):
        return self.enter_result
    def __exit__(self, *excinfo):
        pass


class EventHandler(AgentEventHandler):
    def __init__(self, tracer=None):
        super().__init__()
        self._current_message_id = None
        self._accumulated_text = ""
        self._current_tools = {}
        self.conversation: Optional[List[ChatMessage]] = None # Use ChatMessage from gradio
        self.create_tool_bubble_fn = None
        self.tracer = tracer
        self.current_tool_calls = {} # Track active tool calls

    def on_message_delta(self, delta: MessageDeltaChunk) -> None:
        if delta.id != self._current_message_id:
            # Start a new message
            if self._current_message_id is not None:
                print() # Newline for previous assistant message completion in console
                # Add the completed message to the conversation history if it wasn't added already
                if self.conversation and self._accumulated_text and \
                   (not self.conversation or self.conversation[-1].content != self._accumulated_text):
                     # Check if the last message is already the accumulated text
                     is_duplicate = False
                     if self.conversation:
                         last_msg = self.conversation[-1]
                         if last_msg.role == "assistant" and last_msg.content == self._accumulated_text:
                            is_duplicate = True
                     if not is_duplicate:
                         print(f"\nDEBUG: Adding completed assistant message: {self._accumulated_text[:50]}...")
                         # self.conversation.append(ChatMessage(role="assistant", content=self._accumulated_text)) # Let on_thread_message handle final add

            self._current_message_id = delta.id
            self._accumulated_text = ""
            print("\nassistant> ", end="")

        partial_text = ""
        if delta.delta.content:
            for chunk in delta.delta.content:
                # Handle text content
                if hasattr(chunk, 'text') and chunk.text:
                     text_value = chunk.text.get("value", "")
                     partial_text += text_value
                     # Handle annotations (like citations) if needed - adapt from original if necessary
                     # ... citation handling logic here if Bing tool is used ...

        if partial_text:
            self._accumulated_text += partial_text
            print(partial_text, end="", flush=True)

            # Update Gradio UI progressively
            if self.conversation:
                 # Find or create the assistant message to update
                 assistant_msg_found = False
                 for msg in reversed(self.conversation):
                     if msg.role == "assistant" and not msg.metadata: # Update only pure text messages
                         msg.content = self._accumulated_text # Update existing message
                         assistant_msg_found = True
                         break
                 if not assistant_msg_found:
                      # Append new message if no suitable one exists or last one was a tool call
                      if not self.conversation or self.conversation[-1].role != "assistant" or self.conversation[-1].metadata:
                          self.conversation.append(ChatMessage(role="assistant", content=self._accumulated_text))


    def on_thread_message(self, message: ThreadMessage) -> None:
        # This is called when a message is fully created or updated
        print(f"\nDEBUG: on_thread_message - ID: {message.id}, Role: {message.role}, Status: {message.status}")
        if message.role == "assistant" and message.status == "completed":
            final_content = ""
            if message.content:
                 for content_part in message.content:
                     if hasattr(content_part, 'text') and content_part.text:
                         final_content += content_part.text.value
                         # Add annotation handling here if needed

            print(f"\nAssistant message completed (ID: {message.id}): {final_content[:100]}...")

            # Ensure the final message is correctly in the Gradio conversation
            if self.conversation:
                 # Check if the last message matches the final content
                 last_msg = self.conversation[-1] if self.conversation else None
                 if last_msg and last_msg.role == "assistant" and not last_msg.metadata:
                      if last_msg.content != final_content:
                           print(f"DEBUG: Updating last assistant message in Gradio history.")
                           last_msg.content = final_content # Update the content if it differs
                 elif final_content: # Only add if there's content
                      # Add if last message wasn't this one or was a tool call
                      if not last_msg or last_msg.role != "assistant" or last_msg.content != final_content:
                           print(f"DEBUG: Appending final assistant message to Gradio history.")
                           self.conversation.append(ChatMessage(role="assistant", content=final_content))

            self._current_message_id = None # Reset for the next message
            self._accumulated_text = ""     # Reset accumulated text


    def on_thread_run(self, run: ThreadRun) -> None:
        """Improved error handling for thread runs"""
        print(f"\nthread_run status > {run.status} (ID: {run.id})")
        
        if run.status == "failed":
            print(f"❌ ERROR > Run failed with ID: {run.id}")
            if run.last_error:
                error_msg = f"Error type: {run.last_error.code}, Message: {run.last_error.message}"
                print(f"❌ ERROR DETAILS > {error_msg}")
            else:
                print("❌ ERROR DETAILS > No specific error information available")
                
            # Log the required action if provided
            if hasattr(run, 'required_action') and run.required_action:
                print(f"⚠️ REQUIRED ACTION > {run.required_action}")
        
        elif run.status == "completed":
            print(f"✓ Run completed successfully (ID: {run.id})")
            
        # Add tracer attributes if available
        if self.tracer:
            try:
                span = trace.get_current_span()
                if span and hasattr(span, 'is_recording') and span.is_recording():
                    span.set_attribute("run_id", run.id)
                    span.set_attribute("run_status", run.status)
                    if run.status == "failed" and run.last_error:
                        span.set_attribute("error_code", run.last_error.code)
                        span.set_attribute("error", run.last_error.message)
            except Exception as ex:
                print(f"WARNING: Failed to record tracing for run: {ex}")


    def on_run_step_delta(self, delta: RunStepDeltaChunk) -> None:
        # This gives partial updates for steps, especially tool calls
        step_delta = delta.delta.step_details
        if step_delta and step_delta.type == "tool_calls":
            for tcall_delta in step_delta.tool_calls or []:
                call_id = tcall_delta.id
                if not call_id: continue # Should have an ID

                # Track function arguments as they stream in
                if tcall_delta.type == "function" and tcall_delta.function:
                    func_delta = tcall_delta.function
                    if call_id not in self.current_tool_calls:
                         # First time seeing this tool call delta
                         print(f"\nDEBUG: Tool call started: {func_delta.name} (ID: {call_id})")
                         self.current_tool_calls[call_id] = {"name": func_delta.name, "arguments": "", "status": "starting"}
                         # Create the initial tool bubble in UI
                         if self.create_tool_bubble_fn:
                              self.create_tool_bubble_fn(func_delta.name, "...", call_id, "pending") # Show pending state
                    # Append argument chunks
                    if func_delta.arguments:
                         self.current_tool_calls[call_id]["arguments"] += func_delta.arguments
                         # Optionally update the bubble content with arguments here if desired


    def on_run_step(self, step: RunStep) -> None:
        # This is called when a step (like a tool call) is completed or fails
        if self.tracer:
            span = trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute(f"step_{step.id}_type", step.type)
                span.set_attribute(f"step_{step.id}_status", step.status)

        if step.type == "tool_calls" and step.step_details and step.step_details.tool_calls:
            for tcall in step.step_details.tool_calls:
                call_id = tcall.id
                tool_info = self.current_tool_calls.get(call_id)
                func_name = tool_info["name"] if tool_info else "unknown_function"
                output = None

                if step.status == "completed":
                    print(f"Tool call completed: {func_name} (ID: {call_id})")
                    # Try to parse output
                    if tcall.type == "function" and hasattr(tcall, 'function') and tcall.function.output:
                        output_str = tcall.function.output
                        print(f"  Output: {output_str[:200]}{'...' if len(output_str) > 200 else ''}")
                        try:
                            output = json.loads(output_str)
                            # Special handling for shelf layout visualization
                            if func_name == "get_shelf_layout" and "layout_visual" in output:
                                message = output["layout_visual"] # Use the visual layout directly
                            elif "message" in output:
                                message = output["message"]
                            elif "error" in output:
                                message = f"Error: {output['error']}"
                            # Add more specific formatting for other functions if needed
                            elif func_name == "check_item_stock" and "stock" in output:
                                 message = f"{output['name']} (ID: {output['item_id']}): {output['stock']} units in stock."
                            elif func_name == "find_item_location" and "location_id" in output:
                                 message = f"{output['name']} (ID: {output['item_id']}) is located at Shelf {output['location_id']}, Position {output['position']}."
                            elif func_name == "get_items_needing_restock" and "count" in output:
                                 count = output['count']
                                 if count > 0:
                                     items_str = ", ".join([f"{i['name']} ({i['current_stock']})" for i in output['low_stock_items'][:3]]) # Show first few
                                     message = f"Found {count} low stock items. Examples: {items_str}{'...' if count > 3 else ''}."
                                 else:
                                     message = "No items found needing restock."
                            else:
                                message = f"Completed. Output: {output_str[:100]}{'...' if len(output_str) > 100 else ''}"

                        except json.JSONDecodeError:
                            message = f"Completed. Output (non-JSON): {output_str[:100]}{'...' if len(output_str) > 100 else ''}"
                            print(f"Warning: Could not parse JSON output for {func_name}: {output_str}")

                    elif tcall.type == "bing_grounding": # Example if Bing is used
                         message = "Finished searching web sources."
                    else:
                        message = "Tool call finished." # Fallback

                    # Update the tool bubble in UI to 'done'
                    if self.create_tool_bubble_fn:
                        self.create_tool_bubble_fn(func_name, message, call_id, "done")

                elif step.status == "failed":
                    error_message = f"Tool call failed: {func_name} (ID: {call_id})"
                    if step.last_error:
                         error_message += f" - Error: {step.last_error.message}"
                    print(error_message)
                    if self.tracer and span and span.is_recording():
                         span.set_attribute(f"step_{step.id}_error", error_message)
                    # Update the tool bubble in UI to 'error'
                    if self.create_tool_bubble_fn:
                        self.create_tool_bubble_fn(func_name, error_message, call_id, "error")

                # Clean up finished tool call
                if call_id in self.current_tool_calls:
                    del self.current_tool_calls[call_id]


def convert_dict_to_chatmessage(msg: dict) -> ChatMessage:
    # Converts history dict from Gradio back to ChatMessage if needed
    # This might not be strictly necessary if history is always List[ChatMessage]
    return ChatMessage(role=msg["role"], content=msg["content"], metadata=msg.get("metadata"))

def convert_chatmessage_to_dict(msg: ChatMessage) -> dict:
    """Converts a ChatMessage object to a dictionary for Gradio."""
    return {
        "role": msg.role,
        "content": msg.content,
        "metadata": msg.metadata if msg.metadata else {}
    }

def create_chat_interface(project_client, agent, thread, tracer=None):
    last_message_sent_time = 0 # Track last sent message to prevent duplicates

    # Helper function to create spans safely
    def create_span(name, parent_span=None):
        if not tracer:
            return nullcontext()
        
        try:
            # Try with parent if provided
            if parent_span:
                return tracer.start_as_current_span(name, parent=parent_span)
            else:
                return tracer.start_as_current_span(name)
        except TypeError:
            # If parent param causes error, try without it
            print("DEBUG: Tracer doesn't support parent parameter, using simpler span creation")
            return tracer.start_as_current_span(name)
        except Exception as e:
            print(f"WARNING: Could not create span: {e}")
            return nullcontext()

    def azure_store_chat(user_message: str, history: List[dict]):
        nonlocal last_message_sent_time
        current_time = time.time()

        # Prevent rapid double submission
        if current_time - last_message_sent_time < 2: # 2 seconds threshold
             print("WARN: Duplicate message submission detected, skipping.")
             # Return current history as is, clear input box
             yield history, ""
             return

        if not user_message.strip():
             print("WARN: Empty message received, skipping.")
             yield history, ""
             return

        last_message_sent_time = current_time

        # Convert Gradio's history (list of dicts) to list of ChatMessage objects
        conversation: List[ChatMessage] = [convert_dict_to_chatmessage(m) for m in history]

        print(f"\nUser message: {user_message}")
        # Add user message to the conversation list for UI update
        conversation.append(ChatMessage(role="user", content=user_message))
        yield [convert_chatmessage_to_dict(m) for m in conversation], ""  # Update UI immediately with user message

        chat_span = None
        if tracer:
            chat_span = tracer.start_span("store_chat_interaction")
            if chat_span and hasattr(chat_span, 'is_recording') and chat_span.is_recording():
                 chat_span.set_attribute("user_message", user_message)
                 chat_span.set_attribute("thread_id", thread.id)
                 chat_span.set_attribute("agent_id", agent.id)
                 chat_span.set_attribute("conversation_length_start", len(conversation))

        try:
            # Send user message to the thread
            try:
                project_client.agents.create_message(thread_id=thread.id, role="user", content=user_message)
                print(f"Message sent to thread {thread.id}")
            except Exception as msg_ex:
                print(f"❌ ERROR sending message: {msg_ex}")
                error_msg = ChatMessage(role="assistant", content=f"Error sending message: {str(msg_ex)}")
                conversation.append(error_msg)
                yield [convert_chatmessage_to_dict(m) for m in conversation], ""
                return

            # --- Define tool titles for UI ---
            tool_titles = {
                "check_item_stock": "🔍 Checking Stock",
                "find_item_location": "📍 Finding Location",
                "get_shelf_layout": "🗄️ Viewing Shelf Layout",
                "request_item_from_storage": "📦 Requesting from Storage",
                "check_delivery_status": "🚚 Checking Delivery",
                "get_items_needing_restock": "⚠️ Finding Low Stock",
                "update_inventory_count": "🔢 Updating Inventory",
                "mark_item_restocked": "✅ Marking Restocked",
                "log_damaged_item": "🚫 Logging Damage",
                "get_store_layout_overview": "🏪 Viewing Store Layout",
                "identify_and_restock_item_from_image": "📷 'Scanning' Item (Simulated)",
                "bing_grounding": "🔎 Searching Web Sources"
            }

            tool_icons_status = {
                 "pending": "⏳", 
                 "done": "✅", 
                 "error": "❌" 
            }

            # --- Function to create tool bubbles ---
            def create_tool_bubble(tool_name: str, content: str = "", call_id: str = None, status: str = "pending"):
                if tool_name is None:
                    return
                
                title_prefix = tool_titles.get(tool_name, f"屏ｸ{tool_name}") # Default icon + name
                status_icon = tool_icons_status.get(status, "")
                title = f"{status_icon} {title_prefix}"
                
                bubble_id = f"tool-{call_id}" if call_id else "tool-noid"

                # Check if bubble already exists
                existing_bubble = None
                for msg in reversed(conversation):
                     if msg.metadata and msg.metadata.get("id") == bubble_id:
                         existing_bubble = msg
                         break

                if existing_bubble:
                    # Update existing bubble
                    print(f"DEBUG: Updating tool bubble {bubble_id}: Status='{status}', Content='{content[:50]}...'")
                    existing_bubble.metadata["title"] = title
                    existing_bubble.metadata["status"] = status
                    existing_bubble.content = content
                else:
                    # Create new bubble
                    print(f"DEBUG: Creating tool bubble {bubble_id}: Status='{status}', Content='{content[:50]}...'")
                    msg = ChatMessage(
                        role="assistant",
                        content=content,
                        metadata={"title": title, "id": bubble_id, "status": status}
                    )
                    conversation.append(msg)
                
                return msg

            # Create a dictionary to track active tool calls
            active_tool_calls = {}

            # --- Still prepare event handler for compatibility ---
            event_handler = EventHandler(tracer)
            event_handler.conversation = conversation

            # --- Create streaming session with DIRECT event handling (key change) ---
            print(f"Starting agent stream for thread {thread.id}...")
            try:
                with project_client.agents.create_stream(
                    thread_id=thread.id,
                    assistant_id=agent.id,
                    event_handler=event_handler,
                ) as stream:
                    for item in stream:
                        try:
                            # Get event type and data directly
                            event_type, event_data, *_ = item
                            
                            # Process different event types directly
                            if event_type == "thread.run.step.delta":
                                # Handle tool call deltas (arguments being built)
                                step_delta = event_data.get("delta", {}).get("step_details", {})
                                if step_delta.get("type") == "tool_calls":
                                    for tcall in step_delta.get("tool_calls", []):
                                        call_id = tcall.get("id")
                                        
                                        # Function tool calls
                                        if tcall.get("type") == "function" and tcall.get("function"):
                                            func_name = tcall.get("function", {}).get("name")
                                            if func_name and call_id:
                                                if call_id not in active_tool_calls:
                                                    print(f"\nDEBUG: Tool call started: {func_name} (ID: {call_id})")
                                                    active_tool_calls[call_id] = {
                                                        "name": func_name,
                                                        "arguments": "",
                                                        "status": "pending"
                                                    }
                                                    # Create initial tool bubble
                                                    create_tool_bubble(func_name, "Running...", call_id, "pending")
                                                
                                                # Update arguments if any
                                                if "arguments" in tcall.get("function", {}):
                                                    active_tool_calls[call_id]["arguments"] += tcall["function"]["arguments"]
                                            
                                        # Bing search calls
                                        elif tcall.get("type") == "bing_grounding":
                                            search_query = tcall.get("bing_grounding", {}).get("requesturl", "")
                                            if "?q=" in search_query:
                                                query = search_query.split("?q=")[-1]
                                                create_tool_bubble("bing_grounding", f"Searching for '{query}'...", call_id, "pending")
                            
                            elif event_type == "run_step":
                                # Handle completed or failed tool calls
                                if event_data.get("type") == "tool_calls" and event_data.get("step_details", {}).get("tool_calls"):
                                    for tcall in event_data["step_details"]["tool_calls"]:
                                        call_id = tcall.get("id")
                                        tool_info = active_tool_calls.get(call_id, {})
                                        func_name = tool_info.get("name") or "unknown_function"
                                        
                                        if event_data["status"] == "completed":
                                            if tcall.get("type") == "function" and hasattr(tcall, 'function') and tcall.function.output:
                                                output_str = tcall.function.output
                                                print(f"Tool call completed: {func_name} (ID: {call_id})")
                                                print(f"  Output: {output_str[:200]}{'...' if len(output_str) > 200 else ''}")
                                                
                                                try:
                                                    output = json.loads(output_str)
                                                    # Format the output nicely based on tool type
                                                    if func_name == "get_shelf_layout" and "layout_visual" in output:
                                                        message = output["layout_visual"]
                                                    elif "message" in output:
                                                        message = output["message"]
                                                    elif "error" in output:
                                                        message = f"Error: {output['error']}"
                                                    else:
                                                        message = f"Completed. Output: {output_str[:100]}{'...' if len(output_str) > 100 else ''}"
                                                except json.JSONDecodeError:
                                                    message = f"Completed. Output (non-JSON): {output_str[:100]}{'...' if len(output_str) > 100 else ''}"
                                                
                                                # Update the tool bubble to show completion
                                                create_tool_bubble(func_name, message, call_id, "done")
                                                
                                                # Clean up the active tool call
                                                if call_id in active_tool_calls:
                                                    del active_tool_calls[call_id]
                                        
                                        elif event_data["status"] == "failed":
                                            error_message = f"Tool call failed: {func_name}"
                                            if "last_error" in event_data and event_data["last_error"]:
                                                error_message += f" - {event_data['last_error'].get('message', '')}"
                                            
                                            # Update the tool bubble to show failure
                                            create_tool_bubble(func_name, error_message, call_id, "error")
                                            
                                            # Clean up the active tool call
                                            if call_id in active_tool_calls:
                                                del active_tool_calls[call_id]
                            
                            elif event_type == "thread.message.delta":
                                # Handle assistant message deltas (text being generated)
                                content = ""
                                for chunk in event_data.get("delta", {}).get("content", []):
                                    if chunk.get("text", {}).get("value"):
                                        content += chunk["text"]["value"]
                                
                                if content:
                                    print(content, end="", flush=True)
                                    
                                    # If we don't have an assistant message or last message has metadata
                                    # (like a tool call), create a new message
                                    if not conversation or conversation[-1].role != "assistant" or conversation[-1].metadata:
                                        conversation.append(ChatMessage(role="assistant", content=content))
                                    else:
                                        # Append to the existing last assistant message
                                        conversation[-1].content += content
                            
                            elif event_type == "thread_run":
                                # Handle run status updates
                                status = event_data.get("status")
                                print(f"\nthread_run status > {status} (ID: {event_data.get('id')})")
                                
                                if status == "requires_action":
                                    print("⚠️ NOTE: Run requires action - this is normal for tool calls")
                                elif status == "failed":
                                    print(f"❌ ERROR > Run failed with ID: {event_data.get('id')}")
                                    if "last_error" in event_data and event_data["last_error"]:
                                        print(f"❌ ERROR DETAILS > {event_data['last_error']}")
                            
                            # After each event, yield the updated conversation
                            yield [convert_chatmessage_to_dict(m) for m in conversation], ""
                            
                        except Exception as stream_item_ex:
                            print(f"❌ ERROR processing stream item: {stream_item_ex}")
                            continue
                
                print("Agent stream finished successfully.")
            except Exception as stream_ex:
                print(f"❌ ERROR in stream: {stream_ex}")
                error_msg = ChatMessage(
                    role="assistant", 
                    content=f"An error occurred while processing your request: {str(stream_ex)}"
                )
                conversation.append(error_msg)
                
            # Final yield to ensure UI is up-to-date after stream closes
            yield [convert_chatmessage_to_dict(m) for m in conversation], ""

        except Exception as e:
            print(f"❌ CRITICAL ERROR in chat execution: {e}")
            # Add error message to chat
            error_msg = ChatMessage(
                role="assistant", 
                content=f"An error occurred: {str(e)}. Please try again or contact support if the issue persists."
            )
            conversation.append(error_msg)
            if chat_span and hasattr(chat_span, 'is_recording') and chat_span.is_recording():
                try:
                    chat_span.record_exception(e)
                    chat_span.set_status(trace.Status(trace.StatusCode.ERROR, description=str(e)))
                except Exception as trace_ex:
                    print(f"WARNING: Error recording exception in span: {trace_ex}")
            yield [convert_chatmessage_to_dict(m) for m in conversation], ""  # Update UI with error
        
        finally:
            if chat_span and hasattr(chat_span, 'end'):
                 if hasattr(chat_span, 'is_recording') and chat_span.is_recording():
                     chat_span.set_attribute("conversation_length_end", len(conversation))
                     # Make sure status is set (especially on success)
                     if hasattr(chat_span, 'status') and not chat_span.status.is_ok and chat_span.status.status_code != trace.StatusCode.ERROR:
                          chat_span.set_status(trace.Status(trace.StatusCode.OK))
                 chat_span.end()
                 print("Chat interaction span ended.")

    return azure_store_chat