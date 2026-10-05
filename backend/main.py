import json
import os

import logfire.db_api
from dotenv import load_dotenv

load_dotenv()
with logfire.db_api.connect(
    read_token=os.getenv("LOGFIRE_TOKEN", ""), base_url=os.getenv("LOGFIRE_BASE_URL")
) as conn:
    cursor = conn.cursor()
    cursor.execute(
        """SELECT
          start_timestamp,
          CASE
            WHEN span_name LIKE 'chat%' THEN 'THOUGHTS_AND_CHAT'
            WHEN span_name LIKE 'tool execution%' THEN 'TOOL_CALL'
          END AS step_type,
          -- Extract thinking process from the model parts
          COALESCE(
            attributes -> 'gen_ai.output.messages' -> 0 -> 'parts' -> 0 ->> 'content',
            attributes -> 'gen_ai.output.messages' -> 0 -> 'parts' -> 0 ->> 'thinking'
          ) AS prisoner_thoughts,
          -- Extract actual messages sent
          attributes -> 'gen_ai.output.messages' -> 0 -> 'parts' -> 1 ->> 'content' AS prisoner_message,
          -- Extract tool call details
          attributes ->> 'arbiter.tool_name' AS tool_name,
          attributes -> 'arbiter.tool_args' AS tool_arguments,
          attributes ->> 'arbiter.success' AS tool_success,
          attributes ->> 'arbiter.output_preview' AS tool_response_preview
        FROM records
        WHERE
          (
            attributes ->> 'arbiter.match_id' = '388f7643-d7ad-4a0d-acf9-69a7252478ff'
            OR attributes ->> 'match_id' = '388f7643-d7ad-4a0d-acf9-69a7252478ff'
          )
          AND attributes ->> 'arbiter.agent_role' = 'prisoner'
          AND (
            span_name LIKE 'chat%'
            OR span_name LIKE 'tool execution%'
          )
        ORDER BY start_timestamp ASC""",
    )
    data = cursor.fetchall()

    with open("a2.json", "w") as f:
        f.write(json.dumps(data, indent=4))
        f.close()
