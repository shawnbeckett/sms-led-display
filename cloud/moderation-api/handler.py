import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

# --- DynamoDB setup ---
DDB = boto3.resource("dynamodb")

# Messages table (incoming SMS). Falls back to a default name if the env var is missing.
MESSAGES_TABLE_NAME = os.environ.get("SMS_LED_MESSAGES_TABLE", "sms_led_messages")
MESSAGES_TABLE = DDB.Table(MESSAGES_TABLE_NAME)

# Settings table (global moderation config). Same env-var override pattern.
SETTINGS_TABLE_NAME = os.environ.get("SMS_LED_SETTINGS_TABLE", "sms_led_settings")
SETTINGS_TABLE = DDB.Table(SETTINGS_TABLE_NAME)


class DecimalEncoder(json.JSONEncoder):
    """
    Helper to JSON-encode DynamoDB Decimals (e.g. numeric attributes).
    """

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _response(status_code, body):
    """
    Wrap responses with JSON + CORS headers for the mobile moderator UI.
    """
    if not isinstance(body, (dict, list)):
        body = {"message": str(body)}

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def lambda_handler(event, context):
    """
    Entry point for API Gateway.

    Supports both:
      - REST API / proxy (v1): event["httpMethod"], event["path"]
      - HTTP API (v2): event["requestContext"]["http"]["method"], event["rawPath"]

    Implemented routes (for now):
      - GET /messages/pending
      - GET /settings
    """
    # Default values so we always have something to fall back to
    http_method = ""
    path = "/"

    # --- Detect REST API (v1) event shape ---
    if "httpMethod" in event:
        http_method = (event.get("httpMethod") or "").upper()
        path = event.get("path") or event.get("resource") or "/"

    # --- Detect HTTP API (v2) event shape ---
    elif "requestContext" in event and isinstance(event["requestContext"], dict):
        rc = event["requestContext"]
        http_info = rc.get("http") or {}
        http_method = (http_info.get("method") or "").upper()
        # HTTP API v2 uses rawPath; fall back to path if needed
        path = event.get("rawPath") or event.get("path") or "/"

    else:
        # Unknown event shape (unlikely unless misconfigured trigger)
        print("Unknown event shape:", event)
        return _response(400, {"error": "Bad request"})

    # Basic CORS preflight handling (OPTIONS)
    if http_method == "OPTIONS":
        return _response(200, {"message": "OK"})

    # Normalize path
    path = path.rstrip("/") or "/"

    # --- Routing ---
    if http_method == "GET" and path.endswith("/messages/pending"):
        return handle_get_pending_messages()

    if http_method == "GET" and path.endswith("/settings"):
        return handle_get_settings()

    # Fallback for unimplemented routes
    return _response(404, {"error": "Not Found", "path": path, "method": http_method})


def handle_get_pending_messages():
    """
    Return all messages with status='pending'.

    For MVP, this uses a Scan + FilterExpression.
    Later we can switch to a GSI on `status` if needed.
    """
    try:
        response = MESSAGES_TABLE.scan(
            FilterExpression=Attr("status").eq("pending")
        )
        items = response.get("Items", [])

        # Optional: sort by created_at if present (assumes ISO8601 string)
        items.sort(key=lambda x: x.get("created_at", ""))

        return _response(200, {"items": items})
    except Exception as e:
        # Log to CloudWatch in Lambda by printing
        print("Error in handle_get_pending_messages:", repr(e))
        return _response(500, {"error": "Internal server error"})


def handle_get_settings():
    """
    Return the global moderation settings.

    Looks up the item:
      - config_id = "global"
    in the sms_led_settings table.
    """
    try:
        resp = SETTINGS_TABLE.get_item(
            Key={"config_id": "global"}
        )
        item = resp.get("Item")

        if not item:
            # If the settings row is missing, surface a clear 404-style error
            return _response(404, {"error": "Settings not found", "config_id": "global"})

        return _response(200, item)
    except Exception as e:
        print("Error in handle_get_settings:", repr(e))
        return _response(500, {"error": "Internal server error"})
