from app.providers.alertmanager import AlertmanagerProvider
from app.providers.base import AlertProvider

_PROVIDERS: dict[str, AlertProvider] = {
    AlertmanagerProvider.name: AlertmanagerProvider(),
    # "datadog": DatadogProvider(),   <- future providers register here
}


def get_provider(name: str) -> AlertProvider:
    return _PROVIDERS[name]  # KeyError for unknown providers (404 at the API layer)
