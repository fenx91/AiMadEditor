"""Persistence helpers for named editor setups."""

import datetime
import json
import os
import re


def sanitize_setup_name(name):
    cleaned = re.sub(r"[^\w\s\u4e00-\u9fa5\-]", "", name or "default").strip()
    return cleaned or "default"


def save_setup(data, name=None):
    os.makedirs("data/setups", exist_ok=True)
    safe_name = sanitize_setup_name(name)
    with open(f"data/setups/{safe_name}.json", "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    return safe_name


def list_setups():
    setups_dir = "data/setups"
    if not os.path.exists(setups_dir):
        return []
    files = []
    for filename in os.listdir(setups_dir):
        if filename.endswith(".json"):
            path = os.path.join(setups_dir, filename)
            mtime = datetime.datetime.fromtimestamp(os.stat(path).st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            files.append({"name": filename[:-5], "mtime": mtime})
    files.sort(key=lambda item: item["mtime"], reverse=True)
    return files


def load_setup(name=None):
    safe_name = sanitize_setup_name(name)
    path = f"data/setups/{safe_name}.json"
    if safe_name == "default" and not os.path.exists(path) and os.path.exists("data/v_tiao_setup.json"):
        path = "data/v_tiao_setup.json"
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)
