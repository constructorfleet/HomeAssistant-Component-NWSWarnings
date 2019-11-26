# National Weather Service (NWS) Warnings for Home Assistant
Home Assistant Custom Component for National Weather Service Warnings

# Installation
1. Place folder (nws_warnings) in custom_components folder

# Configuration
```yaml
sensor:
  - platform: nws_warnings
    name: NWS Warnings
    icon: mdi:alert
    severity:
      - extreme
      - severe
    message_type:
      - alert
      - update
    zone: zone.home
    forecast_days: 3
```

**name** (optional)(string) Name of the sensor  
**icon** (optional)(string) Material Design Icon identifier  
**severity** (optional)(string|list of strings) Severity of alerts to report  
valid entries: unknown, minor, moderate, severe, extreme  
**message_type** (optional)(string|list of strings) Message types to report  
valid enties: alert, update  
**zone** (optional)(entity_id) Entity ID of the zone to get report for  
**forecast_days** (optional)(int(1-5)) How many days in the future to retrieve warnings for