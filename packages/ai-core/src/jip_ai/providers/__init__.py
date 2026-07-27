"""Provider adapters.

One real adapter and one fake, which is what
``docs/development/tasks/phase-3-resume-import.md`` settled on: the protocol
keeps business logic provider-independent, and a second real adapter written
before a second provider is needed would be a guess at what varies.
"""

from jip_ai.providers.fake import FakeLLMProvider

__all__ = ["FakeLLMProvider"]
