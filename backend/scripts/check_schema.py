from psycopg import connect

conn = connect(host='127.0.0.1', port=64244, user='nexus', password='nexus', dbname='nexus')
cur = conn.cursor()

# Check agent_runs columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agent_runs'")
columns = [row[0] for row in cur.fetchall()]
print('Columnas en agent_runs:', columns)

conn.close()