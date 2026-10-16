import subprocess
import sys

result = subprocess.run(
    ['cmd', '/c', 'cd C:\\Users\\User\\Desktop\\NEXUS-Personal-AI-Operating-System\\backend && alembic upgrade head'],
    capture_output=True,
    text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)