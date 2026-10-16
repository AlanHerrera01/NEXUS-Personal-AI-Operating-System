from psycopg import connect

conn = connect(host='127.0.0.1', port=64244, user='nexus', password='nexus', dbname='nexus')
cur = conn.cursor()

# Add user_id column
print('Adding user_id column to agent_runs...')
try:
    cur.execute("ALTER TABLE agent_runs ADD COLUMN user_id UUID")
    print('Column added successfully')
    conn.commit()
except Exception as e:
    print('Error:', e)

conn.close()
print('Done')