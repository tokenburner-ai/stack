# Set Up Cost & Usage Alerts

Free billing and usage monitoring for your tokenburner deployment. Uses AWS Budgets (2 free) and CloudWatch Alarms (10 free) — no additional cost.

## Prerequisites
- Deployed stack (`tokenburner deploy` completed)
- AWS CLI configured with your profile
- An email address for notifications

## Step 1: Budget Alarms (2 free)

AWS Budgets emails you when spending exceeds thresholds or is forecasted to.

### Create a monthly budget with alerts

Replace `ACCOUNT_ID`, `PROFILE`, and `EMAIL` with your values:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
PROFILE=your-profile
EMAIL=your-email@example.com

# Early warning: $10/mo
aws budgets create-budget --account-id $ACCOUNT_ID --budget '{
  "BudgetName": "tokenburner-monthly-10",
  "BudgetType": "COST",
  "BudgetLimit": {"Amount": "10", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "CostTypes": {"IncludeTax": true, "IncludeSubscription": true, "UseBlended": true, "IncludeRefund": false, "IncludeCredit": false}
}' --notifications-with-subscribers "[
  {\"Notification\": {\"NotificationType\": \"ACTUAL\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 50, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]},
  {\"Notification\": {\"NotificationType\": \"ACTUAL\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 100, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]},
  {\"Notification\": {\"NotificationType\": \"FORECASTED\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 100, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]}
]"

# Emergency: $50/mo
aws budgets create-budget --account-id $ACCOUNT_ID --budget '{
  "BudgetName": "tokenburner-emergency-50",
  "BudgetType": "COST",
  "BudgetLimit": {"Amount": "50", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "CostTypes": {"IncludeTax": true, "IncludeSubscription": true, "UseBlended": true, "IncludeRefund": false, "IncludeCredit": false}
}' --notifications-with-subscribers "[
  {\"Notification\": {\"NotificationType\": \"ACTUAL\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 50, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]},
  {\"Notification\": {\"NotificationType\": \"ACTUAL\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 100, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]},
  {\"Notification\": {\"NotificationType\": \"FORECASTED\", \"ComparisonOperator\": \"GREATER_THAN\", \"Threshold\": 100, \"ThresholdType\": \"PERCENTAGE\"}, \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$EMAIL\"}]}
]"
```

This gives you:
- Email at $5 and $10 actual spend (early warning)
- Email at $25 and $50 actual spend (emergency)
- Email if AWS *forecasts* you'll exceed either threshold

## Step 2: Usage Spike Alarms (up to 10 free)

CloudWatch alarms monitor Lambda invocations and errors.

### Create an SNS topic for notifications

```bash
TOPIC_ARN=$(aws sns create-topic --name tokenburner-alerts --query TopicArn --output text)
aws sns subscribe --topic-arn $TOPIC_ARN --protocol email --notification-endpoint $EMAIL
```

**Important:** Check your email and click the confirmation link or alarms won't notify you.

### Create alarms for your Lambda function

Replace `FUNCTION_NAME` with your Lambda function name (from `tokenburner status`):

```bash
FUNCTION_NAME=tokenburner-my-product

# Invocation spike: >10,000 in 24 hours
aws cloudwatch put-metric-alarm \
  --alarm-name "${FUNCTION_NAME}-invocation-spike" \
  --alarm-description "Alert if ${FUNCTION_NAME} exceeds 10,000 invocations in 24 hours" \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \
  --statistic Sum --period 86400 --evaluation-periods 1 \
  --threshold 10000 --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN" --treat-missing-data notBreaching

# Error spike: >50 errors in 1 hour
aws cloudwatch put-metric-alarm \
  --alarm-name "${FUNCTION_NAME}-errors" \
  --alarm-description "Alert if ${FUNCTION_NAME} has more than 50 errors in 1 hour" \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \
  --statistic Sum --period 3600 --evaluation-periods 1 \
  --threshold 50 --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN" --treat-missing-data notBreaching
```

## Step 3: Verify

### Check budgets
```bash
aws budgets describe-budgets --account-id $ACCOUNT_ID --output json | python3 -c "
import json, sys
for b in json.load(sys.stdin)['Budgets']:
    actual = float(b['CalculatedSpend']['ActualSpend']['Amount'])
    print(f\"{b['BudgetName']}: \${b['BudgetLimit']['Amount']}/mo limit, \${actual:.2f} actual\")
"
```

### Check alarms
```bash
aws cloudwatch describe-alarms --output json | python3 -c "
import json, sys
alarms = json.load(sys.stdin)['MetricAlarms']
print(f'{len(alarms)} of 10 free alarms used')
for a in sorted(alarms, key=lambda x: x['AlarmName']):
    print(f\"  {a['AlarmName']:<40} {a['StateValue']}\")
"
```

### Check current month's costs
```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json | python3 -c "
import json, sys
groups = json.load(sys.stdin)['ResultsByTime'][0]['Groups']
groups.sort(key=lambda g: float(g['Metrics']['BlendedCost']['Amount']), reverse=True)
total = 0
for g in groups:
    cost = float(g['Metrics']['BlendedCost']['Amount'])
    if cost > 0.001:
        print(f\"  {g['Keys'][0]:<45} \${cost:.2f}\")
        total += cost
print(f\"  {'TOTAL':<45} \${total:.2f}\")
"
```

## What it catches

| Alarm | Trigger | Scenario |
|-------|---------|----------|
| Budget $10 | Spend > $5 or $10 | Left a test resource running |
| Budget $50 | Spend > $25 or $50 | Accidentally deployed full stack mode |
| Invocation spike | >10K requests/day | Bot attack, DDoS, runaway crawler |
| Error spike | >50 errors/hour | Broken deploy, DB connection issues |
| Forecast alerts | Projected overspend | Slow cost creep before it hits you |

## Managing Alerts

### Update a budget limit
```bash
aws budgets update-budget --account-id $ACCOUNT_ID --new-budget '{
  "BudgetName": "tokenburner-monthly-10",
  "BudgetType": "COST",
  "BudgetLimit": {"Amount": "20", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "CostTypes": {"IncludeTax": true, "IncludeSubscription": true, "UseBlended": true, "IncludeRefund": false, "IncludeCredit": false}
}'
```

### Delete a budget
```bash
aws budgets delete-budget --account-id $ACCOUNT_ID --budget-name "tokenburner-monthly-10"
```

### Delete a CloudWatch alarm
```bash
aws cloudwatch delete-alarms --alarm-names "tokenburner-my-product-invocation-spike"
```

## Cost of monitoring itself

| Resource | Free tier | Over limit |
|----------|-----------|------------|
| AWS Budgets | 2 budgets free | $0.02/day each additional |
| CloudWatch Alarms | 10 alarms free | $0.10/alarm/mo |
| SNS email | Free | Free |
| **Total** | **$0.00/mo** | |
