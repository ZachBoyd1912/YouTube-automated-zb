# Make.com Scenarios

Import these JSON blueprints into Make.com to set up the full pipeline orchestration.

## Prerequisites

1. Your VPS is running the pipeline server (see `docker-compose.yml`)
2. You have noted your server's public IP/domain (e.g. `http://YOUR_VPS_IP:8000`)
3. You have set `API_SECRET_KEY` in your `.env` file

---

## How to Import

1. In Make.com, go to **Scenarios → Create a new scenario**
2. Click the **three-dot menu** → **Import Blueprint**
3. Paste the contents of the relevant `.json` file
4. After import, update any placeholder values (see per-scenario instructions below)

---

## Scenarios

### `01_daily_brief.json` — Daily Script + WhatsApp Brief

**Trigger:** Schedule — Monday to Friday, 07:00 Europe/Dublin

**What it does:** Calls `/stage1_and_2` on your pipeline server, which runs NexLev research, generates a script via Claude, writes to Google Sheets, and sends the WhatsApp brief to Zach.

**After import, configure:**
- In the **Scheduled Trigger** module: set timezone to `Europe/Dublin`, time to `07:00`, days to `Mon–Fri`
- In the **HTTP Request** module: replace `YOUR_VPS_IP` with your server address

---

### `02_edit_pipeline.json` — Auto-Edit on Upload

**Trigger:** Google Drive — watch for new files in `/YouTube Pipeline/uploads/`

**What it does:** When Zach drops a `.mp4` into the uploads folder, calls `/stage4` which transcribes, cuts, adds captions, and produces the edited video.

**After import, configure:**
- In the **Google Drive Watch** module: connect your Google account and set the watched folder to your `/YouTube Pipeline/uploads/` folder ID
- Add a **Router** to filter for `.mp4` files only (file name ends with `.mp4`)
- In the **HTTP Request** module: replace `YOUR_VPS_IP`, set `file_id` to the Drive module's `{{fileId}}` output

---

### `03_asset_generation.json` — Generate Thumbnails + Metadata

**Trigger:** Webhook (called by the `/stage4` endpoint on completion)

**What it does:** Calls `/stage5` to generate 3 DALL-E thumbnails, write YouTube metadata, and create the Shorts clip.

**After import, configure:**
- Copy the **Webhook URL** shown in Make.com after import
- Add that URL as `STAGE5_WEBHOOK_URL` to your `.env` so Stage 4 can call it on completion

---

### `04_upload_schedule.json` — Upload to YouTube

**Trigger:** Webhook (called by `/stage5` endpoint on completion)

**What it does:** Calls `/stage6` to upload the edited video to YouTube, set the scheduled publish time, create A/B tests, and cross-post.

**After import, configure:**
- Same webhook pattern as Scenario 03

---

### `05_weekly_analytics.json` — Sunday Analytics Report

**Trigger:** Schedule — Every Sunday, 09:00 Europe/Dublin

**What it does:** Calls `/stage7` to pull YouTube Analytics, resolve A/B tests with clear winners, and send the WhatsApp performance summary to Zach.

**After import, configure:**
- In the **Scheduled Trigger** module: set timezone to `Europe/Dublin`, time to `09:00`, day to `Sunday`
- In the **HTTP Request** module: replace `YOUR_VPS_IP`

---

## HTTP Module Configuration (All Scenarios)

Each HTTP Request module uses these settings:

| Field | Value |
|-------|-------|
| Method | POST |
| URL | `http://YOUR_VPS_IP:8000/stage[N]` |
| Headers | `Authorization: Bearer YOUR_API_SECRET_KEY` |
| Body type | `application/json` |
| Content-Type | `application/json` |

---

## Error Handling

Add a **Error Handler** route to each scenario that sends you a notification if the HTTP request fails or returns a non-200 status. The pipeline server also sends WhatsApp failure alerts directly, but Make.com's built-in error handling gives you a second line of defence.

Recommended: add a **Twilio** or **Email** module on the error route.
