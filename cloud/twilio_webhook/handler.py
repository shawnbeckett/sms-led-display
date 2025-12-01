import os
import json
import uuid
import urllib.parse
import datetime
import base64  # NEW: for decoding base64-encoded request body

import boto3

# ------------------------------------------------------------
# DynamoDB client setup
# ------------------------------------------------------------
dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("TABLE_NAME", "sms_led_messages")
table = dynamodb.Table(TABLE_NAME)


def handler(event, context):
    """
    Lambda handler for Twilio SMS webhook events.

    Flow:
        1. API Gateway receives HTTP POST from Twilio and passes an 'event' to Lambda.
        2. Twilio sends SMS data in x-www-form-urlencoded format inside event["body"].
           API Gateway may base64-encode this body and set isBase64Encoded=True.
        3. We decode the body if needed, then parse the form data.
        4. We extract From, To, Body, MessageSid, etc.
        5. We write a 'pending' record into DynamoDB.
        6. We return HTTP 200 "OK" so Twilio is happy.
    """

    # ------------------------------------------------------------
    # 1. Extract raw body (and decode base64 if necessary)
    # ------------------------------------------------------------
    # For HTTP APIs, event usually looks like:
    #   {"body": "...", "isBase64Encoded": true/false, ...}
    raw_body = event.get("body", "") or ""
    is_base64 = event.get("isBase64Encoded", False)

    if is_base64 and raw_body:
        # Decode from base64 → bytes → UTF-8 string
        raw_body_bytes = base64.b64decode(raw_body)
        raw_body = raw_body_bytes.decode("utf-8")

    # Log the raw body for debugging
    print("Raw request body:", raw_body)

    # ------------------------------------------------------------
    # 2. Parse form-encoded Twilio payload into a dict
    # ------------------------------------------------------------
    # raw_body should now look like:
    #   "From=%2B1647...&To=%2B1647...&Body=Hello+World&MessageSid=SM123..."
    parsed = urllib.parse.parse_qs(raw_body)

    # Convert parse_qs output {k: [v]} → {k: v}
    data = {k: v[0] for k, v in parsed.items()}

    # Extra logging so we can see what Twilio actually sent
    print("Parsed Twilio payload:", json.dumps(data))

    # ------------------------------------------------------------
    # 3. Extract SMS values from Twilio payload
    # ------------------------------------------------------------
    from_number = data.get("From", "")
    to_number = data.get("To", "")
    body = data.get("Body", "")

    # Twilio's unique message ID
    twilio_sid = data.get("MessageSid") or data.get("SmsSid") or str(uuid.uuid4())
    pk = twilio_sid  # use this as DynamoDB partition key

    # ------------------------------------------------------------
    # 4. Generate timestamp
    # ------------------------------------------------------------
    created_at = (
        datetime.datetime.utcnow()
        .replace(microsecond=0)
        .isoformat() + "Z"
    )

    # ------------------------------------------------------------
    # 5. Build DynamoDB item
    # ------------------------------------------------------------
    item = {
        "pk": pk,
        "from_number": from_number,
        "to_number": to_number,
        "body": body,
        "twilio_message_sid": twilio_sid,
        "created_at": created_at,
        "status": "pending",
    }

    print("Writing item to DynamoDB:", json.dumps(item))

    # ------------------------------------------------------------
    # 6. Write item
    # ------------------------------------------------------------
    table.put_item(Item=item)

    # ------------------------------------------------------------
    # 7. Return 200 OK to Twilio
    # ------------------------------------------------------------
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": "OK",
    }
