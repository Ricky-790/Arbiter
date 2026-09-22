import json
import os

from dotenv import load_dotenv

load_dotenv()
import logfire.db_api

conn = logfire.db_api.connect(read_token=os.getenv("READ_TOKEN", ""))
cursor = conn.cursor()
cursor.execute("""SELECT
    start_timestamp,
    duration AS latency_seconds,
    span_name,
    trace_id,
    attributes
FROM records
WHERE attributes->>'arbiter.match_id' = '792754fc-d80b-44c4-ae74-555b17497673'
ORDER BY start_timestamp ASC;""")
rows = cursor.fetchall()
with open("a.json", "w") as f:
    f.write(json.dumps(rows, indent=2))
    f.close()
conn.close()
