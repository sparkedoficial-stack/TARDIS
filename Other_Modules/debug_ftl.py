import sys
import os
sys.path.insert(0, "/home/timemachine/.ftl")

from easy_touch_agent import EasyTouchSelfImprovementAgent

agent = EasyTouchSelfImprovementAgent.get_instance()
unresolved = agent.audit_all_unresolved()
print("Total incidents:", len(agent.unresolved_incidents))
for key, inc in agent.unresolved_incidents.items():
    print(key, inc.status)
