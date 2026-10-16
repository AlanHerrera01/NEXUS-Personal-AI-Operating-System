from psycopg import connect

conn = connect(host='127.0.0.1', port=64244, user='nexus', password='nexus', dbname='nexus')
cur = conn.cursor()

# Check columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agents'")
columns = [row[0] for row in cur.fetchall()]
print('Columnas en agents:', columns)

# Check count
cur.execute("SELECT count(*) FROM agents")
count = cur.fetchone()[0]
print('Filas en agents:', count)

# Try to add user_id if missing (PostgreSQL alter table)
if 'user_id' not in columns:
    print('Adding user_id column...')
    try:
        cur.execute("ALTER TABLE agent_runs ADD COLUMN user_id UUID")
        print('user_id column added')
    except Exception as e:
        print('Error adding column:', e)

conn.commit()
conn.close()
print('Done')