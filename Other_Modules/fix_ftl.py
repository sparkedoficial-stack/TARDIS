import sys
import os
sys.path.insert(0, "/home/timemachine/.ftl")

from easy_touch_agent import EasyTouchSelfImprovementAgent

agent = EasyTouchSelfImprovementAgent.get_instance()
print("Auditing all unresolved FTL issues...")
unresolved = agent.audit_all_unresolved()
print(f"Found {len(unresolved)} unresolved issues.")

print("Solving all unresolved issues...")
report = agent.solve_all_unresolved()
print("Report:")
print(report)
