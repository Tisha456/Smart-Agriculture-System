"""Self-check for the Gemini plant-diagnosis field derivation
(main.finalize_plant_diagnosis). Run: python backend/test_plant_predict.py
Needs backend/.env present (for the Supabase client main.py creates at
import time) but makes no network calls."""
from main import finalize_plant_diagnosis

# Healthy, confident plant -> not low_confidence.
healthy = finalize_plant_diagnosis(
    {"is_plant": True, "species_confidence": 0.9, "condition_confidence": 0.95},
    "gemini-3.6-flash", 850,
)
assert healthy["joint_confidence"] == 0.9 * 0.95
assert healthy["low_confidence"] is False
assert healthy["model_version"] == "gemini:gemini-3.6-flash"
assert healthy["inference_ms"] == 850

# Diseased but the model is unsure about the species -> low_confidence kicks in
# below the 0.45 joint threshold even though is_plant is true.
unsure = finalize_plant_diagnosis(
    {"is_plant": True, "species_confidence": 0.5, "condition_confidence": 0.5},
    "gemini-3.6-flash", 100,
)
assert unsure["joint_confidence"] == 0.25
assert unsure["low_confidence"] is True

# Not a plant at all -> always low_confidence regardless of reported scores.
not_plant = finalize_plant_diagnosis(
    {"is_plant": False, "species_confidence": 0.99, "condition_confidence": 0.99},
    "gemini-3.6-flash", 100,
)
assert not_plant["low_confidence"] is True

# Missing confidence fields shouldn't crash (Gemini/schema hiccup) -> treated as 0.
missing = finalize_plant_diagnosis({"is_plant": True}, "gemini-3.6-flash", 100)
assert missing["joint_confidence"] == 0
assert missing["low_confidence"] is True

print("test_plant_predict: all assertions passed")
