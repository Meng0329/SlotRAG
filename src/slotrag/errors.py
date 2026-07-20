class SlotRAGError(Exception):
    """Base error for expected SlotRAG failures."""


class ConfigurationError(SlotRAGError):
    pass


class ProviderError(SlotRAGError):
    pass


class SchemaError(ProviderError):
    pass


class DatasetError(SlotRAGError):
    pass
