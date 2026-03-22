"""AI Chat CDK Snippet — add to your product stack.

Adds DynamoDB conversations table and Bedrock permissions
to an existing Fargate task definition.

Usage:
    Merge these resources into your product's cdk/stack.py.
"""

# Add to your product stack's __init__:

# DynamoDB table for conversation history
conversations_table = dynamodb.Table(
    self,
    "Conversations",
    table_name=f"tokenburner-{product_name}-conversations",
    partition_key=dynamodb.Attribute(
        name="conversation_id",
        type=dynamodb.AttributeType.STRING,
    ),
    billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
    removal_policy=cdk.RemovalPolicy.DESTROY,
)

# S3 bucket for knowledge base / uploaded context
knowledge_bucket = s3.Bucket(
    self,
    "KnowledgeBase",
    bucket_name=f"tokenburner-{product_name}-knowledge",
    removal_policy=cdk.RemovalPolicy.DESTROY,
    auto_delete_objects=True,
)

# Grant Fargate task access
conversations_table.grant_read_write_data(task_def.task_role)
knowledge_bucket.grant_read_write(task_def.task_role)

# Add to container environment:
# "CONVERSATIONS_TABLE": conversations_table.table_name,
# "KNOWLEDGE_BUCKET": knowledge_bucket.bucket_name,
# "BEDROCK_MODEL": "your-model-id",
