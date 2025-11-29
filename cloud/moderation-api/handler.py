import json
import os
import base64
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

# List of settings the moderator UI is allowed to change.
ALLOWED_SETTINGS_FIELDS = {
    "moderation_mode",
    "profanity_mode",
    "max_message_length",
    "hard_banned_words",
    "soft_banned_words",
}

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
    elif http_method == "GET" and path.endswith("/settings"):
        return handle_get_settings()
    elif http_method == "POST" and path.endswith("/settings"):
        return handle_post_settings(event)
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


def handle_post_settings(event):
    """
    Update the global moderation settings row (config_id='global').

    Accepts a JSON body with any subset of:
      - moderation_mode
      - profanity_mode
      - max_message_length
      - hard_banned_words
      - soft_banned_words

    Only provided fields are updated (partial update).
    Returns the full updated settings item.
    """
    # --- Parse request body (JSON) ---
    raw_body = event.get("body") or ""

    # Handle possible base64-encoding from API Gateway
    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except Exception as e:
            print("Error decoding base64 body:", repr(e))
            return _response(400, {"error": "Invalid base64-encoded body"})

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Body must be a JSON object"})

    # --- Filter and validate field names ---
    update_fields = {}
    for key, value in body.items():
        if key not in ALLOWED_SETTINGS_FIELDS:
            # Unknown field -> reject the request clearly
            return _response(400, {"error": f"Unknown field: {key}"})
        update_fields[key] = value

    if not update_fields:
        return _response(400, {"error": "No valid fields provided to update"})

    # --- Basic type checks / normalization ---
    if "max_message_length" in update_fields:
        try:
            update_fields["max_message_length"] = int(update_fields["max_message_length"])
        except (TypeError, ValueError):
            return _response(400, {"error": "max_message_length must be an integer"})

    if "hard_banned_words" in update_fields:
        if not isinstance(update_fields["hard_banned_words"], list):
            return _response(400, {"error": "hard_banned_words must be a list of strings"})

    if "soft_banned_words" in update_fields:
        if not isinstance(update_fields["soft_banned_words"], list):
            return _response(400, {"error": "soft_banned_words must be a list of strings"})

    # --- Build DynamoDB UpdateExpression from provided fields ---
    update_expr_parts = []
    expr_attr_values = {}

    for key, value in update_fields.items():
        update_expr_parts.append(f"{key} = :{key}")
        expr_attr_values[f":{key}"] = value

    update_expr = "SET " + ", ".join(update_expr_parts)

    # --- Perform the update on config_id='global' ---
    try:
        result = SETTINGS_TABLE.update_item(
            Key={"config_id": "global"},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
        updated_item = result.get("Attributes", {})
        return _response(200, updated_item)
    except Exception as e:
        print("Error in handle_post_settings:", repr(e))
        return _response(500, {"error": "Internal server error"})
