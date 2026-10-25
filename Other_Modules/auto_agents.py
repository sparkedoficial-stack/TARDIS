import sys, time
sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")
from core.subsystem_agents import get_agent_fleet
fleet = get_agent_fleet()
while True:
    fleet.run_all()
    time.sleep(900)
