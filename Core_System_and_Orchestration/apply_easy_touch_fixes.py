import sys
import os
sys.path.insert(0, "/home/timemachine/.ftl")

from easy_touch import EasyTouchEngine

engine = EasyTouchEngine.get_instance()

print("Applying easy touch healing to CloudCode DNS timeout...")
engine.intercept_execution(
    command_or_task="FTL SOBERANO :: PLAN COGNITIVO (KAIJU)",
    returncode=1,
    output="error: Eligibility check failed: Post \"https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist\": dial tcp: lookup daily-cloudcode-pa.googleapis.com on REDACTED_IP:53: i/o timeout",
    is_shell=False
)

print("Applying easy touch healing to iMac cluster timeout...")
engine.intercept_execution(
    command_or_task="FTL SOBERANO :: PLAN COGNITIVO (IMAC)",
    returncode=1,
    output="Fallo al contactar el clúster iMac: timed out",
    is_shell=False
)

print("Easy Touch healing applied to all FTL failures.")
