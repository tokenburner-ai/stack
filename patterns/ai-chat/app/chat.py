"""AI Chat Pattern — Bedrock + SSE streaming.

Drop this into your Flask app to add an AI chat endpoint.
Streams responses via Server-Sent Events using Bedrock's
converse_stream API.

Usage:
    from chat import chat_bp
    app.register_blueprint(chat_bp)

Then POST to /api/chat with {"message": "...", "conversation_id": "..."}
"""

import json
import os
import uuid

import boto3
from flask import Blueprint, Response, request, jsonify, stream_with_context

chat_bp = Blueprint("chat", __name__)

_bedrock = None
_dynamodb = None

MODEL_ID = os.environ.get("BEDROCK_MODEL", "your-model-id")
CONVERSATIONS_TABLE = os.environ.get("CONVERSATIONS_TABLE", "tokenburner-conversations")
MAX_HISTORY = 20  # keep last N messages per conversation


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
        )
    return _bedrock


def _get_dynamo_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
        )
    return _dynamodb.Table(CONVERSATIONS_TABLE)


def _load_history(conversation_id: str) -> list[dict]:
    """Load conversation history from DynamoDB."""
    table = _get_dynamo_table()
    try:
        resp = table.get_item(Key={"conversation_id": conversation_id})
        item = resp.get("Item", {})
        return item.get("messages", [])
    except Exception:
        return []


def _save_history(conversation_id: str, messages: list[dict]):
    """Save conversation history to DynamoDB."""
    table = _get_dynamo_table()
    table.put_item(Item={
        "conversation_id": conversation_id,
        "messages": messages[-MAX_HISTORY:],
    })


@chat_bp.route("/api/chat", methods=["POST"])
def chat():
    """Stream an AI response via SSE."""
    data = request.get_json()
    if not data or not data.get("message"):
        return jsonify({"error": "message required"}), 400

    user_message = data["message"]
    conversation_id = data.get("conversation_id") or str(uuid.uuid4())
    system_prompt = data.get("system_prompt", "You are a helpful assistant.")

    # Load history and append user message
    history = _load_history(conversation_id)
    history.append({"role": "user", "content": [{"text": user_message}]})

    def generate():
        yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"

        try:
            response = _get_bedrock().converse_stream(
                modelId=MODEL_ID,
                messages=history[-MAX_HISTORY:],
                system=[{"text": system_prompt}],
                inferenceConfig={"maxTokens": 4096, "temperature": 0.7},
            )

            assistant_text = ""
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        chunk = delta["text"]
                        assistant_text += chunk
                        yield f"data: {json.dumps({'text': chunk})}\n\n"

            # Save updated history
            history.append({"role": "assistant", "content": [{"text": assistant_text}]})
            _save_history(conversation_id, history)

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@chat_bp.route("/api/chat/history/<conversation_id>", methods=["GET"])
def get_history(conversation_id):
    """Retrieve conversation history."""
    messages = _load_history(conversation_id)
    return jsonify({"conversation_id": conversation_id, "messages": messages})
