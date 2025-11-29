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

# Message status values used in sms_led_messages
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CLEARED = "cleared"  # for future clear-screen behavior

# The primary key used in the sms_led_messages DynamoDB table.
# Twilio ingestion Lambda writes each incoming SMS using "pk" as the
# partition key, normally storing the Twilio message SID (e.g., "SMxxxx").
# This Lambda must use the same key name so UpdateItem/Query work correctly.
MESSAGES_PARTITION_KEY = "pk"

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

    Implemented routes:
      - GET /messages/pending
      - GET /settings
      - POST /settings
      - POST /messages/approve
      - POST /messages/reject
    """
    # Default values
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
        path = event.get("rawPath") or event.get("path") or "/"

    else:
        print("Unknown event shape:", event)
        return _response(400, {"error": "Bad request"})

    # Basic CORS preflight handling
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
    
    elif http_method == "POST" and path.endswith("/messages/approve"):
        return handle_post_message_approve(event)
    
    elif http_method == "POST" and path.endswith("/messages/reject"):
        return handle_post_message_reject(event)

    return _response(404, {"error": "Not Found", "path": path, "method": http_method})


def handle_get_pending_messages():
    """
    Return all messages with status='pending'.
    """
    try:
        response = MESSAGES_TABLE.scan(
            FilterExpression=Attr("status").eq("pending")
        )
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("created_at", ""))
        return _response(200, {"items": items})
    except Exception as e:
        print("Error in handle_get_pending_messages:", repr(e))
        return _response(500, {"error": "Internal server error"})


def handle_get_settings():
    """
    Return the global moderation settings (config_id='global').
    """
    try:
        resp = SETTINGS_TABLE.get_item(Key={"config_id": "global"})
        item = resp.get("Item")

        if not item:
            return _response(404, {"error": "Settings not found", "config_id": "global"})

        return _response(200, item)
    except Exception as e:
        print("Error in handle_get_settings:", repr(e))
        return _response(500, {"error": "Internal server error"})


def handle_post_settings(event):
    """
    Update the global moderation settings row.
    """
    raw_body = event.get("body") or ""

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

    update_fields = {}
    for key, value in body.items():
        if key not in ALLOWED_SETTINGS_FIELDS:
            return _response(400, {"error": f"Unknown field: {key}"})
        update_fields[key] = value

    if not update_fields:
        return _response(400, {"error": "No valid fields provided to update"})

    if "max_message_length" in update_fields:
        try:
            update_fields["max_message_length"] = int(update_fields["max_message_length"])
        except Exception:
            return _response(400, {"error": "max_message_length must be an integer"})

    if "hard_banned_words" in update_fields and not isinstance(update_fields["hard_banned_words"], list):
        return _response(400, {"error": "hard_banned_words must be a list"})

    if "soft_banned_words" in update_fields and not isinstance(update_fields["soft_banned_words"], list):
        return _response(400, {"error": "soft_banned_words must be a list"})

    update_expr = "SET " + ", ".join(f"{k} = :{k}" for k in update_fields)
    expr_attr_values = {f":{k}": v for k, v in update_fields.items()}

    try:
        result = SETTINGS_TABLE.update_item(
            Key={"config_id": "global"},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
        return _response(200, result.get("Attributes", {}))
    except Exception as e:
        print("Error in handle_post_settings:", repr(e))
        return _response(500, {"error": "Internal server error"})


def handle_post_message_approve(event):
    """
    Approve a single message by ID.
    """
    raw_body = event.get("body") or ""

    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except Exception as e:
            print("Error decoding base64 body in approve:", repr(e))
            return _response(400, {"error": "Invalid base64-encoded body"})

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Body must be a JSON object"})

    message_id = body.get("message_id")
    if not message_id or not isinstance(message_id, str):
        return _response(400, {"error": "message_id (string) is required"})

    try:
        result = MESSAGES_TABLE.update_item(
            Key={MESSAGES_PARTITION_KEY: message_id},
            UpdateExpression="SET #s = :approved",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":approved": STATUS_APPROVED},
            ReturnValues="ALL_NEW",
        )
        updated_item = result.get("Attributes")

        if not updated_item:
            return _response(404, {"error": "Message not found", "message_id": message_id})

        return _response(200, {"item": updated_item})
    except Exception as e:
        print("Error in handle_post_message_approve:", repr(e))
        return _response(500, {"error": "Internal server error"})
    
def handle_post_message_reject(event):
    """
    Reject a single message by ID.

    Request body (JSON):
      { "message_id": "..." }

    Sets status = "rejected" on the pk.
    Returns the updated item.
    """
    # --- Parse body ---
    raw_body = event.get("body") or ""

    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except Exception as e:
            print("Error decoding base64 body in reject:", repr(e))
            return _response(400, {"error": "Invalid base64-encoded body"})

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Body must be a JSON object"})

    message_id = body.get("message_id")
    if not message_id or not isinstance(message_id, str):
        return _response(400, {"error": "message_id (string) is required"})

    # --- Perform reject update ---
    try:
        result = MESSAGES_TABLE.update_item(
            Key={MESSAGES_PARTITION_KEY: message_id},
            UpdateExpression="SET #s = :rejected",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":rejected": STATUS_REJECTED},
            ReturnValues="ALL_NEW",
        )
        updated_item = result.get("Attributes")

        if not updated_item:
            return _response(404, {"error": "Message not found", "message_id": message_id})

        return _response(200, {"item": updated_item})

    except Exception as e:
        print("Error in handle_post_message_reject:", repr(e))
        return _response(500, {"error": "Internal server error"})

