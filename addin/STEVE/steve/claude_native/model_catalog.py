"""Preserve the exact account-picker route, including explicit context choices."""


def native_model(model):
    # Never silently upgrade a route: larger-context variants can use usage credits.
    return model


def supports_adaptive_thinking(model):
    return not (isinstance(model, str) and 'haiku-4-5' in model)
