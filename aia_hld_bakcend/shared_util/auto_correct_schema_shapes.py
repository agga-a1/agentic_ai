from typing import Any, Dict, Type
from pydantic import BaseModel

def auto_correct_schema_shapes(agent_output: Dict[str, Any], schema_model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Dynamically corrects agent output to match the expected shapes from a Pydantic schema.
    - Converts lists to dicts or dicts to lists of dicts as needed.
    - Never hardcodes section names.
    """
    corrected = agent_output.copy()
    for field_name, field in schema_model.model_fields.items():
        expected_type = field.annotation
        value = corrected.get(field_name)
        # Handle dict
        if (isinstance(expected_type, type) and issubclass(expected_type, BaseModel)) or \
           (hasattr(expected_type, "__origin__") and expected_type.__origin__ is dict):
            if isinstance(value, list):
                # If agent outputted a list, try to merge into dict
                merged = {}
                for item in value:
                    if isinstance(item, dict):
                        merged.update(item)
                corrected[field_name] = merged if merged else {}
        # Handle list of dicts
        elif hasattr(expected_type, "__origin__") and expected_type.__origin__ is list:
            inner_type = expected_type.__args__[0]
            if isinstance(value, dict):
                # If agent outputted a dict, wrap in list
                corrected[field_name] = [value]
            elif isinstance(value, list):
                # If agent outputted a list of strings, convert to list of dicts with placeholder keys
                if all(isinstance(item, str) for item in value):
                    # Try to infer key name from inner_type
                    key_names = getattr(inner_type, "model_fields", {}).keys() if hasattr(inner_type, "model_fields") else ["value"]
                    corrected[field_name] = [{next(iter(key_names)): item} for item in value]
        # Otherwise, leave as-is
    return corrected