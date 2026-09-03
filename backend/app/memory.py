from datetime import datetime, timezone

from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["aivar"]
selectors = db["healed_selectors"]
runs = db["runs"]

selectors.create_index([("url", 1), ("target", 1)], unique=True)


def get_healed_selector(url: str, target: str) -> dict | None:
    doc = selectors.find_one({"url": url, "target": target})
    if not doc:
        return None
    return {"strategy": doc["strategy"], "value": doc["value"], "role": doc.get("role")}


def save_healed_selector(url: str, target: str, strategy: str, value: str, role: str | None, reasoning: str) -> None:
    selectors.update_one(
        {"url": url, "target": target},
        {
            "$set": {
                "strategy": strategy,
                "value": value,
                "role": role,
                "reasoning": reasoning,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def save_run(intent: str, url: str, result: dict) -> None:
    runs.insert_one(
        {
            "intent": intent,
            "url": url,
            "status": result["status"],
            "results": result["results"],
            "healing_events": result["healing_events"],
            "created_at": datetime.now(timezone.utc),
        }
    )
