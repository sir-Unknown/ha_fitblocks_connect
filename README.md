# Fitblocks Connect

This custom integration connects Home Assistant to your Fitblocks Connect account and exposes your upcoming schedule as a calendar plus a few sensors.

## Features

- Calendar entity that shows only lessons you are enrolled in
- Sensors for:
  - Remaining credits
  - Number of upcoming enrolled lessons
  - Up to 4 “next lesson” timestamp sensors (disabled by default) with rich attributes
- Services to enroll/unenroll in lessons
- Reauthentication flow when credentials expire

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS (category: Integration)
2. Install the integration
3. Restart Home Assistant

### Manual

1. Copy `custom_components/fitblocks_connect/` into your Home Assistant `config/custom_components/`
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & services** → **Add integration**
2. Search for **Fitblocks Connect**
3. Fill in:
   - `base_url` (default: `https://fitblocks.nl`)
   - `box` (the gym slug in the URL, for example `physicsperformance`)
   - `username` (your email address)
   - `password`
   - `display_name` (optional; used as the “service device” name in Home Assistant)

The integration title is detected from the Fitblocks UI when possible; otherwise it falls back to `box @ base_url`.

## Entities

### Calendar

- Shows upcoming lessons where you are enrolled (`subscribed: true`)
- Read-only (creating/updating/deleting events via Home Assistant is not supported)

### Sensors

- `Remaining credits`: highest known `credits_remaining` across upcoming enrolled lessons (falls back to last known credits)
- `Enrolled lessons`: count of upcoming enrolled lessons
- `Lesson 1` .. `Lesson 4` (disabled by default): start time of the Nth upcoming enrolled lesson

The lesson sensors include attributes that can be used for automations, including:
`start`, `end`, `workout`, `description`, `occupancy`, `participants_count`, `credits_remaining`, `class_type_id`, `event_id`, `schedule_registration_id`.

## Services

The integration registers these services:

- `fitblocks_connect.enroll`
  - `start` (datetime)
  - `end` (datetime)
  - `class_type_id` (UUID)
- `fitblocks_connect.unenroll`
  - `schedule_registration_id` (UUID)
  - `class_type_id` (UUID)

If you have multiple Fitblocks Connect config entries, you must provide `config_entry_id`.

### Example: unenroll from the next lesson

Use a “Lesson 1” sensor as the source for `schedule_registration_id` and `class_type_id`:

```yaml
action:
  - service: fitblocks_connect.unenroll
    data:
      schedule_registration_id: "{{ state_attr('sensor.fitblocks_lesson_1','schedule_registration_id') }}"
      class_type_id: "{{ state_attr('sensor.fitblocks_lesson_1','class_type_id') }}"
```

## Notes

- The schedule is fetched from Fitblocks Connect and refreshed periodically (cloud polling)
- The coordinator fetches a 7-day window of events and enriches enrolled lessons with details (credits, occupancy, participants, registration id)

## Troubleshooting

- “Failed to connect”: verify `base_url` and `box` and check if the Fitblocks website is reachable from your Home Assistant instance
- “Invalid authentication”: verify your email/password; if it used to work, use the reauthentication prompt in Home Assistant
- Services failing with multiple accounts: pass `config_entry_id` to select the right account

## Disclaimer

This integration is not affiliated with Fitblocks. Fitblocks Connect endpoints may change and break functionality.
