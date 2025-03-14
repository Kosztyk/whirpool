This is basically the official integration with 2 more sensor for Temperature and Humidity for AirCon. I find them useful if you wand to build a custom dashboard aor automation.

![Screenshot 2025-03-14 at 10 11 28](https://github.com/user-attachments/assets/bfee804d-e744-4d0c-b19a-07362ec7dac7)
![Screenshot 2025-03-14 at 10 11 55](https://github.com/user-attachments/assets/c45fc192-343c-4acb-9259-a43cb276c670)
![Screenshot 2025-03-14 at 10 15 33](https://github.com/user-attachments/assets/1d31d5bb-4ef3-4c4b-93fd-7784795456d6)

Example of sensor card 

type: horizontal-stack
cards:
   - type: custom:mushroom-template-card
    primary: Livingroom
    secondary: |-
      {{states('sensor.living_air_conditioner_current_temperature')}}°C / H
      {{states('sensor.living_air_conditioner_current_humidity')}}%
    icon: mdi:home-circle
    icon_color: |-
      {% if is_state('switch.living_switch_1', 'on') %}
        orange
      {% endif %}
    tap_action:
      action: navigate
      navigation_path: living
    hold_action:
      action: toggle
    entity: switch.living_switch_1
