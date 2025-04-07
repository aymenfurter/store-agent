import os
from typing import Optional
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.projects.telemetry.agents import AIAgentsInstrumentor

# Constants for custom span attributes
STORE_ATTRIBUTES = {
    "store.action": "store.action",
    "store.item.id": "store.item.id",
    "store.item.name": "store.item.name",
    "store.shelf.id": "store.shelf.id",
    "store.quantity": "store.quantity",
    "store.inventory.change": "store.inventory.change",
    "store.request.id": "store.request.id",
    "store.status": "store.status",
    "store.error": "store.error"
}

class StoreTracer:
    def __init__(self, project_client=None):
        self.tracer = self._setup_tracing(project_client)

    def _setup_tracing(self, project_client):
        """Configure tracing with better error handling and fallback options."""
        try:
            # Try project client first
            if project_client:
                connection_string = project_client.telemetry.get_connection_string()
                if connection_string:
                    configure_azure_monitor(
                        connection_string=connection_string,
                        service_name="store-management-agent"
                    )
                    instrumentor = AIAgentsInstrumentor()
                    instrumentor.instrument(enable_content_recording=True)
                    return trace.get_tracer(__name__)

            # Fallback to environment variable
            connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
            if connection_string:
                configure_azure_monitor(
                    connection_string=connection_string,
                    service_name="store-management-agent"
                )
                return trace.get_tracer(__name__)

            print("WARNING: No valid connection string found for Azure Monitor")
            return trace.get_tracer(__name__)  # Returns no-op tracer

        except Exception as e:
            print(f"ERROR setting up tracing: {e}")
            return trace.get_tracer(__name__)  # Returns no-op tracer

    def start_as_current_span(self, name, **kwargs):
        """Forward start_as_current_span to internal tracer."""
        return self.tracer.start_as_current_span(name, **kwargs)

    def start_span(self, name, **kwargs):
        """Forward start_span to internal tracer."""
        return self.tracer.start_span(name, **kwargs)

    def get_current_span(self):
        """Forward get_current_span to trace module."""
        return trace.get_current_span()

    def inventory_operation(self, operation_type: str):
        """Create a span for inventory operations with relevant attributes."""
        return self.tracer.start_as_current_span(
            f"inventory.{operation_type}",
            attributes={
                SpanAttributes.OPERATION_NAME: f"inventory_{operation_type}",
                "store.operation.type": "inventory",
                "store.operation.action": operation_type
            }
        )

    def shelf_operation(self, operation_type: str):
        """Create a span for shelf operations."""
        return self.tracer.start_as_current_span(
            f"shelf.{operation_type}",
            attributes={
                SpanAttributes.OPERATION_NAME: f"shelf_{operation_type}",
                "store.operation.type": "shelf",
                "store.operation.action": operation_type
            }
        )

    def storage_operation(self, operation_type: str):
        """Create a span for storage/delivery operations."""
        return self.tracer.start_as_current_span(
            f"storage.{operation_type}",
            attributes={
                SpanAttributes.OPERATION_NAME: f"storage_{operation_type}",
                "store.operation.type": "storage",
                "store.operation.action": operation_type
            }
        )

    def record_inventory_change(self, span, item_id: str, quantity_change: int, 
                              reason: str, success: bool, error: Optional[str] = None):
        """Record inventory change details in span."""
        if not span or not hasattr(span, 'is_recording') or not span.is_recording():
            return

        span.set_attribute(STORE_ATTRIBUTES["store.item.id"], item_id)
        span.set_attribute(STORE_ATTRIBUTES["store.inventory.change"], quantity_change)
        span.set_attribute("store.change.reason", reason)
        
        if success:
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.ERROR))
            if error:
                span.set_attribute(STORE_ATTRIBUTES["store.error"], error)
                span.record_exception(Exception(error))

    def record_storage_request(self, span, request_id: str, item_id: str, 
                             quantity: int, target_location: str):
        """Record storage request details in span."""
        if not span or not hasattr(span, 'is_recording') or not span.is_recording():
            return

        span.set_attribute(STORE_ATTRIBUTES["store.request.id"], request_id)
        span.set_attribute(STORE_ATTRIBUTES["store.item.id"], item_id)
        span.set_attribute(STORE_ATTRIBUTES["store.quantity"], quantity)
        span.set_attribute(STORE_ATTRIBUTES["store.shelf.id"], target_location)
        span.add_event("storage_request_created", {
            "request_id": request_id,
            "timestamp": trace.get_current_span().get_span_context().trace_id
        })

    def record_shelf_update(self, span, shelf_id: str, shelf_index: int, 
                          position_index: int, item_id: str, success: bool):
        """Record shelf layout update details in span."""
        if not span or not hasattr(span, 'is_recording') or not span.is_recording():
            return

        span.set_attribute(STORE_ATTRIBUTES["store.shelf.id"], shelf_id)
        span.set_attribute("store.shelf.index", shelf_index)
        span.set_attribute("store.position.index", position_index)
        span.set_attribute(STORE_ATTRIBUTES["store.item.id"], item_id)
        
        if success:
            span.set_status(Status(StatusCode.OK))
            span.add_event("shelf_layout_updated", {
                "shelf_id": shelf_id,
                "position": f"S{shelf_index+1}-P{position_index+1}"
            })
        else:
            span.set_status(Status(StatusCode.ERROR))

# Create global tracer instance
store_tracer = None

def init_tracer(project_client=None):
    """Initialize the global store tracer."""
    global store_tracer
    store_tracer = StoreTracer(project_client)
    return store_tracer

def get_tracer() -> StoreTracer:
    """Get the global store tracer instance."""
    global store_tracer
    if store_tracer is None:
        store_tracer = StoreTracer()
    return store_tracer

def get_tracer_status(tracer) -> str:
    """Check the status of the tracer instance."""
    if not tracer:
        return "No tracer provided (None)"
    
    try:
        tracer_type = type(tracer).__name__
        # Check if it's our StoreTracer class
        if tracer_type == "StoreTracer":
            tracer_type = f"StoreTracer (internal={type(tracer.tracer).__name__})"
            
        provider_type = type(trace.get_tracer_provider()).__name__
        
        # Test creating a span
        with tracer.start_as_current_span("test_span") as span:
            recording = span and hasattr(span, "is_recording") and span.is_recording()
            recording_status = "recording" if recording else "not recording"
            
        return f"Tracer type: {tracer_type}, Provider: {provider_type}, Span: {recording_status}"
    except Exception as e:
        return f"Error checking tracer: {str(e)}"

def debug_tracer_connection(project_client) -> str:
    """Debug the tracer's connection settings."""
    try:
        # Check if telemetry is configured in project
        try:
            connection_string = project_client.telemetry.get_connection_string()
            telemetry_status = "Available" if connection_string else "Not available"
        except Exception as e:
            telemetry_status = f"Error: {str(e)}"
            
        # Check environment variable
        env_connection = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        env_status = "Available" if env_connection else "Not set"
        
        return f"Project telemetry: {telemetry_status}, Environment variable: {env_status}"
    except Exception as e:
        return f"Error debugging tracer: {str(e)}"