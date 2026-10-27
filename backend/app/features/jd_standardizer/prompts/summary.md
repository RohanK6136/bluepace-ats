---
version: 1
step: summary
---
## system
Write one sentence of at most {{ max_chars }} characters that tells a candidate what the role is. Include the job title. Mention location or role type only if given. No marketing adjectives. No first or second person. Do not mention pay, benefits or visas. Return JSON only.
## user
TITLE: {{ title }}
{% if role_type %}
ROLE TYPE: {{ role_type }}
{% endif %}
{% if location %}
LOCATION: {{ location }}
{% endif %}
{% if about %}
ABOUT THE ROLE: {{ about }}
{% endif %}
{% if responsibilities %}
RESPONSIBILITIES:
{% for r in responsibilities %}
- {{ r }}
{% endfor %}
{% endif %}
{% if repair_hint %}

REPAIR: the previous answer broke these rules; fix them: {{ repair_hint }}
{% endif %}
