# Deployment checklist

*optional run >> python3 -m pip install --upgrade build
*optional run >> python3 -m pip install --upgrade twine

✅change version of pyproject.toml

✅delete src/python_whatsapp_bot.egg-info/ if exists
✅delete dist/ if exists

✅run >> python3 -m build
✅run >> python3 -m twine upload dist/*
💡use __token__ as username
💡enter password with the pypi prefix
