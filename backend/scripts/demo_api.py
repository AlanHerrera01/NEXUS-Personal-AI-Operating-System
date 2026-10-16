from uuid import UUID
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.main import app

# Usar la sesión existente
session = SessionFactory()
repository = SqlAlchemyAgentRepository(session)

# Usar el agente que ya existe en la BD
agent_id = UUID('7be1284b-774b-4bf5-8f6b-ee5b95bddf9a')
agent = repository.get_by_id(agent_id)
print('Agent found:', agent.name if agent else None)

# Crear client
client = TestClient(app)

# Probar el endpoint
response = client.post(
    f'/api/v1/agents/{agent_id}/runs',
    json={'input': 'Revisa mis tareas pendientes'},
)

print('Status code:', response.status_code)
if response.status_code == 201:
    body = response.json()
    print('Status:', body.get('status'))
    print('Response:', body.get('response', '')[:100])
    print('Actions:', body.get('actions', []))
else:
    print('Error body:', response.text[:200])

# Cleanup
session.close()