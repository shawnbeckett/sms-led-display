# sms-led-display
Raspberry Pi SMS-to-LED display that ingests SMS via Twilio, moderates messages, and renders approved content on an LED matrix.

## Deploying the Moderator UI (S3)
The Moderator UI is a static single-page app hosted from the `sms-led-moderator-ui` S3 bucket. Only the contents of `/web/moderator_ui` should ever be deployed (never your home directory or the repo root).

### Deploying the Moderator UI
1. Make changes to:
   - `web/moderator_ui/index.html`
   - `web/moderator_ui/app.js`
   - `web/moderator_ui/style.css`
2. In a terminal on the Mac, change into the UI folder:
   ```bash
   cd ~/PythonProjects/sms-led-display/web/moderator_ui
   ```
3. Deploy the updated UI to S3:
   ```bash
   aws s3 sync . s3://sms-led-moderator-ui --delete
   ```
4. Visit the S3 static website URL (or CloudFront URL, if configured) in a browser and refresh to confirm that the changes are live.

**Warning:** Run `aws s3 sync` only from inside `web/moderator_ui`; running it elsewhere can upload sensitive files (SSH keys, wallets, dotfiles, virtualenvs).

## Deploying Lambda Functions
There are two Lambda functions in this project, both deployed by zipping the contents of their `cloud/` subdirectories and calling `aws lambda update-function-code`:
- `twilio_sms_ingest`
- `sms-led-moderation-api`

### Deploying `twilio_sms_ingest`
1. Navigate to the Twilio webhook Lambda folder:
   ```bash
   cd ~/PythonProjects/sms-led-display/cloud/twilio_webhook
   ```
2. Create the deployment ZIP:
   ```bash
   zip -r ../twilio_sms_ingest.zip .
   ```
3. Update the Lambda code in AWS:
   ```bash
   aws lambda update-function-code \
     --function-name twilio_sms_ingest \
     --zip-file fileb://../twilio_sms_ingest.zip
   ```

### Deploying `sms-led-moderation-api`
1. Navigate to the moderation API folder:
   ```bash
   cd ~/PythonProjects/sms-led-display/cloud/moderation_api
   ```
2. Create the deployment ZIP:
   ```bash
   zip -r ../moderation_api.zip .
   ```
3. Update the Lambda code in AWS:
   ```bash
   aws lambda update-function-code \
     --function-name sms-led-moderation-api \
     --zip-file fileb://../moderation_api.zip
   ```

**Caution:** Run `zip -r` only from inside each Lambda directory to avoid bundling unintended files from higher-level paths.

## Pi Deployment Workflow

Remotes:

- `origin` → GitHub
- `pi` → `pi@sms-led.local:/home/pi/sms-led-display.git`

Typical flow:

1. Make code changes locally.
2. Stage and commit:

   ```bash
   git add ...
   git commit -m "message"
   ```
3. Push to GitHub:

   ```bash
   git push origin main
   ```
4. Deploy to the Pi:

   ```bash
   git push pi main
   ```

What happens on `git push pi main`:

- The Pi’s post-receive hook checks out `main` into `/home/pi/sms-led-display`.
- If `pi/renderer/requirements.txt` exists, it installs/updates deps via `/home/pi/virtualenvs/led-matrix-env/bin/python3 -m pip install -r requirements.txt`.
- It restarts `smsled-startup.service`.

Viewing logs from the Mac:

- Service logs:

  ```bash
  ssh pi@sms-led.local 'journalctl -u smsled-startup.service -n 50 --no-pager'
  ```
- Deploy log:

  ```bash
  ssh pi@sms-led.local 'tail -n 100 /home/pi/sms-led-deploy.log'
  ```

Force a redeploy when `main` hasn’t changed:

```bash
git commit --allow-empty -m "Force redeploy to Pi"
git push pi main
```

Alternative manual restart (bypasses Git):

```bash
ssh pi@sms-led.local 'sudo systemctl restart smsled-startup.service'
```

## DynamoDB Tables
- `sms_led_messages` (partition key `pk`, string): stores incoming SMS messages, their status (PENDING, APPROVED, REJECTED, LIVE, PLAYED, etc.), metadata such as timestamps and from-number, and any rejection reasons.
- `sms_led_settings` (partition key `config_id`, string): stores global configuration for the display and moderation, typically using a `config_id` like `"global"` for the active config.

Both Lambdas read/write these tables, which must exist in the same region as the Lambdas (us-east-1).

## API Gateway Endpoints
Base URL:
```text
https://bq6tluiuu3.execute-api.us-east-1.amazonaws.com
```
This base URL fronts `sms-led-moderation-api` for most endpoints and `twilio_sms_ingest` for the Twilio webhook.

Key routes (relative to the base URL):
- `GET /messages/approved` – `sms-led-moderation-api`
- `GET /messages/pending` – `sms-led-moderation-api`
- `GET /messages/live` – `sms-led-moderation-api`
- `POST /messages/reject` – `sms-led-moderation-api`
- `POST /messages/approve` – `sms-led-moderation-api`
- `POST /messages/played` – `sms-led-moderation-api`
- `GET /settings` – `sms-led-moderation-api`
- `POST /settings` – `sms-led-moderation-api`
- `POST /twilio-sms` – `twilio_sms_ingest` (Twilio inbound webhook)

The Moderator UI calls the messages and settings endpoints from the browser, and the Pi renderer polls the appropriate endpoints to fetch approved/live messages.

## Twilio Configuration
Twilio is configured to POST incoming SMS messages to the API Gateway `/twilio-sms` endpoint, which invokes the `twilio_sms_ingest` Lambda.

- Twilio phone number: 647-930-4995
- Webhook URL shape:
  ```text
  https://bq6tluiuu3.execute-api.us-east-1.amazonaws.com/twilio-sms
  ```

Setup checklist:
1. In the Twilio Console, open the configuration for the number 647-930-4995.
2. Under Messaging settings, set the “A MESSAGE COMES IN” webhook URL to the `/twilio-sms` API Gateway URL.
3. Ensure the method is HTTP POST.
4. Save the configuration.

`twilio_sms_ingest` normalizes and stores incoming messages in `sms_led_messages` with an initial status (e.g., PENDING), which are then surfaced in the Moderator UI.

## Local Development Environment (Mac)
1. Clone the repo into:
   ```bash
   ~/PythonProjects/sms-led-display
   ```
2. Ensure Python 3 is installed.
3. Optional: create a local virtualenv in the repo:
   ```bash
   cd ~/PythonProjects/sms-led-display
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r cloud/moderation_api/requirements.txt
   ```
4. Run a local HTTP server for quick UI testing:
   ```bash
   cd ~/PythonProjects/sms-led-display/web/moderator_ui
   python3 -m http.server 8080
   ```

Production deployment still uses S3 and Lambda as described above.

## IAM & Permissions Overview
- Lambda execution roles must read/write `sms_led_messages` and `sms_led_settings` in DynamoDB and write logs to CloudWatch.
- The `sms-led-moderator-ui` S3 bucket must be configured for static website hosting and public read access (directly or via CloudFront with an origin access control).
- API Gateway must invoke `sms-led-moderation-api` and `twilio_sms_ingest` Lambdas.

## Deployment Safety Notes
- Always verify your current directory with `pwd` before running `aws s3 sync` or `zip -r ../...`.
- Never run `aws s3 sync` from your home directory (e.g., `/Users/yourname`) or any location containing `.ssh`, wallet files, `.Trash`, `.venv`, or other sensitive data.
- If sensitive files are ever accidentally uploaded to S3: immediately empty the bucket, rotate exposed credentials or SSH keys, and move any exposed wallet contents to a new wallet.
