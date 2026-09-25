import json
import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()
import logfire.db_api

conn = logfire.db_api.connect(
    read_token=os.getenv("READ_TOKEN", ""), min_timestamp=timedelta(days=14)
)
cursor = conn.cursor()
cursor.execute("""(
  SELECT
    attributes->>'arbiter.agent_role' AS agent_role,
    start_timestamp,
    attributes->'pydantic_ai.all_messages' AS chat_history
  FROM records
  WHERE
    attributes->>'arbiter.match_id' = '3bac8e3e-292a-40b6-bf3d-17584427e3dc'
    AND attributes->>'arbiter.agent_role' = 'prisoner'
    AND span_name = 'invoke_agent agent'
    AND start_timestamp <= '2026-09-21T16:16:30Z'
  ORDER BY start_timestamp DESC
  LIMIT 1
)
UNION ALL
(
  SELECT
    attributes->>'arbiter.agent_role' AS agent_role,
    start_timestamp,
    attributes->'pydantic_ai.all_messages' AS chat_history
  FROM records
  WHERE
    attributes->>'arbiter.match_id' = '3bac8e3e-292a-40b6-bf3d-17584427e3dc'
    AND attributes->>'arbiter.agent_role' = 'warden'
    AND span_name = 'invoke_agent agent'
    AND start_timestamp <= '2026-09-21T16:16:30Z'
  ORDER BY start_timestamp DESC
  LIMIT 1
)""")
rows = cursor.fetchall()
with open("a.json", "w") as f:
    f.write(json.dumps(rows, indent=2))
    f.close()
conn.close()
