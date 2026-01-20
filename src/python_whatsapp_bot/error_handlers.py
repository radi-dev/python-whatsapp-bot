from typing import Any, Dict


def keys_exists(element:Dict[str, Any], *keys: Any)-> bool:
    '''
    Check if *keys (nested) exists in `element` (dict). e.g:
    data = {
    "spam": {
        "egg": {
            "bacon": "Well..",
            "sausages": "Spam egg sausages and spam",
            "spam": "does not have much spam in it"
        }
    }
    }
    keys_exists(data, "spam") -> True
    keys_exists(data, "spam", "bacon") -> False
    keys_exists(data, "spam", "egg") ->True
    Keys_exists(data, "spam", "egg", "bacon") ->True
    '''
    if not isinstance(element, dict):
        raise AttributeError('keys_exists() expects dict as first argument.')
    if len(keys) == 0:
        raise AttributeError(
            'keys_exists() expects at least two arguments, one given.')

    _element = element
    for key in keys:
        try:
            _element = _element[key]
        except KeyError:
            return False
    return True
