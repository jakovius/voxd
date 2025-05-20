#!/usr/bin/env python3
import os

trigger_path = os.path.expanduser("~/.cache/whisp_trigger")
os.makedirs(os.path.dirname(trigger_path), exist_ok=True)
open(trigger_path, "w").close()
