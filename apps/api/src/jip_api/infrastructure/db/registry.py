"""Model registry.

Importing this module imports every ORM model module, which is what populates
``Base.metadata``. Alembic autogenerate and any ``create_all`` need that
metadata to be complete; a model that no one imports is invisible to both, and
the symptom is a migration that silently omits a table.

Add every new model module here.
"""

from jip_api.domain.career import models as career_models
from jip_api.domain.users import models as user_models

__all__ = ["career_models", "user_models"]
