---
name: analyst_job_brief
version: 1
flow: analyze_and_match
node: AJS Job Brief
model: LLM_AGENT_MODEL
settings: think=false, temperature 0.2 (retry 0.5, 0.8), format=<schema job_brief.schema.json>
---
Extract a job brief from the posting. Reply with one JSON object and nothing else, matching the JSON schema given below.
Rules:
- language is the posting language as an ISO 639-1 code (da or en).
- contact is the named recruiter or contact person with name, role, email and phone (null for unknown fields), or null if nobody is named. The user message may list CONTACT HINTS found by a regex pass: confirm or reject each one against the posting text, and take the name and role from the text next to it. Never invent a name, email or phone.
- must_have lists the required skills, experience and domain knowledge; nice_to_have lists the preferred ones. Do not put language requirements, location or work permit in must_have or nice_to_have; they belong in required_languages, danish_required, location and relocation_ok.
- seniority is the level as written (for example "senior", "lead", "junior") or null. remote describes remote or hybrid work as written, or null. deadline is the application deadline as written, or null.
- location is the work location as written (city or region), or null.
- relocation_ok is true if the posting offers relocation support or accepts candidates who still have to move, false if it requires living locally already, null if not stated.
- required_languages lists the ISO 639-1 codes of languages the posting requires (not "nice to have"). danish_required is true only if Danish is required.
- company_values lists values, principles or ways of working the posting itself states about the company (at most 3 short phrases of up to 4 words, in English); use [] if it states none. Never invent values.
- List items are short (at most 12 words) and in the posting's language. At most 25 keywords.
